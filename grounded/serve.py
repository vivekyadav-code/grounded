#!/usr/bin/env python3
"""HTTP service.

Everything here exists because a container needs it and a laptop doesn't:
config validated at boot (fail fast, not on the first request), liveness
separated from readiness, per-request correlation IDs in structured logs,
a rate limit so one caller cannot spend the whole quota, and metrics that
answer "is it healthy" without opening a shell.
"""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .answer import ABSTAIN_BELOW, ask
from .embed import Cache
from .llm import RateLimited
from .store import Store

WEB = Path(__file__).resolve().parent.parent / "web"
STARTED = time.time()
MAX_QUESTION = 500

METRICS = {"requests": 0, "answered": 0, "abstained": 0, "errors": 0,
           "rate_limited": 0, "upstream_rate_limited": 0, "unauthorized": 0}
_lock = threading.Lock()


def _has_key(env):
    if env.get("GEMINI_API_KEY"):
        return True
    from .embed import EmbedError, _key
    try:
        return bool(_key())
    except EmbedError:
        return False


class Config:
    """Read once, validated once. A misconfigured container should refuse to
    start, not fail on whichever request happens to hit the broken path."""

    def __init__(self, env=None):
        env = env if env is not None else os.environ
        self.port = int(env.get("PORT", "8080"))
        self.api_key = env.get("GROUNDED_API_KEY", "").strip()
        self.rate_limit = int(env.get("GROUNDED_RATE_LIMIT", "30"))   # per minute
        self.abstain_below = float(env.get("GROUNDED_ABSTAIN_BELOW", ABSTAIN_BELOW))
        self.k = int(env.get("GROUNDED_TOP_K", "5"))
        self.problems = []
        if not (1 <= self.port <= 65535):
            self.problems.append(f"PORT {self.port} out of range")
        if not 0 < self.abstain_below < 1:
            self.problems.append("GROUNDED_ABSTAIN_BELOW must be between 0 and 1")
        if self.k < 1:
            self.problems.append("GROUNDED_TOP_K must be at least 1")
        # Ask the embedder whether it can find a key rather than checking
        # os.environ here: it also reads env.sh, so checking only the
        # environment made the boot check stricter than the real capability
        # and refused to start a service that would have worked.
        if not env.get("GROUNDED_ALLOW_NO_KEY") and not _has_key(env):
            self.problems.append(
                "no Gemini API key — set GEMINI_API_KEY or put it in env.sh")

    @property
    def auth_required(self):
        return bool(self.api_key)


