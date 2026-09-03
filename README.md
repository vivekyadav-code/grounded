# grounded

**Answers questions about your documents, with citations — or admits it can't.**

A retrieval-augmented generation service over private documentation. Hybrid
retrieval, measured abstention, and an evaluation suite that scores retrieval,
refusal and faithfulness independently.

Python 3, standard library only. No vector database, no framework, no
`pip install`.

```bash
./rag ingest                                    # index corpus/
./rag ask "How do I regenerate the token?"      # answer, with citations
./rag eval                                      # score the whole thing
./rag trace                                     # what was retrieved, and why
```

## What it does

```
document → heading-aware chunks → embeddings ─┐
                                              ├─ RRF fusion → context → cited answer
question → embedding ─────────► vector search ┤                    ↑
        └───────────────────► BM25 keyword ───┘            abstain if unsupported
```

## The parts that matter

**Hybrid retrieval.** Dense vectors and BM25 fail differently. Vectors handle
paraphrase — "how do I start it" finding "serving the site" — but are blind to
exact tokens. BM25 nails an identifier, a flag or an error string and is
helpless against paraphrase. Documentation questions are full of both.

They're combined with **reciprocal rank fusion** rather than a weighted sum,
because cosine similarity and BM25 scores are on incomparable scales;
normalising them means inventing a distribution. RRF uses only rank, so there
is nothing to tune per corpus.

**Chunking that respects the document.** Splitting on a character count throws
away the structure the author already decided on. This splits on headings
first, carries the heading path *into* the chunk text — `Operations > Serving >
run it with --no-open` retrieves where a bare `run it with --no-open` cannot —
and only then splits oversized sections on paragraph boundaries with overlap.

**Abstention.** If nothing in the corpus is similar enough, it says so rather
than writing a plausible paragraph from the model's own memory. There are two
independent layers: a similarity floor before generation, and an `INSUFFICIENT`
instruction the model can return after seeing the retrieved context. The second
catches what the first lets through — measured, not assumed.

**Citations, checked.** Every factual sentence carries `[n]` pointing at a
retrieved chunk, and citations outside the retrieved range are discarded as
hallucinations rather than displayed as sources.

**Traces, stored.** Every query records what was retrieved, each retriever's
score, the latency, the provider and the outcome. A RAG system that cannot tell
you *why* it answered is not debuggable, and that is the only question anyone
asks about one.

## No vector index, deliberately

Exact cosine over every chunk, in SQLite. At this corpus size that costs
single-digit milliseconds, and an approximate index would add a dependency and
a recall cliff to save time that isn't being spent. The trade flips somewhere
around 10⁵ chunks. This is nowhere near it — and knowing which side of that
line you're on is the point.

## Evaluation

```bash
./rag eval
```

Three things are scored, because they fail independently and each hides the
others:

| | What it catches |
|---|---|
| **Retrieval recall@k** | the right document never reached the model — a fluent wrong answer looks like success |
| **Abstention** | it answers everything, which makes it an LLM with extra steps |
| **Faithfulness** | the answer doesn't follow from its own citations, judged blind by a second model |

The suite also **calibrates the abstention threshold** instead of guessing it,
printing the similarity distribution for in-corpus and out-of-corpus questions
and the headroom between them.

Current run against the bundled corpus of 6 documents / 60 chunks:

```
recall@5      100%   (8/8)
abstention    5/5 refused out-of-corpus · 8/8 answered in-corpus
threshold     0.62   in-corpus min 0.665 · out-corpus max 0.620 · headroom +0.045
faithfulness  88-100%
```

**Faithfulness varies between runs.** The judge is a model, and on a borderline
answer — one that synthesises across two sources rather than restating one — it
does not always agree with itself. The pass threshold is set to tolerate one
disagreement rather than to hide it. Majority-vote judging would tighten this
and has not been built.

## Two bugs the tests found

Recorded because they are the interesting part.

