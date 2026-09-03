#!/usr/bin/env python3
"""Hybrid retrieval: dense vectors and BM25, fused by reciprocal rank.

Neither method is sufficient alone and they fail differently. Vectors handle
paraphrase ("how do I start it" -> "serving the site") but are blind to exact
tokens. BM25 nails an identifier — a flag, a filename, an error string — and
is helpless against paraphrase. Docs questions are full of both.

Fusion is RRF rather than a weighted score sum, because cosine similarity and
BM25 are on incomparable scales; normalising them means inventing a
distribution. RRF only uses rank, so there is nothing to tune per corpus.
"""
from .embed import embed_query
from .store import Store

RRF_K = 60          # standard damping; the exact value barely matters
POOL = 20           # candidates drawn from each retriever before fusion


def reciprocal_rank_fusion(ranked_lists, k=RRF_K):
    scores = {}
    for lst in ranked_lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def retrieve(question, store=None, cache=None, k=5, pool=POOL):
    """Return [(chunk_row, fused_score, why)] best first."""
    store = store or Store()
    qvec = embed_query(question, cache=cache)

    dense = store.vector_search(qvec, k=pool)
    sparse = store.keyword_search(question, k=pool)

    dense_rank = [cid for _, cid in dense]
    sparse_rank = [cid for _, cid in sparse]
    fused = reciprocal_rank_fusion([dense_rank, sparse_rank])

    dense_scores = {cid: s for s, cid in dense}
    sparse_scores = {cid: s for s, cid in sparse}

    out = []
    for cid, score in fused[:k]:
        row = store.get(cid)
        if row is None:
            continue
        why = []
        if cid in dense_scores:
            why.append(f"vector {dense_scores[cid]:.3f}")
        if cid in sparse_scores:
            why.append(f"keyword {sparse_scores[cid]:.2f}")
        out.append((row, score, " · ".join(why)))
    return out


def best_similarity(question, store=None, cache=None):
    """Top raw cosine — the abstention decision is made on this, not on the
    fused score, because RRF scores are relative and say nothing about whether
    the corpus actually contains an answer."""
    store = store or Store()
    qvec = embed_query(question, cache=cache)
    top = store.vector_search(qvec, k=1)
    return top[0][0] if top else 0.0
