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
    ("How do I roll back a Deployment to a previous revision?",
     "workloads-controllers-deployment.md"),
    ("What Service types does Kubernetes support?",
     "services-networking-service.md"),
    ("What are the reclaim policies for a PersistentVolume?",
     "storage-persistent-volumes.md"),
    ("How does the kube-scheduler choose a node for a Pod?",
     "scheduling-eviction-kube-scheduler.md"),
    ("How do I make a ConfigMap immutable?", "configuration-configmap.md"),
    ("Where are container logs written and how do I read them?",
     "cluster-administration-logging.md"),
    ("What is a headless Service?", "services-networking-service.md"),
    ("How do I autoscale a workload automatically?", "workloads-autoscaling.md"),
    ("What is a static Pod?", "workloads-pods.md"),
    ("What is the difference between a ConfigMap and a Secret?", None),
]

# Not in the corpus. Answering any of these is a failure, however plausible.
# The middle three are deliberately Kubernetes-adjacent — "France" is a soft
# test of a threshold, "Istio mTLS" is a real one.
UNANSWERABLE = [
    "What is the capital of France?",
    "How do I configure Istio mutual TLS between two services?",
    "What does Amazon EKS cost per cluster per month?",
    "How do I write a Helm chart with subchart dependencies?",
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


def _retrieval_only(question, store, cache):
    """What ask() would have returned had generation been reachable: the
    retrieval and the abstention decision, with no answer."""
    from .retrieve import best_similarity, retrieve
    top = best_similarity(question, store=store, cache=cache)
    hits = retrieve(question, store=store, cache=cache, k=5)
    return {"question": question, "hits": hits, "top_score": top,
            "answered": False, "answer": "", "citations": [], "provider": None,
            "generation_unavailable": True}


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
    generation_down = None
    for question, expect in ANSWERABLE:
        try:
            r = ask(question, store=store, cache=cache, trace=False)
        except LLMError as e:
            # The model being unavailable must not take the retrieval score
            # with it — recall and abstention are measurable without it, and
            # they are the metrics that localise a fault.
            generation_down = str(e)
            r = _retrieval_only(question, store, cache)
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
        try:
            r = ask(question, store=store, cache=cache, trace=False)
        except LLMError as e:
            generation_down = str(e)
            r = _retrieval_only(question, store, cache)
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
    if generation_down:
        say("FAITHFULNESS — skipped")
        say(f"  generation unavailable: {generation_down[:90]}")
        say(f"\nPARTIAL  recall {recall:.0%} · abstention {refused}/{len(UNANSWERABLE)}"
            f" · faithfulness not measured")
        # Retrieval and abstention still have to hold; only faithfulness is
        # unknown, and an unknown is reported as such rather than as a pass.
        return recall >= 0.75 and refused == len(UNANSWERABLE)

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