**A shell comment became a section heading.** `# free disk space` inside a
fenced ```bash block was parsed as markdown, so every following section
inherited a nonsense heading path. The chunk was still retrieved correctly —
top vector score 0.660 — but with a corrupted heading it read as unanswerable
and the system abstained on a question it had the answer to. Fixing fence
tracking took in-corpus answering from 7/8 to 8/8.

**Overlap silently didn't happen.** Chunk overlap was whole-paragraph, so any
document whose paragraphs exceeded the overlap budget got no overlap at all —
a fact sitting on a seam was lost from both sides. The docstring claimed a
guarantee the code didn't provide. Now it carries trailing words when a whole
paragraph won't fit, and never cuts a code fence in half.

## Running it as a service

```bash
docker build --secret id=gemini_key,env=GEMINI_API_KEY -t grounded .
docker run -p 8080:8080 -e GEMINI_API_KEY=$GEMINI_API_KEY \
                        -e GROUNDED_API_KEY=your-token grounded
```

| route | |
|---|---|
| `POST /ask` | `{"question": "..."}` → answer, sources, whether each was cited |
| `GET /healthz` | liveness — deliberately does not touch the index |
| `GET /readyz` | readiness — 503 until the index has chunks |
| `GET /metrics` | Prometheus text format, no exporter dependency |

**The index is baked at build time.** Embedding the corpus on first boot would
pay an API bill and a cold-start delay on every replica, every deploy, forever.
Baking makes the image immutable and the first request as fast as the
thousandth. The key is passed as a BuildKit secret, mounted for that one layer
and never written into the image or its history.

**Liveness and readiness are different questions.** `/healthz` says the process
is alive and must not depend on the index, or a slow dependency gets the
container killed. `/readyz` says it can actually serve, and gates traffic
instead. Fly's health check points at `/readyz` for exactly this reason.

**Failure classes reach the caller intact.** An upstream rate limit returns
**503 with `Retry-After`**, not 502 — it's temporary and the client should back
off and retry. A genuine fault returns 502 with a request id and no stack
trace. `/metrics` counts them separately, because a spike in one means
something completely different from a spike in the other.

**Logs are the trace.** One JSON object per line to stdout with a correlation
id, the retrieval outcome, top score, provider and duration. In a container the
SQLite trace table would be ephemeral and lost on restart, so the service
disables it and lets the platform collect the logs — which is what a log
shipper can actually query.

Config is validated at boot and the process refuses to start if it's wrong,
rather than failing on whichever request first hits the broken path.

Deploying to Fly (`fly.toml` included):

```bash
fly launch --no-deploy
fly secrets set GEMINI_API_KEY=... GROUNDED_API_KEY=...
fly deploy
```

## Two more bugs, found only by running the container

Both are the kind that a CLI can never surface.

**SQLite connections belong to the thread that opened them.** One shared
connection is fine from a command line and throws `ProgrammingError` on the
first request a threaded server handles. It broke twice — once in the index
store, then again in the embedding cache, because fixing one didn't fix the
other. Both now use per-thread connections with WAL.

**A rate limit was being reported as a fatal error.** The service returned 502
when the upstream model was merely throttled, telling callers to give up on
something that would work again in a minute. It now raises a distinct
`RateLimited` and answers 503 with `Retry-After`. The first attempt at the rule
was still wrong: it required *every* provider to be throttled, so a second
provider simply being absent downgraded a retryable condition back into a fatal
one.

## Layout

```
grounded/
  embed.py      embeddings · content-addressed cache · 429 backoff
  store.py      SQLite: chunks, vectors, BM25, query traces
  ingest.py     heading- and fence-aware chunking with overlap
  retrieve.py   hybrid search + reciprocal rank fusion
  answer.py     context assembly · cited generation · abstention
  llm.py        provider chain with separated failure classes
  evals.py      recall · abstention · faithfulness · threshold calibration
  serve.py      HTTP API · auth · rate limiting · health · metrics
  cli.py
corpus/         the indexed documents
tests/          21 offline tests, no network
```

## Setup

Needs `GEMINI_API_KEY` in the environment or an `env.sh` beside the project.
Generation falls back to the `claude` CLI if Gemini is unavailable.

```bash
export GEMINI_API_KEY=...
./rag ingest && ./rag eval
python3 -m unittest discover -s tests
```
