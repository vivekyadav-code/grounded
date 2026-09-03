# RUNBOOK — running Beyond Obvious without help

Everything needed to operate, debug and repair the studio alone.
Companion docs: PROJECT_SETUP.md (first-time install) · HOW_TO_RUN.md (daily use)
· OPERATIONS.md (what's verified vs pending).

---

## 0. The 30-second mental model

```
idea → script (Claude→Gemini→Groq→Ollama) → quality gates → doodle render
     → Qwen-cloned Fenrir voice → FFmpeg → cover → Instagram + YouTube
     → insights → learning → better ideas
```
Everything runs on this Mac. The only cloud calls are: script writing (LLM
APIs), publishing (Instagram/YouTube APIs), insights, and Global-Trend syncs.

---

## 1. Start / stop / restart the server

```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator/scripts/anim/webui
../../../.venv/bin/python -m uvicorn server:app --app-dir "$PWD" --port 8765
```
Studio: http://localhost:8765 · leave the terminal open (it IS the server).

Background instead (survives closing the window):
```bash
setsid ../../../.venv/bin/python -m uvicorn server:app --app-dir "$PWD" --port 8765 >> /tmp/bo-server.log 2>&1 < /dev/null &
```
`nohup ... &` is NOT enough on its own: it ignores SIGHUP but leaves the server
in the launching shell's process GROUP, so anything that kills that group takes
the server with it. That is how the server died on 2026-08-24 — it was started
inside a shell command that later timed out, and the timeout killed the group.
If `setsid` is unavailable (stock macOS), launch it from Python instead, which
calls setsid() in the child:
```bash
python3 -c "import subprocess,pathlib; subprocess.Popen(['.venv/bin/python','-m','uvicorn','server:app','--app-dir',str(pathlib.Path('scripts/anim/webui').resolve()),'--port','8765'], stdout=open('/tmp/bo-server.log','a'), stderr=subprocess.STDOUT, start_new_session=True)"
```

**ALWAYS check for running jobs before restarting** — a restart kills
in-flight generations and publishes:
```bash
curl -s localhost:8765/api/jobs | python3 -m json.tool | grep -B2 -A2 '"stage"'
```
Only restart when nothing is `scripting|rendering|voice|publishing`.
Then: `pkill -f "uvicorn server:app"` and start again.

---

## 2. When something fails

**First stop: the System page** (sidebar → System). It shows every job's
outcome (survives restarts), each failure with a plain-language hint, and
per-reel render logs. 90% of questions are answered there.

Raw sources if you need them:
- `scripts/anim/webui/failures.log` — tracebacks, newest at the bottom
- `scripts/anim/reels/<slug>/out/build.log` — voice/render detail for one reel
- server terminal / `/tmp/bo-server.log`

**Common failures and fixes**

| Symptom | Cause | Fix |
|---|---|---|
| "LLM quota busy" / 429 | Claude or Gemini limit | wait, or pick another brain in Advanced settings |
| "scene check FAILED" twice | the writer produced bad geometry | regenerate the same topic — usually passes |
| "Invalid OAuth" / token errors | Instagram token expired | §3 below |
| Publish fails at tunnel step | cloudflared didn't start | retry; `brew reinstall cloudflared` if persistent |
| Voice fails / weird speech | Qwen worker issue | switch engine to Chatterbox in Advanced settings and regenerate |
| UI shows stale numbers | (fixed Aug-15: no-store + cache-busting) | hard-refresh; if it persists, restart server |
| Reel spells words letter-by-letter | ALL-CAPS reaching Qwen | already guarded; report the exact line |

---

## 3. Tokens — the things that expire

| Token | File | Expires | Renew |
|---|---|---|---|
| Instagram publish (Beyond Obvious) | `scripts/anim/secrets/ig.json` | ~60 days (≈2026-10-14) | regenerate via Instagram app dashboard, replace `access_token` |
| Instagram publish (ideaInPages) | `scripts/anim/secrets/book_account/ig.json` | ~60 days (≈2026-10-15) | same dashboard, but the account must hold an **accepted Instagram Tester** role — see §3.1 |
| Instagram Business Discovery | `scripts/anim/secrets/ig_fb.json` | ~60 days | re-run the Graph API Explorer flow, paste new token; auto-exchanges to long-lived if `app_id`/`app_secret` present |
| YouTube | `scripts/anim/secrets/yt.json` | does not expire | if ever broken: `.venv/bin/python scripts/anim/oauth_yt.py`, open the printed URL, approve |
| Google/Groq/Gemini keys | `env.sh` | n/a | replace the line, no restart needed |

Symptoms of expiry: publishing fails with "Invalid OAuth"/"Session has
expired"; Global Trends Instagram source shows an error; insights pull prints
an auth error. **Nothing else breaks** — generation keeps working.

### 3.1 Adding a second Instagram account to the Meta app

How @ideainpages was connected (2026-08-16). Follow this for any further account.

The app runs in **Development mode**. In that mode Meta only issues a token for
an Instagram account that holds a role on the app, and the failure is reported as:

    Insufficient Developer Role: Insufficient developer role

which names neither the account nor the missing role, and looks identical to a
scope problem. It is not one. The fix:

1. App Dashboard → **App Roles → Roles → Instagram Testers** → add the Instagram
   **username**. Note this is a different list from **Roles → Testers**, which
   invites a *Facebook* user and has no effect on an Instagram-Login flow.
2. The invite is **pending, not granted** — the dashboard lists the account
   either way, so this step looks finished when it isn't. Log into Instagram as
   that account → Settings and privacy → **Apps and websites → Tester invites**
   → Accept.
3. Back in the dashboard: **Instagram → API setup with Instagram login** →
   Generate token for that account. This returns the token *and* the numeric
   Instagram user ID — both are needed; the ID is not recoverable from the token
   later without an API call.
4. Whoever clicks Generate must be **Admin or Developer** on the app. A
   Tester-role user gets the same error from the other direction.

Because the role is what authorises publishing, the account keeps working
without App Review — but only while it stays a tester on this app.

### 3.2 What is per-account, and what is deliberately shared

Every publishing credential and every piece of learned state belongs to one
account. `scripts/anim/accounts.py` resolves the paths; nothing reads a
hard-coded `content/…` path any more.

| Per account | Beyond Obvious (legacy paths) | ideaInPages |
|---|---|---|
| Instagram token | `secrets/ig.json` | `secrets/book_account/ig.json` |
| YouTube token | `secrets/yt.json` | `secrets/book_account/yt.json` (none yet) |
| Token refresh state | `secrets/token_state.json` | `secrets/book_account/token_state.json` |
| Reel metadata / performance / posted / lessons / ideas / queue / config | `content/*.json` | `content/accounts/book_account/*.json` |
| Exports | `~/Preparation/AI Videos` | `~/Preparation/Book Videos` |

**Deliberately shared, not an oversight:**
- `content/global_intel.db` and `secrets/ig_fb.json` — competitor/trend data.
  What is trending in the world is not one account's property; only the
  watchlist is per-account.
- `llm_providers.py` profiles (from `content/learning_config.json`) — the LLM
  chain is shared engine infrastructure, not content policy.

**Known gap:** the automatic scheduler tick runs for the DEFAULT account only.
Queues, slots and safety checks are all per-account, but nothing loops over
accounts yet, so a second account's queue is never ticked. Publishing a book
reel is a manual action today.

Useful commands:

    .venv/bin/python scripts/anim/tokens.py                       # all accounts
    .venv/bin/python scripts/anim/tokens.py refresh --account=book_account
    .venv/bin/python scripts/anim/insights_pull.py                # all accounts
    .venv/bin/python scripts/anim/oauth_yt.py --account=book_account

### 3.3 Connecting a YouTube channel to an account

How ideaInPages was connected (2026-08-16). ideaInPages lives on its **own
Google account**, so it got its own Cloud project rather than borrowing Beyond
Obvious's — separate quota, and access owned by the same account that owns the
channel.

In the Cloud console, signed in as that account:

1. New project. Enable **YouTube Data API v3** (upload) and **YouTube Analytics
   API**. Without the second, uploads still work and `insights_pull.py` simply
   logs a 403 and falls back to public view counts — it does not break.
2. OAuth consent screen, User type **External**, with three scopes:
   `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly`.
3. **Publishing status must be "In production".** An app left in *Testing*
   issues refresh tokens that expire after **7 days**, so the channel silently
   stops publishing a week later. Beyond Obvious's token survives indefinitely
   only because its app is published. Expect an "unverified app" warning at
   consent (Advanced → Go to app); that is normal for personal use.
4. Credentials → OAuth client ID. `oauth_yt.py` serves on **8899** and redirects
   to `http://localhost:8899` to catch the code.

   **If you get `Error 400: redirect_uri_mismatch`, this is the step.** Open the
   client and add an Authorized redirect URI of exactly:

       http://localhost:8899

   Three things that look identical but are different URIs to Google: `https`
   instead of `http`, a trailing slash, and `127.0.0.1` instead of `localhost`.
   Save, then retry — propagation is usually seconds but can take minutes, so a
   failure immediately after saving is not proof the URI is wrong.

   (Desktop-app clients are documented as accepting loopback redirects without
   registering one. That did NOT hold here on 2026-08-16 — the first client
   failed with `redirect_uri_mismatch` regardless, and a second client with the
   URI registered explicitly worked. Register it either way.)
5. Put `client_id` and `client_secret` into `secrets/<account>/yt.json`, then:

       .venv/bin/python scripts/anim/oauth_yt.py --account=book_account

   It prints the account and target file before opening, so a wrong-account
   authorization is visible before it is granted. The refresh token is written
   into that account's file only.
6. Verify what the token actually controls before trusting it:

       .venv/bin/python -c "import sys; sys.path.insert(0,'scripts/anim'); \
         import publish_yt; print(publish_yt.channel_info(account='book_account'))"

   `None` is not necessarily a failure — `channel_info` returns None when the
   granted scope is upload-only. A returned name must be the right channel.

The channel must exist on that Google account before step 5; a new Google
account has none until one is created at youtube.com.

Uploads default to **private**: `publish_yt` reads `youtube.privacy` from the
account's config, and an account with no `config.json` falls back to built-in
defaults, which do not set it.

---

## 4. Daily operation

- **Make a reel**: Create → type a topic → Generate (or pick a suggestion).
- **Publish**: on the finished screen or any Library card — Instagram and/or
  YouTube buttons; double-post protected.
- **Schedule**: Scheduler page. `Auto posting on/off`, content source
  (auto-generate vs your approved pool), platforms, and per-slot reel pinning.
  Max 3 automatic posts/day, hard-coded guard.
- **Measure**: metrics refresh THEMSELVES every 6 hours, for every connected
  account, from the scheduler loop — no cron needed (it was on the checklist as
  ❌ for weeks, which is why this used to need a manual click every time). Tune
  with `insights_refresh_hours` in an account's config; 0 disables it. Analytics
  → `refresh` still forces a pull now. Only if you want stats pulled while the
  server is DOWN, install this:
  ```
  17 */6 * * * cd <project> && .venv/bin/python scripts/anim/insights_pull.py >> /tmp/insights.log 2>&1
  ```
- **Learn**: Analytics shows what's working/declining, fatigue, and the
  leaderboard. Ideas page ranks what to make next with evidence.

---

## 5. Configuration — one file

`content/learning_config.json` — edited live, no restart needed:
- `generation_defaults` — engine (qwen/chatterbox/kokoro), voice, speed, brain
- `performance_weights` / `predicted_weights` — what "good" means
- `explore_ratio`, `predicted_threshold` — how adventurous the idea engine is
- `fatigue` — cooldown thresholds and penalties
- `scheduler` — timezone, slots/day, min gap, benchmark times, buffer target
- `youtube.privacy` — public|private for uploads
- `qwen.use_instruct` — leave false (open checkpoints ignore it with cloning)

---

## 6. If Claude access ends

The app does not need Claude Code — only the *script writer* prefers Claude.
- In Advanced settings set brain to **Gemini** or **Groq** (both free tiers),
  or set `generation_defaults.brain` in the config.
- If Claude is unavailable, the chain falls through automatically, but each
  call wastes time trying Claude first — set the brain explicitly to avoid it.
- Everything else (render, voice, publish, schedule, analytics, trends) is
  fully local/independent.

---

## 7. Backups (do this monthly)

Critical, small, git-tracked: `content/*.json` (metadata, performance, queue,
ideas, config). Commit and push:
```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator
git add -A && git commit -m "data snapshot" && git push
```
NOT in git: `content/global_intel.db` (trend observations),
`scripts/anim/secrets/*` (tokens — keep a private copy elsewhere),
`reels/` and `AI Videos/` (large media). Copy those to an external drive if
they matter to you.

---

## 8. Health checklist (run monthly, or when something feels off)

```bash
cd /Users/vivekyadav/Preparation/Documents/ai-video-generator
.venv/bin/python scripts/anim/tests/test_analytics.py     # learning math
.venv/bin/python scripts/anim/tests/test_scheduler.py     # scheduling logic
.venv/bin/python scripts/anim/tests/test_performance.py   # voice director
.venv/bin/python scripts/anim/tests/test_global.py        # trend intelligence
bash scripts/anim/tests/golden_test.sh                    # renderer (SSIM)
```
All should print `ALL PASS` / `PASS`. If one fails, the System page and the
test output name the broken area — and generation usually still works.
