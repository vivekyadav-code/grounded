# Beyond Obvious — Pre-Independence Checklist (target: 2026-09-24)

Goal: the system runs, posts, learns, and is debuggable WITHOUT a maintainer.
Work through top to bottom. ✅ verified · 🔶 built-not-verified · ❌ not built

## 1. Core loop (verify weekly until the 24th)
- ✅ Generate reel end-to-end (Qwen default, Director v3, clarity + ending gates)
- ✅ Publish Instagram (one click, cover, caption, double-post guard)
- ✅ Publish YouTube (public since audit passed; first pre-audit upload stays locked)
- ✅ YouTube stats in analytics (readonly scope, snapshots, own section)
- ✅ Insights pull (IG + YT stats with history) — manual button
- ✅ Insights refreshed automatically (every 6h, EVERY connected account) — built
  into the scheduler loop rather than crontab, so it needs no separate install,
  respects `insights_refresh_hours` per account (0 disables), and shows each
  pull as a job so a failure is visible. The crontab line in RUNBOOK.md is now
  only a fallback for running it with the server down.
- 🔶 Auto posting full day: plan → JIT pick → publish at slot → history
  (all pieces tested separately; NEVER yet observed as one real unattended day)
  → TEST: turn auto ON with 2-3 approved reels, watch one full day hands-off

## 2. Survival without Claude access

**PLANNED (user has ChatGPT Plus): add a `codex` provider.** Codex CLI is
included with ChatGPT Plus/Pro and has headless `codex exec "prompt"` — the
same shape as our existing `claude -p` call, so it drops into the provider
chain with its own profile. Likely BETTER than the gemini fallback (GPT-5
class via existing subscription, no API credits). Steps when ready:
`npm install -g @openai/codex` → `codex login` → add `_codex` to
llm_providers PROFILES/PROVIDERS → verify one reel through the UI → make it
the default brain, gemini as backup. ~30 lines + a test run.
- ✅ Claude kill-switch (disabled_providers in learning_config + 3-strike
  rate-limit cooldown so a dead account costs seconds, not minutes)
- ✅ Verified Claude-less reels through the real API path (2026-08-15):
  · gemini "You apologize to furniture" 33.7s — passed gates, 1 ending warning
  · groq   "You check if they viewed it" 18.3s — SHIPPED WITH 5 WARNINGS,
    thin script (jargon, no concrete example, 18s vs 30-45s target)
  → VERDICT: gemini is the usable fallback; groq only as last resort.
    Set generation_defaults.brain to "gemini" the day Claude access ends.
- ✅ RUNBOOK.md: restarts, token regeneration (IG both flavors, YT), common
  failures (System page hints cover most), config knob map, backup/restore
- ✅ System page: job history, failure hints, build logs (self-service debug)

## 3. Token clocks (all die ~Oct 14 — AFTER access ends)
- ✅ IG publish token auto-refresh (daily tick; refreshed live, verified working)
- ✅ IG global-intel token auto-refresh (fb_exchange, verified)
- ✅ YT refresh token (self-renewing, production app — no expiry)
- ✅ Expiry warnings on System page (days-remaining + manual refresh button)

## 4. Data safety
- 🔶 content/*.json in git (committed ad hoc — add nightly auto-commit or
  document manual habit in RUNBOOK)
- ❌ global_intel.db not backed up (gitignored) — add to backup routine
- ❌ reels/ + AI Videos are unbacked (large; decide: external drive or accept loss)

## 5. Machine resilience
- ❌ launchd job: server starts at login, restarts on crash (needs user OK)
- ❌ Mac sleep policy: caffeinate or pmset for scheduled posting hours
- 🔶 missed-slot rescheduling (simulated ✅, never observed live)

## 6. Learning integrity (observe, no code)
- 🔶 predicted-vs-actual audit — meaningful at ~15 posted predicted reels
- 🔶 weekly learning report — becomes real with 2+ weeks of snapshots
- manual: note follower count every 2-3 days (API cannot provide it)

## Final week (Sept 17-24): FREEZE
No new features. Re-run every ✅ above, fix only breakage, commit final state,
re-read RUNBOOK start-to-finish pretending Claude doesn't exist.
