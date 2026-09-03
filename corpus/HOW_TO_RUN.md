# HOW TO RUN — step by step, no AI needed

Exact commands to run the studio yourself. Assumes setup is done once
(see PROJECT_SETUP.md). Everything happens in Terminal + your browser.

> **Current as of 2026-08-15.** The studio is now a single app at
> http://localhost:8765 with sidebar pages: Create · Ideas · Library ·
> Analytics · Global Trends · Experiments · Scheduler · System · Settings.
> Default voice is **Qwen3-TTS cloning Fenrir** (local, Apache-2.0), with the
> Performance Director shaping delivery. Publishing goes to **Instagram and
> YouTube Shorts**. For failures, tokens, config and recovery see **RUNBOOK.md**;
> for what's verified vs pending see **OPERATIONS.md**.

---

## 1. Start the studio

```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator/scripts/anim/webui
../../../.venv/bin/python -m uvicorn server:app --app-dir "$PWD" --port 8765
```

Leave this Terminal window open — it IS the server. You'll see log lines scroll as you use the studio.

Then open in your browser:
- **Studio (everything):** http://localhost:8765
- **Longform/YouTube composer:** http://localhost:8765/longform

*(Optional, for the Claude brain: make sure you've logged into Claude Code once
with `claude` in any terminal. For the Gemini fallback, `env.sh` must contain your key.
For the local fallback, run `ollama serve` in another terminal.)*

## 2. Make a Reel

Two ways:

**A. Let it find topics:** click **🎲 FIND TOPICS** (optionally type a theme first,
e.g. `sleep`). Click a topic card → confirm → wait ~4–6 minutes.

**B. Your exact idea:** type the full question/statement in the box —
e.g. `Why do I think of the perfect reply 3 hours later?` — and click
**🎯 THIS EXACT TOPIC**. The reel will be on exactly that, word for word.

Settings in the top bar (all optional): brain (auto = Claude→Gemini→local),
engine (Chatterbox = expressive default, Kokoro = fast), emotion slider,
voice, music mood, pace.

When it finishes you get: the video player, **caption + hashtags** (copy button),
**⬇ download**, **🔁 REGENERATE AUDIO** (change voice/engine/emotion/pace without
re-generating the script), and publish toggles (needs API credentials configured — currently not set up).

## 3. Make a YouTube long video

On http://localhost:8765/longform: type the topic, pick the number of facts
(1 fact ≈ 1 min sample, 5 facts ≈ 6 min), click **🎬 CREATE VIDEO**.

Expect ~35–45 minutes for a 5-fact video (most of it is Chatterbox voicing +
rendering). The result includes chapters, a thumbnail, and a ready-to-paste
title/description — the **copy** button grabs it all.

## 4. Where your videos are

| Type | Folder |
|---|---|
| Reels | `/Users/vivekyadav/Preparation/AI Videos/` |
| Long videos | `/Users/vivekyadav/Preparation/AI studio videos/` |

Next to every `.mp4` is a same-named `.txt` with the caption + hashtags
(or title/description/chapters). The LIBRARY section on both pages shows these
folders — every card has **📝 DETAILS** and **📋 COPY POST**, so you can grab
the post text any time, even weeks later.

## 5. When something fails

- The progress bar turns red with the reason. The system already retried once
  automatically (long videos resume from where they failed, not from the start).
- Click **🔁 TRY AGAIN** to retry manually — same topic, nothing lost.
- "all providers failed" = Claude hit its usage window AND Gemini hit its daily
  quota. Wait (Claude window resets every 5h; Gemini resets midnight Pacific)
  or start `ollama serve` for reels.
- Full error history with details: `scripts/anim/webui/failures.log`
- **Golden rule: never restart the server while a video is generating** —
  the job dies with it. Check both studio pages are idle first.

## 6. Stop / restart the server

- Stop: press `Ctrl+C` in the server Terminal (or close it).
- Restart: run the command from step 1 again.
- Restart is required after editing any `.py` file; NOT required for
  `.html`/`.js` changes (just hard-refresh the browser: Cmd+Shift+R).

## 7. Maintenance commands (occasional)

```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator/scripts/anim

# check the render engine still produces pixel-identical reference frames:
bash tests/golden_test.sh

# validate any scene files by hand:
../../.venv/bin/python dsl/check_scene.py reels/<some-slug>/scene*.json

# rebuild a video from its existing scenes (no LLM needed):
../../.venv/bin/python build_reel.py reels/<slug>/manifest.json reels/<slug>/out/final.mp4

# free disk space (rendered intermediates; safe — exports are elsewhere):
rm -rf reels/*/out
```

## 8. Save your work to GitHub

```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator
git add -A && git commit -m "session updates" && git push
```

Repo: https://github.com/vivekyadav-code/ai-video-generator (private).
Secrets (`env.sh`), models, and rendered videos are gitignored automatically.
