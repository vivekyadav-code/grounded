# PROJECT SETUP — Doodle Video Studio

> Machine-readable bootstrap guide. An AI agent (or a human) following this file
> top-to-bottom on a fresh macOS machine ends with a fully working studio.
> Every step has a VERIFY command — do not proceed past a failing verify.

## What this project is

A fully-local, $0-per-video studio that turns a topic into a doodle-animation
video: 9:16 Instagram Reels and 16:9 YouTube long-form. An LLM writes scenes as
JSON (never code), a checker/autofix gauntlet validates them, Chrome renders
deterministic frames, local TTS voices the script, FFmpeg assembles everything.

- Web UI: FastAPI server on **http://localhost:8765** (reels at `/`, YouTube at `/longform`)
- Pipeline core: `scripts/anim/` (everything below happens here)
- No paid APIs are required to render; LLM providers are used for script/scene writing only.

## 1. System requirements

| Requirement | Tested version | Install |
|---|---|---|
| macOS (Apple Silicon) | Darwin 25 / M4 16GB | — |
| Python | 3.14 | `brew install python@3.14` |
| Node.js | 26.x | `brew install node` |
| FFmpeg | 8.x | `brew install ffmpeg` |
| Google Chrome | any recent | must exist at `/Applications/Google Chrome.app` (hardcoded in `scripts/anim/animate.mjs`) |
| Ollama (optional, local LLM fallback) | any | `brew install ollama` |
| Claude Code CLI (optional, best script quality) | any | https://claude.com/claude-code |

VERIFY:
```bash
python3 --version && node --version && ffmpeg -version | head -1 \
  && test -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" && echo CHROME-OK
```

## 2. Python virtualenv

Created at the **project root** as `.venv`. All pipeline scripts are invoked via
`.venv/bin/python` (never the system python).

```bash
cd ai-video-generator
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn kokoro-onnx faster-whisper chatterbox-tts \
  edge-tts soundfile numpy onnxruntime
```

Key packages (tested versions): fastapi 0.141, uvicorn 0.52, kokoro-onnx 0.4.7,
faster-whisper 1.2.1, chatterbox-tts 0.1.7, edge-tts 7.2.8, soundfile 0.14, numpy 2.4.

**GOTCHA:** never `.resolve()` the venv python path in code — it is a symlink to
the system interpreter and resolving it escapes the venv (documented in
`webui/server.py`).

VERIFY:
```bash
.venv/bin/python -c "import fastapi, kokoro_onnx, faster_whisper, edge_tts; print('py-deps-OK')"
```

## 3. Node dependencies

```bash
cd scripts/anim
npm install        # installs puppeteer-core (drives the system Chrome, no bundled Chromium)
```

VERIFY: `node -e "require('puppeteer-core'); console.log('node-deps-OK')"` (run in `scripts/anim`).

## 4. Model files (all local, all free)

| Model | Purpose | Location | How to get |
|---|---|---|---|
| `kokoro-v1.0.onnx` (~325MB) | Kokoro TTS (fast voice) | `scripts/anim/kokoro-v1.0.onnx` | https://github.com/thewh1teagle/kokoro-onnx/releases |
| `voices-v1.0.bin` (~28MB) | Kokoro voice pack (incl. `am_fenrir`) | `scripts/anim/voices-v1.0.bin` | same release page |
| Chatterbox TTS (~2GB) | Expressive voice (default engine) | HuggingFace cache | auto-downloads on first use (`resemble-ai/chatterbox`) |
| faster-whisper `base.en` | Caption word-timing alignment | HF cache | auto-downloads on first use |
| Ollama `llama3.1:8b` + `llama3.2:3b` | Local LLM fallback (tier 3) | ollama | `ollama pull llama3.1:8b && ollama pull llama3.2:3b` |

