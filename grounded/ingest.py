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

ANCHOR = re.compile(r"\s*\{#[-\w]+\}\s*$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
TITLE_LINE = re.compile(r"^title:\s*(.+?)\s*$", re.M)
# {{< glossary_tooltip text="Pod" term_id="pod" >}} -> Pod
TOOLTIP = re.compile(r"\{\{[<%]\s*glossary_tooltip[^>%}]*?text=\"([^\"]*)\"[^>%}]*?[>%]\}\}")
SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.S)


def preprocess(text):
    """Strip the publishing system's scaffolding, keep the prose.

    Real documentation is not clean markdown. These docs carry YAML front
    matter and Hugo shortcodes; embedding `{{< note >}}` teaches the index
    nothing and dilutes the chunk. The front-matter `title` is worth keeping
    though — it is the document's real name, and it becomes the root heading
    so every chunk inherits it.
    """
    title = None
    m = FRONT_MATTER.match(text)
    if m:
        t = TITLE_LINE.search(m.group(1))
        if t:
            title = t.group(1).strip().strip('"\'')
        text = text[m.end():]
    text = COMMENT.sub("", text)         # editorial notes, not content
    text = TOOLTIP.sub(r"\1", text)      # keep the human-readable term
    text = SHORTCODE.sub("", text)       # drop the rest of the scaffolding
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title, text.strip()


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
            # "## Pod logs {#basic-logging}" — the anchor is for the website's
            # URLs and only dilutes the heading path it travels in
            stack.append(ANCHOR.sub("", m.group(2)).strip())
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


def chunk_document(text, title=None):
    """[(heading_path, chunk_text)] ready to embed."""
    out = []
    for heading, body in split_sections(text):
        if title:
            heading = f"{title} > {heading}" if heading else title
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
    title, body = preprocess(path.read_text())
    pieces = chunk_document(body, title=title)
    for i, (heading, text) in enumerate(pieces):
        vec = embed(text, task="RETRIEVAL_DOCUMENT", cache=cache)
        store.add(source, heading, i, text, vec)
        if on_chunk:
            on_chunk(source, i, len(pieces), heading)
    store.commit()
    return len(pieces)


SKIP = {"README.md", "LICENSE.md", "CONTRIBUTING.md"}


def ingest_dir(directory, patterns=("*.md", "*.txt"), skip=SKIP, store=None, **kw):
    """Index the corpus, not the notes about the corpus. A README describing
    the collection is not a document someone asks questions about, and it
    competes for retrieval with the ones that are.

    Also PRUNES: a source that is no longer in the corpus has its chunks
    deleted. Without this, removing a document leaves it answerable from a
    stale index — and adding a filename to `skip` silently kept whatever it
    had already contributed.
    """
    store = store or Store()
    files = sorted(f for p in patterns for f in Path(directory).rglob(p)
                   if f.name not in skip)
    counts = {f.name: ingest_path(f, store=store, **kw) for f in files}

    current = set(counts)
    for stale in [s for s in store.sources() if s not in current]:
        store.clear(stale)
    store.commit()
    return counts
