#!/usr/bin/env python3
"""SQLite as the whole persistence layer: chunks, vectors, and query traces.

No vector index. At this corpus size exact cosine over every chunk costs
single-digit milliseconds, and an approximate index would add a dependency
and a recall cliff to save time that isn't being spent. That trade flips
somewhere around 10^5 chunks; this is nowhere near it.

Traces are stored, not printed. A RAG system that cannot tell you WHY it
answered the way it did is not debuggable, and "why did it say that" is the
only question anyone asks about one.
"""
import json
import math
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

from .embed import pack, unpack

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "index.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
  id       INTEGER PRIMARY KEY,
  source   TEXT NOT NULL,
  heading  TEXT,
  ord      INTEGER NOT NULL,
  text     TEXT NOT NULL,
  tokens   INTEGER NOT NULL,
  vec      BLOB
);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);
CREATE TABLE IF NOT EXISTS traces (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  question  TEXT NOT NULL,
  answered  INTEGER NOT NULL,
  top_score REAL,
  ms        INTEGER,
  provider  TEXT,
  detail    TEXT NOT NULL
);
"""

WORD = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return WORD.findall(text.lower())


class Store:
    def __init__(self, path=DB):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._bm25 = None

    # ---------------------------------------------------------------- write
    def clear(self, source=None):
        if source:
            self.db.execute("DELETE FROM chunks WHERE source=?", (source,))
        else:
            self.db.execute("DELETE FROM chunks")
        self.db.commit()
        self._bm25 = None

    def add(self, source, heading, ord_, text, vec):
        self.db.execute(
            "INSERT INTO chunks (source,heading,ord,text,tokens,vec) VALUES (?,?,?,?,?,?)",
            (source, heading, ord_, text, len(tokenize(text)), pack(vec)))
        self._bm25 = None

    def commit(self):
        self.db.commit()

    # ---------------------------------------------------------------- read
    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def sources(self):
        return [r[0] for r in self.db.execute(
            "SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source")]

    def all_chunks(self):
        return self.db.execute(
            "SELECT id, source, heading, ord, text, vec FROM chunks").fetchall()

    def get(self, chunk_id):
        return self.db.execute(
            "SELECT id, source, heading, ord, text FROM chunks WHERE id=?",
            (chunk_id,)).fetchone()

    # ------------------------------------------------------------- vectors
    @staticmethod
    def cosine(a, b):
        dot = na = nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0 or nb == 0:
            return 0.0
        return dot / math.sqrt(na * nb)

    def vector_search(self, qvec, k=8):
        out = []
        for r in self.all_chunks():
            if r["vec"] is None:
                continue
            out.append((self.cosine(qvec, unpack(r["vec"])), r["id"]))
        out.sort(reverse=True)
        return out[:k]

    # ---------------------------------------------------------------- bm25
    def _build_bm25(self):
        docs, df = {}, Counter()
        total = 0
        for r in self.all_chunks():
            tf = Counter(tokenize(r["text"]))
            docs[r["id"]] = tf
            total += sum(tf.values())
            for term in tf:
                df[term] += 1
        n = len(docs) or 1
        self._bm25 = {"docs": docs, "df": df, "n": n,
                      "avg": (total / n) if n else 1.0}

    def keyword_search(self, query, k=8, k1=1.5, b=0.75):
        """Plain BM25. Vectors miss exact identifiers — a function name, a flag,
        an error string — and those are exactly what people search docs for."""
        if self._bm25 is None:
            self._build_bm25()
        idx = self._bm25
        terms = tokenize(query)
        scores = {}
        for cid, tf in idx["docs"].items():
            length = sum(tf.values()) or 1
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (idx["n"] - idx["df"][t] + 0.5) / (idx["df"][t] + 0.5))
                s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * length / idx["avg"]))
            if s > 0:
                scores[cid] = s
        return sorted(((v, k_) for k_, v in scores.items()), reverse=True)[:k]

    # -------------------------------------------------------------- traces
    def trace(self, question, answered, top_score, ms, provider, detail):
        self.db.execute(
            "INSERT INTO traces (at,question,answered,top_score,ms,provider,detail)"
            " VALUES (?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), question, int(answered),
             top_score, ms, provider, json.dumps(detail)))
        self.db.commit()

    def traces(self, limit=20):
        return self.db.execute(
            "SELECT * FROM traces ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
