#!/usr/bin/env python3
"""Answer a question from the corpus, with citations — or refuse.

Two rules decide whether this is trustworthy:

  1. It abstains. If the corpus has nothing similar enough, it says so instead
     of writing a plausible paragraph from the model's own memory. Abstention
     is measured in the eval suite, because a RAG system that never refuses is
     just an LLM with extra steps.
  2. Every claim carries a citation [n] pointing at the chunk it came from,
     and the citations are checked against what was actually retrieved before
     the answer is returned.
"""
import time

from .llm import generate
from .retrieve import best_similarity, retrieve
from .store import Store

# Below this cosine, the corpus does not contain the answer.
#
# Calibrated, not guessed: `./rag eval` measures the similarity distribution
# for questions known to be inside and outside the corpus and prints the gap.
# On the bundled corpus that gap is 0.628 (highest out-of-corpus) to 0.731
# (lowest in-corpus), so the threshold sits in the middle of it.
#
# It was 0.62 first, which is BELOW the out-of-corpus maximum — the floor let
# two Kubernetes-adjacent questions through and the model's INSUFFICIENT path
# had to catch them. Two layers is the design, but the cheap layer should do
# the work the measurement says it can.
ABSTAIN_BELOW = 0.68

PROMPT = """Answer the question using ONLY the numbered sources below.

Rules:
- Every sentence that states a fact must end with its source number, like [2].
- If the sources do not contain the answer, reply with exactly: INSUFFICIENT
- Do not use knowledge from outside the sources, even if you are confident.
- Be brief and concrete. No preamble.

Sources:
{context}

Question: {question}

Answer:"""


def build_context(hits):
    return "\n\n".join(
        f"[{i}] ({h['source']}"
        + (f" · {h['heading']}" if h["heading"] else "")
        + f")\n{h['text']}"
        for i, (h, _score, _why) in enumerate(hits, 1))


def cited_indexes(answer, n):
    """Which [n] the answer actually used, ignoring out-of-range inventions."""
    import re
    return sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer)
                   if 1 <= int(m) <= n})


def ask(question, store=None, cache=None, k=5, abstain_below=ABSTAIN_BELOW,
        trace=True):
    """Returns a dict: answered, answer, citations, hits, top_score, provider."""
    store = store or Store()
    started = time.time()

    # abstention is decided on raw similarity, not the fused rank score:
    # RRF scores are relative and say nothing about whether the corpus
    # actually contains an answer
    hits = retrieve(question, store=store, cache=cache, k=k)
    top_score = best_similarity(question, store=store, cache=cache)

    result = {"question": question, "hits": hits, "top_score": top_score,
              "answered": False, "answer": "", "citations": [], "provider": None}

    if not hits or top_score < abstain_below:
        result["answer"] = ("I don't have that in the indexed documents. "
                            f"(closest match scored {top_score:.2f}, "
                            f"below the {abstain_below:.2f} threshold)")
        _record(store, result, started, trace)
        return result

    prompt = PROMPT.format(context=build_context(hits), question=question)
    text, provider = generate(prompt)
    text = text.strip()
    result["provider"] = provider

    if text.upper().startswith("INSUFFICIENT"):
        result["answer"] = ("The retrieved sources don't answer that, "
                            "so I'd rather not guess.")
        _record(store, result, started, trace)
        return result

    result["answered"] = True
    result["answer"] = text
    result["citations"] = cited_indexes(text, len(hits))
    _record(store, result, started, trace)
    return result


def _record(store, result, started, trace):
    if not trace:
        return
    ms = int((time.time() - started) * 1000)
    store.trace(
        result["question"], result["answered"], result["top_score"], ms,
        result["provider"],
        {"citations": result["citations"],
         "retrieved": [{"id": h["id"], "source": h["source"],
                        "heading": h["heading"], "score": round(s, 4), "why": w}
                       for h, s, w in result["hits"]]})
