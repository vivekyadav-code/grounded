#!/usr/bin/env python3
"""Embeddings, with the two things that actually matter in production:
a cache, so re-ingesting a corpus doesn't re-buy every vector, and a
retry policy that tells a rate limit apart from a real failure.
"""
import hashlib
import json
import os
import re
import sqlite3
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("GROUNDED_EMBED_MODEL", "gemini-embedding-001")
DIMS = int(os.environ.get("GROUNDED_EMBED_DIMS", "768"))
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:embedContent?key={k}"
BACKOFF = (4, 12, 30)          # free-tier embedding quota is small


class EmbedError(RuntimeError):
    """Embedding could not be produced. Never silently returns zeros —
    a zero vector retrieves nothing and looks like a bad corpus."""


def _key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for f in (ROOT / "env.sh", ROOT.parent / "ai-video-generator" / "env.sh"):
        try:
            m = re.search(r"GEMINI_API_KEY=([^\s\"']+)", f.read_text())
        except OSError:
            continue
        if m:
            return m.group(1)
    raise EmbedError("no GEMINI_API_KEY (env or env.sh)")


def pack(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob):
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class Cache:
    """Content-addressed: the same text at the same model is bought once."""

    def __init__(self, path=None):
        self.path = Path(path or ROOT / "cache" / "embeddings.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS vec ("
                        "k TEXT PRIMARY KEY, model TEXT, dims INT, v BLOB)")
        self.db.commit()
        self.hits = self.misses = 0

    @staticmethod
    def key(text, model, dims):
        return hashlib.sha256(f"{model}:{dims}:{text}".encode()).hexdigest()

    def get(self, text, model=MODEL, dims=DIMS):
        row = self.db.execute("SELECT v FROM vec WHERE k=?",
                              (self.key(text, model, dims),)).fetchone()
        if row:
            self.hits += 1
            return unpack(row[0])
        self.misses += 1
        return None

    def put(self, text, vec, model=MODEL, dims=DIMS):
        self.db.execute("INSERT OR REPLACE INTO vec VALUES (?,?,?,?)",
                        (self.key(text, model, dims), model, dims, pack(vec)))
        self.db.commit()


def _call(text, task, model, dims, timeout=60):
    body = {"content": {"parts": [{"text": text}]},
            "outputDimensionality": dims,
            "taskType": task}
    url = ENDPOINT.format(m=model, k=_key())
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    for wait in (*BACKOFF, None):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["embedding"]["values"]
        except urllib.error.HTTPError as e:
            # 429 is "slow down" and is worth waiting for; nothing else is.
            if e.code != 429 or wait is None:
                raise EmbedError(f"embedding failed: HTTP {e.code}") from e
            time.sleep(wait)
        except urllib.error.URLError as e:
            raise EmbedError(f"embedding failed: {e.reason}") from e
    raise EmbedError("embedding failed: rate limited")


def embed(text, task="RETRIEVAL_DOCUMENT", cache=None, model=MODEL, dims=DIMS):
    """Embed one string.

    `task` matters: a question and a passage are embedded into the same space
    but with different roles, and using the document task for queries measurably
    hurts retrieval.
    """
    text = (text or "").strip()
    if not text:
        raise EmbedError("refusing to embed empty text")
    if cache is not None:
        hit = cache.get(f"[{task}] {text}", model, dims)
        if hit is not None:
            return hit
    vec = _call(text, task, model, dims)
    if len(vec) != dims:
        raise EmbedError(f"expected {dims} dims, got {len(vec)}")
    # The cache stores float32. Quantise on the way out too, so a warm cache
    # and a cold one return byte-identical vectors — otherwise retrieval
    # scores drift depending on whether something happened to be cached.
    vec = unpack(pack(vec))
    if cache is not None:
        cache.put(f"[{task}] {text}", vec, model, dims)
    return vec


def embed_query(text, cache=None):
    return embed(text, task="RETRIEVAL_QUERY", cache=cache)