```bash
cd scripts/anim
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

VERIFY: `ls -la scripts/anim/kokoro-v1.0.onnx scripts/anim/voices-v1.0.bin`

## 5. LLM providers (script/scene brains)

Provider chain, in order (`scripts/anim/llm_providers.py`): **claude → gemini → ollama**.
The system works with ANY ONE of them available. Long-form uses claude/gemini only
(the local 8B parrots templates across many scenes).

1. **Claude (best quality, subscription — no API key needed)**
   - Install Claude Code CLI, then log in once interactively: `claude` (uses your Claude subscription).
   - Headless calls use `claude -p --output-format json --json-schema --max-turns 4`.
   - Models: haiku for light tasks, sonnet for scene writing (override: `CLAUDE_GEN_MODEL`).
2. **Gemini (free tier)**
   - Get a key at https://aistudio.google.com/apikey
   - Put it in `env.sh` at the project root (this file is gitignored — create it):
     ```bash
     export GEMINI_API_KEY=YOUR_KEY_HERE
     ```
   - The server also reads the key directly from `env.sh` if the env var is unset.
3. **Ollama (fully local fallback)**
   - `ollama serve` must be running; models from step 4 pulled.
   - Overrides: `OLLAMA_MODEL` (default llama3.1:8b), `OLLAMA_SMALL_MODEL` (default llama3.2:3b).

VERIFY (any one passing is enough to generate):
```bash
echo 'Say OK' | claude -p --max-turns 1 2>/dev/null | head -c 80        # claude
curl -s localhost:11434/api/tags | head -c 80                            # ollama
```

## 6. Output folders (hardcoded in `webui/server.py`)

| What | Where |
|---|---|
| Finished reels (+ caption/hashtag `.txt`) | `/Users/vivekyadav/Preparation/AI Videos` |
| Long videos (+ thumb + title/desc/chapters `.txt`) | `/Users/vivekyadav/Preparation/AI studio videos` |

Both are auto-created on server start. **On a new machine, edit
`REEL_EXPORT_DIR` / `LONG_EXPORT_DIR` near the top of `webui/server.py`.**
The studio library (`/api/library`) is a live scan of these two folders.

## 7. Start the server

```bash
cd ai-video-generator/scripts/anim/webui
../../../.venv/bin/python -m uvicorn server:app --app-dir "$PWD" --port 8765
```

VERIFY: `curl -s -o /dev/null -w "%{http_code}" localhost:8765/` → `200`,
then open http://localhost:8765 (reels) and http://localhost:8765/longform (YouTube).

## 8. Post-setup sanity tests

```bash
cd scripts/anim
# 1. golden-frame regression (renders reference scenes, compares SSIM >= 0.999)
bash tests/golden_test.sh
# 2. checker on a known-good scene set
../../.venv/bin/python dsl/check_scene.py reels/yt-sample-chemical-high/scene*.json
# 3. full local build with NO LLM (voice + render + music):
../../.venv/bin/python build_reel.py reels/yt-sample-chemical-high/manifest.json /tmp/setup_test.mp4
```

All three passing = the whole render path works. Generating from the UI
additionally needs one LLM provider from step 5.

## Architecture map (for an AI agent orienting itself)

```
scripts/anim/
  webui/server.py        FastAPI: topics, generate (reel), longform, rerender, library, publish
  webui/static/          index.html (reels studio) + longform.html (YouTube studio)
  llm_providers.py       claude→gemini→ollama chain, lock-serialized, RateLimited handling
  build_reel.py          manifest → per-scene TTS (kokoro/chatterbox) → whisper align →
                         parallel Chrome frame render → FFmpeg assemble → music duck
  animate.mjs            Puppeteer: renders one scene JSON to mp4 (deterministic seek(t))
  dsl/engine.js          scene DSL runtime (actors/props/camera/beats/captions)
  dsl/characters.js      stick-figure rig: 25 poses, 11 emotions
  dsl/props.js           69 declarative props
  dsl/environments.js    14 backdrop presets
  dsl/check_scene.py     R1-R9 correctness rules (exits 1 on FAIL) — THE quality gate
  dsl/autofix_scene.py   repairs scenes to pass the checker (--salvage deletes hopeless props)
  music_gen.py           local numpy synth music bed (no assets needed)
  publish.py             YouTube/Instagram upload (optional; needs API credentials in secrets/)
  tests/golden_test.sh   pixel-regression tests (--bless to re-record after intended changes)
  reels/<slug>/          per-video working dirs: sceneN.json + manifest.json + out/
