# Beyond Obvious — Content Intelligence Studio

A local-first studio that writes, animates, voices, publishes and **learns from**
short-form psychology reels. Everything runs on this Mac; the only network calls
are script LLMs, publishing, insights and trend syncs.

```
idea ─▶ script (Claude→Gemini→Groq→Ollama) ─▶ quality gates ─▶ doodle render
     ─▶ Qwen-cloned Fenrir voice ─▶ FFmpeg ─▶ cover ─▶ Instagram + YouTube
     ─▶ insights ─▶ learning ─▶ better ideas ─┐
        ▲                                      │
        └──────────────────────────────────────┘
```

**Start it:** `cd scripts/anim/webui && ../../../.venv/bin/python -m uvicorn server:app --app-dir "$PWD" --port 8765`
→ http://localhost:8765

## Docs

| Read this | For |
|---|---|
| **HOW_TO_RUN.md** | daily use — make a reel, publish, schedule |
| **RUNBOOK.md** | operate alone: restarts, failures, tokens, config, backups |
| **OPERATIONS.md** | what's verified ✅ vs pending ❌ |
| **PROJECT_SETUP.md** | first-time install on a new machine + architecture map |

## The studio (sidebar pages)

- **Create** — topic → finished reel. Modes: Idea · Exact topic · Remix a winner.
- **Ideas** — ranked recommendations with evidence: proven patterns, winner
  mutations, global trends, exploration. Every idea shows why and its risks.
- **Library** — every reel, with per-platform publish state.
- **Analytics** — normalized performance (views ≠ value), what's working and
  declining, content fatigue, per-reel "why this worked", YouTube telemetry.
- **Global Trends** — public-ecosystem intelligence (Reddit / YouTube / imports)
  and the GLOBAL→YOU matrix: which outside patterns are worth testing here.
- **Experiments** — controlled variants and their measured outcomes.
- **Scheduler** — learned per-weekday posting times, auto posting (max 3/day),
  just-in-time content choice or hand-pinned slots.
- **System** — job history, failures with fixes, render logs, token expiry.

## What makes it more than a generator

- **Quality gates before render**: a substance critic (does it teach anything?),
  a first-watch clarity critic (would a distracted viewer follow it?), and an
  ending contract (the hook's tension must be paid off in plain words).
- **Voice as performance**: Qwen3-TTS clones the Fenrir identity locally
  (Apache-2.0); a Performance Director assigns delivery style, internal pauses,
  micro-pace and endings per line — with a governor that prevents theatrics.
- **Honest learning**: sample-size guards everywhere, confidence labels, no
  fabricated metrics; unknown stays unknown. Global data is for discovery, own
  audience data decides optimization.
- **Content DNA**: every reel records topic, mechanism, hook type, emotional arc,
  duration, writer model — so patterns can be learned, not guessed.

## Cost

$0 per reel: local rendering, local voice, free LLM tiers (Claude subscription
optional — Gemini/Groq/Ollama cover the fallback), free official APIs for
publishing and insights.

## Repo layout

```
scripts/anim/            the studio (Python)
  webui/                 FastAPI server + single-page UI
  dsl/                   scene engine, checker, autofixer, styles
  performance.py         voice performance director
  analytics.py           learning engine
  scheduler.py           posting-time learning + queue
  global_intel.py        global trend intelligence
  publish_ig.py / publish_yt.py / insights_pull.py / tokens.py
  tests/                 analytics · scheduler · performance · global ·
                         resilience · golden frames · palettes
content/                 all data: reel DNA, performance, queue, ideas, config
storage/, src/           legacy Spring Boot prototype (superseded, kept for reference)
```

Legacy note: the original Java/Veo pipeline in `src/` is retired — the Python
studio replaced it entirely.
