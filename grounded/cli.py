#!/usr/bin/env python3
"""grounded — answers questions about your documents, with citations.

  ./rag ingest [dir]        index the corpus
  ./rag ask "question"      answer it, or say it can't
  ./rag search "terms"      show what retrieval returns, and why
  ./rag eval                run the evaluation suite
  ./rag trace [n]           recent queries: what was retrieved, and the outcome
  ./rag status              corpus and index summary
"""
import argparse
import json
import sys
from pathlib import Path

from .embed import Cache
from .store import ROOT, Store


def cmd_ingest(a):
    from .ingest import ingest_dir
    store, cache = Store(), Cache()
    directory = a.directory or ROOT / "corpus"
    print(f"indexing {directory}")

    def progress(source, i, total, heading):
        print(f"\r  {source}  {i + 1}/{total}  {(heading or '')[:48]:<48}", end="")

    counts = ingest_dir(directory, store=store, cache=cache, on_chunk=progress)
    print(f"\r{'':<70}\r", end="")
    for name, n in counts.items():
        print(f"  {name:28} {n:>4} chunks")
    print(f"\n{sum(counts.values())} chunks from {len(counts)} documents"
          f"  ·  embeddings: {cache.misses} new, {cache.hits} cached")


def cmd_ask(a):
    from .answer import ask
    store, cache = Store(), Cache()
    if store.count() == 0:
        sys.exit("nothing indexed yet — run: ./rag ingest")
    r = ask(a.question, store=store, cache=cache, k=a.k)
    print()
    print(r["answer"])
    print()
    if r["answered"]:
        used = set(r["citations"])
        for i, (h, _s, _w) in enumerate(r["hits"], 1):
            mark = "*" if i in used else " "
            head = f" · {h['heading']}" if h["heading"] else ""
            print(f" {mark}[{i}] {h['source']}{head}")
        if not used:
            print("\n  ! the answer cited nothing — treat it with suspicion")
    print(f"\n  top similarity {r['top_score']:.3f}"
          + (f"  ·  via {r['provider']}" if r["provider"] else "  ·  abstained"))


def cmd_search(a):
    from .retrieve import retrieve
    store, cache = Store(), Cache()
    if store.count() == 0:
        sys.exit("nothing indexed yet — run: ./rag ingest")
    for i, (h, score, why) in enumerate(retrieve(a.query, store=store,
                                                 cache=cache, k=a.k), 1):
        head = f" · {h['heading']}" if h["heading"] else ""
        print(f"[{i}] {h['source']}{head}")
        print(f"    fused {score:.4f}   ({why})")
        print(f"    {h['text'][:150].replace(chr(10), ' ')}…\n")


def cmd_eval(a):
    from .evals import run
    sys.exit(0 if run(verbose=not a.quiet) else 1)


def cmd_trace(a):
    store = Store()
    rows = store.traces(limit=a.n)
    if not rows:
        print("no queries recorded yet")
        return
    for r in reversed(rows):
        detail = json.loads(r["detail"])
        state = "answered" if r["answered"] else "ABSTAINED"
        print(f"{r['at']}  {state:9}  top {r['top_score']:.3f}  {r['ms']}ms"
              f"  {r['provider'] or '-'}")
        print(f"  Q: {r['question']}")
        for d in detail.get("retrieved", [])[:3]:
            print(f"     {d['source']} · {(d['heading'] or '')[:40]}  ({d['why']})")
        print()


def cmd_serve(a):
    from .serve import Config, serve
    cfg = Config()
    if a.port:
        cfg.port = a.port
    serve(cfg)


def cmd_status(a):
    store = Store()
    print(f"index      {store.path}")
    print(f"chunks     {store.count()}")
    for row in store.db.execute(
            "SELECT source, COUNT(*) n, SUM(tokens) t FROM chunks"
            " GROUP BY source ORDER BY source"):
        print(f"  {row[0]:28} {row[1]:>4} chunks  {row[2]:>6} tokens")
    n = store.db.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    ab = store.db.execute("SELECT COUNT(*) FROM traces WHERE answered=0").fetchone()[0]
    print(f"queries    {n} ({ab} abstained)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rag", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest"); p.add_argument("directory", nargs="?")
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("ask"); p.add_argument("question")
    p.add_argument("-k", type=int, default=5); p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("search"); p.add_argument("query")
    p.add_argument("-k", type=int, default=5); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("eval"); p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("trace"); p.add_argument("n", nargs="?", type=int, default=5)
    p.set_defaults(fn=cmd_trace)
    p = sub.add_parser("serve", help="run the HTTP service")
    p.add_argument("--port", type=int); p.set_defaults(fn=cmd_serve)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    a = ap.parse_args(argv)
    return a.fn(a)
