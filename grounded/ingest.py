#!/usr/bin/env python3
"""Turn documents into retrievable chunks.

Chunking is where most RAG quality is won or lost, so this is deliberate:

  - Split on markdown headings first. A heading marks a topic boundary the
    author already decided on; splitting on a character count throws that away.
  - Carry the heading path INTO the chunk text. A chunk reading "run it with
    --no-open" is useless out of context; "Operations > Serving > run it with
    --no-open" retrieves and answers correctly.
  - Only then split oversized sections, on paragraph boundaries, with overlap
    so a fact spanning the seam survives in one piece.
"""
import re
from pathlib import Path

from .embed import Cache, embed
from .store import Store, tokenize

MAX_TOKENS = 320          # comfortably inside the embedding window, small
OVERLAP_TOKENS = 60       # enough to keep a fact whole across a seam
MIN_TOKENS = 12           # below this a chunk is a heading, not content

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def split_sections(text):
    """[(heading_path, body)] — heading-aware, in document order."""
    lines = text.splitlines()
    stack, buf, out = [], [], []
    in_fence = False

    def flush():
        body = "\n".join(buf).strip()
        if body:
            out.append((" > ".join(stack), body))
        buf.clear()

    for line in lines:
        # A "#" inside a fenced block is a shell comment, not a heading.
        # Without this, `# free disk space` in a bash example became a section
        # heading and every following section inherited it — which is exactly
        # how a correctly-retrieved chunk ended up unanswerable.
        if FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else HEADING.match(line)
        if m:
            flush()
            depth = len(m.group(1))
            stack[:] = stack[:depth - 1]
            stack.append(m.group(2).strip())
        else:
            buf.append(line)
    flush()
    return out


def _paragraphs(body):
    """Blank-line paragraphs, except that a fenced code block is one unit —
    splitting a command in half serves nobody."""
    out, buf, in_fence = [], [], False
    for line in body.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not line.strip() and not in_fence:
            if buf:
                out.append("\n".join(buf).strip())
                buf = []
            continue
        buf.append(line)
    if buf:
        out.append("\n".join(buf).strip())
    return [p for p in out if p]


def _carry(paragraphs, overlap):
    """The tail of a chunk, repeated at the head of the next one.

    Whole paragraphs first. If even the last paragraph is bigger than the
    budget, carry its final words instead — otherwise long-paragraph documents
    get no overlap at all, and a fact sitting on a seam is lost from both
    sides. A code fence is never cut: half a command is worse than none.
    """
    tail, tail_n = [], 0
    for q in reversed(paragraphs):
        qn = len(tokenize(q))
        if tail_n + qn > overlap:
            break
        tail.insert(0, q)
        tail_n += qn
    if tail or not paragraphs:
        return list(tail), tail_n
    last = paragraphs[-1]
    if FENCE.match(last):
        return [], 0
    words = last.split()
    if len(words) <= overlap:
        return [last], len(words)
    return [" ".join(words[-overlap:])], overlap


def split_long(body, max_tokens=MAX_TOKENS, overlap=OVERLAP_TOKENS):
    """Split on blank lines, then pack paragraphs up to the budget."""
    paras = _paragraphs(body)
    chunks, cur, cur_n = [], [], 0
    for p in paras:
        n = len(tokenize(p))
        if cur and cur_n + n > max_tokens:
            chunks.append("\n\n".join(cur))
            cur, cur_n = _carry(cur, overlap)
        cur.append(p)
        cur_n += n
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def chunk_document(text):
    """[(heading_path, chunk_text)] ready to embed."""
    out = []
    for heading, body in split_sections(text):
        for piece in split_long(body):
            if len(tokenize(piece)) < MIN_TOKENS:
                continue
            # the heading path travels with the chunk, into the embedding
            out.append((heading, f"{heading}\n\n{piece}" if heading else piece))
    return out


def ingest_path(path, store=None, cache=None, on_chunk=None):
    """Ingest one file. Returns the number of chunks written."""
    path = Path(path)
    store = store or Store()
    cache = cache if cache is not None else Cache()
    source = path.name
    store.clear(source)                     # re-ingesting replaces, never doubles
    pieces = chunk_document(path.read_text())
    for i, (heading, text) in enumerate(pieces):
        vec = embed(text, task="RETRIEVAL_DOCUMENT", cache=cache)
        store.add(source, heading, i, text, vec)
        if on_chunk:
            on_chunk(source, i, len(pieces), heading)
    store.commit()
    return len(pieces)


def ingest_dir(directory, patterns=("*.md", "*.txt"), **kw):
    files = sorted(f for p in patterns for f in Path(directory).rglob(p))
    return {f.name: ingest_path(f, **kw) for f in files}
