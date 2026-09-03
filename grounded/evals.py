#!/usr/bin/env python3
"""The evaluation suite.

A RAG system without one is a demo. Three things are measured, because they
fail independently and each hides the others:

  1. RETRIEVAL — is the right document in the top k? If it isn't, nothing
     downstream can be right, and a fluent wrong answer looks like success.
  2. ABSTENTION — does it refuse what the corpus doesn't contain? A system
     that always answers is an LLM with extra steps, and this is the metric
     that catches it.
  3. FAITHFULNESS — does every claim actually follow from the cited sources?
     Judged blind by a second model that is shown the answer and the sources
     but never the question's expected answer.

The abstention threshold is calibrated here rather than guessed: the suite
prints the similarity distribution for in-corpus and out-of-corpus questions
and flags the gap between them.
"""
import json

from .answer import ABSTAIN_BELOW, ask
from .embed import Cache
from .llm import LLMError, generate
from .retrieve import best_similarity
from .store import Store

# Answerable from the corpus. `expect` is the document that must appear in
# the retrieved set — the assertion is about retrieval, not about wording.
ANSWERABLE = [
    ("How do I regenerate the Instagram token when it expires?", "RUNBOOK.md"),
    ("What command starts the studio web server?", None),
    ("What is the recognition gate and why does it exist?", "housestyle-README.md"),
    ("How do I encode a new customer's house style?", "housestyle-README.md"),
    ("What Python and Node dependencies does the studio need?", "PROJECT_SETUP.md"),
    ("What is the plan if Claude access ends?", "OPERATIONS.md"),
    ("How do I free disk space from rendered intermediates?", "HOW_TO_RUN.md"),
    ("What are the quality gates that run before a reel renders?", None),
]

# Not in the corpus. Answering any of these is a failure, however plausible.
UNANSWERABLE = [
    "What is the capital of France?",
    "How do I configure Kubernetes autoscaling for the ingest workers?",
    "What is the best Python web framework for building microservices?",
    "How do I train a diffusion model from scratch on a single GPU?",
    "What were the company's Q3 revenue figures?",
]

JUDGE = """You are checking whether an answer is supported by its sources.

Sources:
{context}

Answer:
{answer}

Is every factual claim in the answer supported by the sources above?
Ignore style, brevity and formatting. Judge only support.

Return JSON: {{"supported": true or false, "unsupported_claim": "the first
claim that is not supported, or empty string"}}"""

JUDGE_SCHEMA = {"type": "object",
                "properties": {"supported": {"type": "boolean"},
                               "unsupported_claim": {"type": "string"}},
                "required": ["supported"]}


def judge_faithfulness(result):
    """LLM-as-judge over the CITED chunks only, not everything retrieved."""
    used = result["citations"] or list(range(1, len(result["hits"]) + 1))
    context = "\n\n".join(
        f"[{i}] {result['hits'][i - 1][0]['text']}"
        for i in used if 1 <= i <= len(result["hits"]))
    try:
        verdict, _ = generate(JUDGE.format(context=context, answer=result["answer"]),
                              schema=JUDGE_SCHEMA)
    except LLMError as e:
        return None, f"judge unavailable: {e}"
    return bool(verdict.get("supported")), verdict.get("unsupported_claim", "")


def run(verbose=True):
    store, cache = Store(), Cache()
    if store.count() == 0:
        print("nothing indexed — run: ./rag ingest")
        return False

    say = print if verbose else (lambda *a, **k: None)
    say(f"corpus: {store.count()} chunks from {len(store.sources())} documents\n")

    # ---------------------------------------------------- 1. retrieval recall
    say("RETRIEVAL — is the right document retrieved?")
    recall_hits = 0
    answered_results = []
    in_scores = []
    for question, expect in ANSWERABLE:
        r = ask(question, store=store, cache=cache, trace=False)
        in_scores.append(r["top_score"])
        sources = {h["source"] for h, _s, _w in r["hits"]}
        ok = (expect is None) or (expect in sources)
        recall_hits += ok
        answered_results.append((question, r, ok))
        say(f"  {'ok  ' if ok else 'MISS'} {question[:58]:<58} "
            f"{('→ ' + expect) if expect else '(any source)'}")
    recall = recall_hits / len(ANSWERABLE)
    say(f"  recall@5: {recall:.0%}  ({recall_hits}/{len(ANSWERABLE)})\n")

    # ------------------------------------------------------- 2. abstention
    say("ABSTENTION — does it refuse what it doesn't have?")
    refused = 0
    out_scores = []
    for question in UNANSWERABLE:
        r = ask(question, store=store, cache=cache, trace=False)
        out_scores.append(r["top_score"])
        ok = not r["answered"]
        refused += ok
        say(f"  {'ok  ' if ok else 'ANSWERED ANYWAY'} {question[:58]:<58} "
            f"top {r['top_score']:.3f}")
    answered_when_should = sum(1 for _q, r, _ok in answered_results if r["answered"])
    say(f"  refused {refused}/{len(UNANSWERABLE)} out-of-corpus · "
        f"answered {answered_when_should}/{len(ANSWERABLE)} in-corpus\n")

    # ------------------------------------------------- 3. threshold headroom
    if in_scores and out_scores:
        lo_in, hi_out = min(in_scores), max(out_scores)
        say("THRESHOLD — calibration, not guesswork")
        say(f"  in-corpus  min {lo_in:.3f}   max {max(in_scores):.3f}")
        say(f"  out-corpus min {min(out_scores):.3f}   max {hi_out:.3f}")
        say(f"  threshold  {ABSTAIN_BELOW:.2f}   headroom {lo_in - hi_out:+.3f}"
            + ("  (separable)" if lo_in > hi_out else "  (OVERLAP — no safe threshold)"))
        say("")

    # ------------------------------------------------------ 4. faithfulness
    say("FAITHFULNESS — is every claim supported by its citations?")
    checked = supported = 0
    uncited = 0
    for question, r, _ok in answered_results:
        if not r["answered"]:
            continue
        if not r["citations"]:
            uncited += 1
        verdict, detail = judge_faithfulness(r)
        if verdict is None:
            say(f"  skip {question[:58]:<58} {detail}")
            continue
        checked += 1
        supported += verdict
        say(f"  {'ok  ' if verdict else 'UNSUPPORTED'} {question[:58]:<58}"
            + (f"  ← {detail[:60]}" if not verdict and detail else ""))
    faith = (supported / checked) if checked else 0.0
    say(f"  supported: {faith:.0%}  ({supported}/{checked})"
        + (f"  ·  {uncited} answers cited nothing" if uncited else ""))

    passed = recall >= 0.75 and refused == len(UNANSWERABLE) and faith >= 0.8
    say(f"\n{'PASS' if passed else 'FAIL'}  "
        f"recall {recall:.0%} · abstention {refused}/{len(UNANSWERABLE)} · "
        f"faithfulness {faith:.0%}")
    return passed