class RateLimiter:
    """Fixed window per client. Crude on purpose — it protects the API budget,
    it is not a security control."""

    def __init__(self, per_minute):
        self.per_minute = per_minute
        self.hits = {}
        self.lock = threading.Lock()

    def allow(self, who):
        if self.per_minute <= 0:
            return True
        now = int(time.time() // 60)
        with self.lock:
            window, count = self.hits.get(who, (now, 0))
            if window != now:
                window, count = now, 0
            if count >= self.per_minute:
                self.hits[who] = (window, count)
                return False
            self.hits[who] = (window, count + 1)
            return True


def log(**fields):
    """One JSON object per line to stdout — what every log shipper expects,
    and what makes a request greppable by its correlation id."""
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      **fields}, separators=(",", ":")), flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "grounded"
    config = None
    limiter = None
    store = None
    cache = None

    def log_message(self, *a):        # replaced by structured logging
        pass

    # ------------------------------------------------------------- plumbing
    def _send(self, code, payload, request_id=None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if request_id:
            self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(body)

    def _serve_body(self, code, text, ctype):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _client(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return "key:" + auth[7:][:8]
        fwd = self.headers.get("X-Forwarded-For", "")
        return "ip:" + (fwd.split(",")[0].strip() or self.client_address[0])

    def _authorized(self):
        if not self.config.auth_required:
            return True
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and auth[7:] == self.config.api_key

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            # liveness: the process is up. Deliberately does NOT touch the
            # index — a slow dependency must not get the container killed.
            return self._send(200, {"status": "ok",
                                    "uptime_s": round(time.time() - STARTED, 1)})
        if path == "/readyz":
            # readiness: can it actually serve? Different question, different
            # answer, different consequence.
            n = self.store.count()
            ok = n > 0
            return self._send(200 if ok else 503,
                              {"ready": ok, "chunks": n,
                               "reason": None if ok else "index is empty"})
        if path == "/metrics":
            with _lock:
                lines = [f"grounded_{k} {v}" for k, v in METRICS.items()]
            lines.append(f"grounded_chunks {self.store.count()}")
            lines.append(f"grounded_uptime_seconds {round(time.time() - STARTED, 1)}")
            return self._text(200, "\n".join(lines) + "\n")
        if path == "/api/info":
            rows = self.store.db.execute(
                "SELECT source, COUNT(*) n FROM chunks GROUP BY source"
                " ORDER BY source").fetchall()
            return self._send(200, {
                "chunks": self.store.count(),
                "documents": [{"source": r[0], "chunks": r[1]} for r in rows],
                "threshold": self.config.abstain_below,
                "auth_required": self.config.auth_required,
                "top_k": self.config.k})
        if path == "/":
            page = WEB / "index.html"
            if page.exists():
                # NOT _send(): its third parameter is request_id, so passing a
                # content type there served the page as JSON and put the whole
                # document into a response header.
                return self._serve_body(200, page.read_text(),
                                        "text/html; charset=utf-8")
            return self._send(200, {"service": "grounded",
                                    "endpoints": ["/ask", "/api/info", "/healthz",
                                                  "/readyz", "/metrics"],
                                    "chunks": self.store.count()})
        return self._send(404, {"error": "not found"})

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        request_id = self.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        started = time.time()
        path = self.path.split("?")[0]
        if path != "/ask":
            return self._send(404, {"error": "not found"}, request_id)

        with _lock:
            METRICS["requests"] += 1

        if not self._authorized():
            with _lock:
                METRICS["unauthorized"] += 1
            log(level="warn", request_id=request_id, path=path, status=401,
                client=self._client())
            return self._send(401, {"error": "unauthorized"}, request_id)

        who = self._client()
        if not self.limiter.allow(who):
            with _lock:
                METRICS["rate_limited"] += 1
            log(level="warn", request_id=request_id, path=path, status=429, client=who)
            return self._send(429, {"error": "rate limited",
                                    "limit_per_minute": self.config.rate_limit},
                              request_id)

        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                raise ValueError("body too large")
            body = json.loads(self.rfile.read(n) or b"{}")
            question = str(body.get("question", "")).strip()
        except (ValueError, json.JSONDecodeError) as e:
            with _lock:
                METRICS["errors"] += 1
            return self._send(400, {"error": f"bad request: {e}"}, request_id)

        if not question:
            return self._send(400, {"error": "question is required"}, request_id)
        if len(question) > MAX_QUESTION:
            return self._send(400, {"error": f"question exceeds {MAX_QUESTION} characters"},
                              request_id)

        try:
            # trace=False: in a container the SQLite trace table is ephemeral
            # and lost on every restart, and writing it adds contention for no
            # benefit. The structured stdout log below IS the trace — that's
            # what the platform collects and what a log shipper can query.
            r = ask(question, store=self.store, cache=self.cache,
                    k=self.config.k, abstain_below=self.config.abstain_below,
                    trace=False)
        except RateLimited:
            # temporary and retryable — saying 502 here tells the caller to
            # give up on something that will work again in a minute
            with _lock:
                METRICS["upstream_rate_limited"] += 1
            log(level="warn", request_id=request_id, path=path, status=503,
                error="upstream rate limited",
                duration_ms=int((time.time() - started) * 1000))
            self.send_response(503)
            body = json.dumps({"error": "upstream model is rate limited, retry shortly",
                               "retry_after_s": 60, "request_id": request_id}).encode()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", "60")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-Id", request_id)
            self.end_headers()
            return self.wfile.write(body)
        except Exception as e:
            with _lock:
                METRICS["errors"] += 1
            log(level="error", request_id=request_id, path=path, status=502,
                error=f"{type(e).__name__}: {e}"[:200],
                duration_ms=int((time.time() - started) * 1000))
            # the caller gets a category, not a stack trace
            return self._send(502, {"error": "upstream model or index failure",
                                    "request_id": request_id}, request_id)

        with _lock:
            METRICS["answered" if r["answered"] else "abstained"] += 1

        payload = {
            "request_id": request_id,
            "question": question,
            "answered": r["answered"],
            "answer": r["answer"],
            "top_score": round(r["top_score"], 4),
            "threshold": self.config.abstain_below,
            "sources": [
                {"n": i, "source": h["source"], "heading": h["heading"],
                 "cited": i in r["citations"], "score": round(score, 4),
                 "why": why, "excerpt": h["text"][:300]}
                for i, (h, score, why) in enumerate(r["hits"], 1)],
        }
        log(level="info", request_id=request_id, path=path, status=200,
            client=who, answered=r["answered"], top_score=round(r["top_score"], 4),
            provider=r["provider"], citations=len(r["citations"]),
            duration_ms=int((time.time() - started) * 1000))
        return self._send(200, payload, request_id)


def serve(config=None):
    config = config or Config()
    if config.problems:
        for p in config.problems:
            log(level="fatal", error=p)
        raise SystemExit(2)

    Handler.config = config
    Handler.limiter = RateLimiter(config.rate_limit)
    Handler.store = Store()
    Handler.cache = Cache()

    httpd = ThreadingHTTPServer(("0.0.0.0", config.port), Handler)
    log(level="info", event="listening", port=config.port,
        chunks=Handler.store.count(), auth="required" if config.auth_required else "open",
        rate_limit_per_minute=config.rate_limit)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log(level="info", event="shutdown")
    finally:
        httpd.server_close()