content/ideas.json       topic ledger (produced/proposed, enables part 2/3 continuity)
webui/failures.log       every job failure with traceback (status text gets overwritten; this doesn't)
```

Key invariants an agent must preserve:
- The LLM writes **scene JSON only** — never JS/shell/FFmpeg args (security boundary).
- Every scene must pass `check_scene.py` before render; fix via `autofix_scene.py`, not by hand-waving.
- `PROP_EXT` (prop sizes) lives ONLY in `check_scene.py`; autofix imports it (generated props extend it at import).
- Templates use `@@TOKEN@@` replacement, never `%`-formatting (breaks on literal `%`).
- Server code changes require a server restart; static HTML changes do not.
- Never restart the server while a job is running (jobs are in-process threads; checkpoints in `reels/<slug>/checkpoint.json` let longform resume). Check `/api/jobs` first.

Lessons from shipped bugs (each of these happened — do not repeat them):
- **Files are the truth after a subprocess touches them.** `autofix_scene.py` repairs
  scene files ON DISK; the parent's in-memory dicts don't see it. Re-serializing from
  those dicts silently destroys the repairs (this killed two longform runs). Always
  read-modify-write the file.
- **A `str.replace()` edit that finds no anchor is a silent no-op.** Assert the anchor
  exists, or verify the change landed afterwards (grep the file / curl the served page).
- **Smoke-test the exact production entry point,** in the same interpreter/sys.path the
  server uses — a CLI test of a neighboring function missed an ImportError that only
  triggered in-server (`dsl/` not on the server's path).
- **Claude CLI headless:** `--max-turns` must be >=4 with `--json-schema` (structured
  output is a tool round-trip, and a stray denied WebSearch burns another turn); accept
  a valid `structured_output` even if the envelope says `is_error`; a hard usage-cap
  returns PLAIN TEXT, not JSON — treat as rate-limited, never blacklist.
- **Two jobs on one topic share `reels/<slug>/` and wipe each other** — the dedupe
  guard in the POST endpoints exists for this; keep it when adding new job types.
- **No silent overrides in the UI.** Any implicit behavior (e.g. a voice-clone file
  that hijacks the voice) must be a visible, honestly-labeled option instead.

## Architecture additions (2026-08-15)

Voice & performance
- `scripts/anim/performance.py` — Performance Director: delivery styles,
  segments, internal pauses, micro-prosody (pace/energy/endings), the
  anti-theatrical governor. Engine-agnostic.
- `scripts/anim/qwen_synth.py` + `.venv-qwen/` — Qwen3-TTS worker (isolated
  deps). Clones Fenrir from `voice_ref/fenrir_clone_ref.wav` + `.txt`
  (the transcript must match the audio exactly).
- Engines: `qwen` (default) · `chatterbox` · `kokoro`, chosen per manifest.

Intelligence
- `scripts/anim/analytics.py` — normalized performance scoring, patterns with
  sample-size honesty, fatigue engine, weekly learning report, why-panels.
- `scripts/anim/reel_meta.py` — per-reel creation DNA (`content/reel_meta.json`).
- `scripts/anim/global_intel.py` + `content/global_intel.db` — Global Trend
  Intelligence (Reddit/YouTube/import adapters, trend engine, GLOBAL→YOU).
- `scripts/anim/scheduler.py` + `content/schedule_queue.json` — learned
  posting times, JIT slot decisions, persistent queue.

Publishing
- `publish_ig.py` (Instagram, cover picker) · `publish_yt.py` (YouTube Shorts)
  · `oauth_yt.py` (one-time YouTube auth) · `insights_pull.py` (IG + YT stats).

Tests: `tests/test_analytics.py`, `test_scheduler.py`, `test_performance.py`,
`test_global.py`, `golden_test.sh`, `palette_contrast.py`.
