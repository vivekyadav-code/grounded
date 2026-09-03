#!/usr/bin/env python3
"""A small provider chain: Gemini over HTTP, Claude via its CLI.

Failure classes are kept apart, because collapsing them is how these systems
break: a malformed answer means retry the same provider, an availability
failure means stop asking it for a while, and a rate limit means wait.
"""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEMINI_MODEL = os.environ.get("GROUNDED_MODEL", "gemini-2.5-flash")
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{m}:generateContent?key={k}")
COOLDOWN = 600
_down = {}


class LLMError(RuntimeError):
    pass


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
    return None


def _available(name):
    until = _down.get(name, 0)
    if until and time.time() < until:
        return False
    _down.pop(name, None)
    return True


def _mark_down(name):
    _down[name] = time.time() + COOLDOWN


def _gemini(prompt, schema, timeout):
    key = _key()
    if not key:
        raise LLMError("no GEMINI_API_KEY")
    cfg = {"temperature": 0, "maxOutputTokens": 1400,
           "thinkingConfig": {"thinkingBudget": 0}}
    if schema:
        cfg["responseMimeType"] = "application/json"
        prompt += "\n\nReturn ONLY JSON matching: " + json.dumps(schema)
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
    req = urllib.request.Request(GEMINI_URL.format(m=GEMINI_MODEL, k=key),
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise LLMError("rate limited") from e
        _mark_down("gemini")
        raise LLMError(f"gemini HTTP {e.code}") from e
    except urllib.error.URLError as e:
        _mark_down("gemini")
        raise LLMError(f"gemini unreachable: {e.reason}") from e
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise LLMError("gemini returned no text") from e


def _claude(prompt, schema, timeout):
    exe = "claude"
    args = [exe, "-p", prompt, "--disallowed-tools", "*"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        _mark_down("claude")
        raise LLMError(f"claude unavailable: {type(e).__name__}") from e
    if r.returncode != 0:
        _mark_down("claude")
        raise LLMError(f"claude exited {r.returncode}")
    return r.stdout.strip()


PROVIDERS = [("gemini", _gemini), ("claude", _claude)]


def _extract_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMError("no JSON in reply")


def generate(prompt, schema=None, timeout=90, order=None):
    """Returns (parsed_or_text, provider_name). Raises only if all providers fail."""
    errors = []
    names = order or [n for n, _ in PROVIDERS]
    for name in names:
        fn = dict(PROVIDERS).get(name)
        if fn is None or not _available(name):
            errors.append(f"{name}: skipped")
            continue
        for attempt in (1, 2):
            try:
                text = fn(prompt, schema, timeout)
            except LLMError as e:
                errors.append(f"{name}: {e}")
                break                       # provider-level problem, move on
            if not schema:
                return text, name
            try:
                return _extract_json(text), name   # bad output: retry once
            except LLMError as e:
                errors.append(f"{name}: attempt {attempt}: {e}")
    raise LLMError("all providers failed — " + "; ".join(errors[:4]))
