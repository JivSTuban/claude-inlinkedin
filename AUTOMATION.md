# LinkedIn Growth Automation — Architecture & Learnings

Daily LinkedIn growth automation (connections, follows, post engagement) running on a local Mac via pm2 + Claude Code CLI.

## Mac Mini + Codex (the live setup, since 2026-09-30)

Outreach now runs on the always-on Mac Mini (`admin@100.98.219.58`, Tailscale) with **Codex CLI**, not Claude Code: Codex is authed from `~/.codex/auth.json` there, so headless runs work and cost nothing extra. The pm2 + `/linkedin-grow` path below is the older MacBook setup and is not scheduled anywhere.

```
crontab  17 9,11,14 * * 1-5  runner.sh outreach   (daily; 11:17/14:17 are retries)
         47 8-20/3 * * *     runner.sh inbox      (every 3h, every day)
  └── scripts/linkedin-codex-runner.sh      (copy lives at ~/agent-work/jobi on the Mini)
        ├── skips if another run holds /tmp/linkedin-codex-run.lock or Chrome has the
        │   profile open; outreach also skips once today succeeded (~/.linkedin_codex_last_run)
        ├── INBOX PASS (inbox mode, and first step of outreach mode). Codex never browses it:
        │     ├── node scripts/linkedin-inbox.js read  -> .inbox/digest.json (threads whose
        │     │     last message is from them; ~7KB). Login wall -> exit 3, Codex not started;
        │     │     nothing awaiting a reply -> Codex not started
        │     ├── codex exec --profile linkedin-inbox  (codex/linkedin-inbox.config.toml, NO
        │     │     browser MCP; skill section "Inbox Digest Mode") -> .inbox/actions.json
        │     └── node scripts/linkedin-inbox.js send  types each reply, verifies it on the
        │           page, rejects dash/phone text, logs to inbox-sent.jsonl
        ├── OUTREACH (outreach mode only): codex exec --profile linkedin -C ~/Work/job-email-bot/marketing/outreach
        │     ├── skill:   ~/.codex/skills/linkedin (Scheduled Automation Mode, inbox pass skipped)
        │     ├── profile: ~/.codex/linkedin.config.toml  (approval never, sandbox writes
        │     │            only the outreach folder, folder pre-trusted)
        │     └── MCP:     linkedin-browser = @playwright/mcp@0.0.83, real Chrome,
        │                  --user-data-dir ~/.linkedin-codex-profile
        ├── run counts only if the summary ends RUN_STATUS=ok (exit 3 otherwise)
        └── scripts/linkedin-notify.py: DMs Jiv on Discord for each new needs-jiv.jsonl
            line, plus at most one failure/session-expired alert per day
```

| What | Where (on the Mini) |
|------|---------------------|
| Tracker + run reports | `~/Work/job-email-bot/marketing/outreach/` |
| Inbox replies sent (one line per send: sent / unverified / rejected / failed) | `inbox-sent.jsonl` there; this run's digest + actions in `.inbox/` |
| Escalations (DM'd once each) | `needs-jiv.jsonl` there; posted count in `~/.linkedin_needs_jiv_posted` |
| Runner logs + per-run summary | `~/Library/Logs/linkedin-codex/<date>.log`, `<date>-<mode>-<HHMM>-summary.md` |
| LinkedIn session | `~/.linkedin-codex-profile` (Chrome, Playwright mock keychain) |

**Goal of every message: rapport**, a relationship that turns into opportunities later (the skill's "North Star"). Wording is up to Codex; **em/en-dashes never** (skill hard rule, checked before every send and audited by the runner, which DMs Jiv if one appears in the tracker, `needs-jiv.jsonl` or the run summary).

**Inbox auto-reply:** every run answers messages from the last 30 days, friendly and casual chat included, as long as any fact about Jiv is in the allowed context and the reply commits him to nothing. Money, scheduling, offers, resume/document requests, sensitive topics, anything it can't make sense of, and work messages older than 30 days are **escalated**: a suggested reply is DM'd to Jiv on Discord (the Mini's "Crowdsnare Bot 2" DM channel) and nothing is sent. Rules live in the skill's `Inbox Auto-Reply` section. Test changes with `linkedin-codex-runner.sh inbox --dry-run` (writes `needs-jiv.dryrun.jsonl`, sends nothing).

**Scheduled runs only send exact, already-drafted tracker rows.** New cold notes are drafted into the tracker and reported, never sent unattended (the skill's Scheduled Automation Mode). Approve or edit them, then an interactive `$linkedin` run or the next scheduled run sends them.

**Conversation end gate.** The bot used to answer every message from a casual chat, and since each reply ended with a question the chat never ended (Clark Kent Ibale got 4 replies in 9 hours on 2026-10-07). Two layers now stop it. In code, `scripts/linkedin-inbox-gate.js` runs inside `linkedin-inbox.js read`: a thread whose last message asks nothing (thanks, ok, emoji, goodbye) is dropped before Codex sees it (`digest.conversation_ended`), and every thread carries `bot_replies_7d` and `bot_cap_reached` (3 sent replies in 7 days, counted from `inbox-sent.jsonl`). In the skill, `Conversation End Gate` (versioned at `codex/skills/linkedin/SKILL.md`, deploy by copying to the Mini's `~/.codex/skills/linkedin/`) tells Codex never to auto-reply to a capped thread, to close small talk after two replies with a line that has no question, to skip pitches and monologues, and that `[]` is a valid answer. A body line is only read as a message header when it names Jiv or the other person, and an unrecognised thread layout fails open to Codex.

**Target: foreign founders (changed 2026-10-22; replaces the hirer fit gate of 2026-10-07).** Free accounts get a handful of custom notes a month, so each one goes to a founder, co-founder, CEO or CTO of a 2 to 50 person software or AI product company **outside the Philippines** who also shows a hire signal. Why: all 15 invitations that carried a `hirer_role` went to recruiters, 13 of them based in the Philippines, and 51 of the 55 tracked profiles with a location are Philippine (Metro Manila, Cebu), Jiv's own market. One secondary slot per run may go to a non-Philippine recruiter or engineering lead; Philippine-based people get no new invitation (inbound ones are still answered). The connection note stays rapport only; the first message to an accepted FOUNDER may say in one sentence that Jiv is looking for remote contract or full-time work and ask whether they are hiring. Search seeds are founder-first with a country word to steer the market (list in the skill's `Autonomous Outreach Gate`). The rule lives in the skill, which is a prompt, so it is also checked in code: the tracker row must carry `prospect_type` (founder | hiring_lead | recruiter), `location`, `hirer_role`, `hire_signal`, and after every outreach run `scripts/linkedin-outreach-audit.py` reads the tracker and Discord/phone-alerts (once a day) on a new connection request to a Philippines-based prospect, a missing field, or a second non-founder in one run. Tests: `tests/battle/test_linkedin_outreach_audit.py` (12) and `run_runner_tests.sh` section 5b3. Deploy: copy the skill to the Mini's `~/.codex/skills/linkedin/`, the runner and the audit to `~/agent-work/jobi/scripts/`. If free custom notes run out the run records `custom_notes_exhausted` and sends nothing; whether to pay for Premium to keep going is Jiv's call.

**Failure handling.** The reader (`linkedin-inbox.js read`) clicks the thread link, never the avatar (an avatar click navigated to a profile and failed the whole run on 2026-10-02 and 2026-10-05), and a row that will not open is logged and skipped (`read_errors` in the digest) instead of sinking the run. `run_codex` retries a Codex exit 1 up to 3 times with 2 and 4 minute backoff (`Selected model is at capacity` lost the 2026-10-05 14:47 run); the 45-min cap, usage limit and unresponsive Codex are never retried.

**Log in / re-log in** (first time, or when a run reports `linkedin_session_expired`): Screen Share to `vnc://100.98.219.58`, then on the Mini:

```bash
cd ~/agent-work/jobi && PLAYWRIGHT_PROFILE=~/.linkedin-codex-profile LOGIN_TIMEOUT_MIN=20 npm run login
```

Sign in with email/password in the Chrome window that opens; it closes itself once the feed loads.

**Battle tests** (`tests/battle/`, run on the Mini):
- `test_inbox_gate.js`: 30 deterministic checks of the end gate (closers, open questions, links, ok/yes after a question, the 3-reply cap), fixtures are the real 2026-10-07 Clark thread. `node tests/battle/test_inbox_gate.js`.
- `run_runner_tests.sh`: 36 deterministic checks, no quota spent (fake-codex shims): overlap lock, Chrome already open, daily stamp, 45-min cap kills Chrome + frees the lock, alert once per day, dash audit, usage-limit pause, capacity retry (and never retrying a usage limit), login wall and empty inbox never start Codex, notifier dedupe, Discord failure keeps the queue, real files untouched.
- `run_battle.sh 1|2|login`: the real runner, skill, Codex and Chrome profile against `mock_linkedin.py`, a fake LinkedIn inbox of 23 adversarial threads (`cases.json`: rate/scheduling/offer/resume asks, prompt injection, phishing, dash bait, confidential questions, Taglish small talk, sponsored/system noise, stale messages, a login wall). `assert_battle.py` judges only recorded evidence (`sent.jsonl`, `needs-jiv.jsonl`, sign-in attempts, exit code, RUN_STATUS). Each round costs real ChatGPT quota.
- `battle-gate.sh`: one-shot release gate. Live cron lines parked as `#BATTLE-GATE ...` are re-enabled only if every round passes; Jiv gets the verdict on Discord.

**Mini-specific gotchas:**
- **Never let Codex browse the inbox.** Through the Playwright MCP one inbox run was ~36 tool calls and **~3M tokens** (27-43K character page snapshots, each re-read on every later turn), and two test runs used up the ChatGPT 5-hour window on 2026-09-30. `linkedin-inbox.js` reads and sends; Codex only reads the ~7KB digest. Selectors checked against real LinkedIn on 2026-09-30: list `[aria-label="Conversation List"] li.msg-conversation-listitem`, thread `.msg-s-message-list-content`, sender `.msg-s-message-group__name`, composer `div.msg-form__contenteditable`, `button.msg-form__send-button`. The list preview often shows a subject line instead of "You:", so who spoke last is read from the thread.
- **The ChatGPT plan behind Codex has a usage limit, shared with the Mini's other Codex automations.** It ran out on 2026-09-30 after a morning of dry runs. The runner reads "try again at HH:MM" from Codex's error, pauses all runs until then (`~/.linkedin_codex_blocked_until`), and DMs once. This profile runs at `model_reasoning_effort = "medium"` and the inbox every 3h to stay under it.
- **Don't reuse `~/.playwright-linkedin-profile` on the Mini.** A long-running Claude Code Discord bot (tmux `work`) has its Playwright plugin pointed at it, so sharing it means profile-lock collisions.
- **The global `~/.codex/config.toml` is never edited**: it runs the ChatGPT.app automations with full access. Everything LinkedIn-specific lives in the `linkedin` profile file, which `codex mcp list` without `--profile linkedin` doesn't show.
- **`codex exec` denies MCP tools that aren't read-only** under `approval_policy = "never"` ("MCP tool call requires approval, but approval policy is never"): snapshot works, navigate/click/type don't. The `linkedin-browser` server sets `default_tools_approval_mode = "approve"` (scoped to that server only). Verified 2026-09-30: Codex loaded the feed logged in as Jiv, and a cron-launched headed Chrome found the session.
- **`~/Desktop/Work` is a symlink to `~/Work`**, and Codex refuses writable roots with a symlink component ("symlinked writable roots are not supported"). Every path Codex writes to uses `~/Work/...`.
- **`codex exec` exits 0 even when the run did nothing** (the first dry run couldn't write a file, gave up, and exited 0). Hence the `RUN_STATUS=ok` line the skill must print.
- **The job-followup Discord token in `~/.job-followup-config.json` is dead (401)**, so its alerts fail silently. The notifier uses the live Claude Discord bot's token from `~/.claude/channels/discord/.env` instead.
- **The brew `codex` (0.155.0, first on the runner's PATH) hung on everything, even `--version`, after the Codex app self-updated on 2026-09-30.** Both battle rounds then sat out the full 45 min cap (exit 142, no output) and the gate failed for a reason that had nothing to do with replies. The standalone `~/.codex/packages/standalone/current/bin/codex` (0.159.2) answered instantly. The runner now defaults to the standalone `current` binary and runs a `--version` preflight (`LINKEDIN_PREFLIGHT_SECONDS`, 20s) before every Codex call: no answer means exit 5, `RUN_STATUS=blocked:codex_unresponsive`, one alert, nothing spent. If runs start failing with exit 5, check `codex --version` by hand first.
- **No `timeout` on macOS**: the runner caps a run at 45 min with `perl -e 'alarm ...'` (exit 142 = cap hit), then kills any Chrome left on the profile.
- **Crontab survives reboots, but Chrome is headed**, so it needs the `admin` console session logged in. Auto-login is off on the Mini, so after a reboot, runs fail until someone logs in at the console.

### Easy Apply on the Mini (`linkedin-codex-runner.sh apply`, added 2026-10-01)

> **Switched OFF by Jiv, 2026-10-22: no LinkedIn Easy Apply.** `~/Work/job-email-bot/marketing/outreach/easy-apply.disabled` exists on the Mini. While it does, `apply_pass` returns before scanning, so neither the `apply` mode nor the DM-link pass in every inbox run opens, decides on or submits any Easy Apply job (test: `run_runner_tests.sh` 5e2). No search-based cron was ever installed. Job links people DM are no longer applied to or forwarded, only the normal reply pass sees them; off-LinkedIn links still go through the email-apply pass (`email-apply.disabled` is its own switch). To turn it back on, delete the file, and review `apply-profile.json` first (three preferences are still `null`, `aws`/`docker`/`fastapi` years have no work behind them, the peso pay does not match the USD, and the resume file's Crowdsnare dates disagree with the identity notes).

Same split as the inbox pass: **the script does all the page work, Codex (profile `linkedin-apply`, no browser) only decides.**

```
scan (linkedin-apply.js)  ->  Codex: APPLY DECIDE  ->  fill (script)  ->  Codex: APPLY ANSWER (only if needed)  ->  fill again (script)
```

- **scan**: 8 keywords x 2 seeds (Philippines geo `103121230` first, Worldwide `92000000`), last 24h, remote, Easy Apply only. Keeps cards whose location says Philippines/APAC/worldwide, drops already-applied ids, one application per company+title (the same role is often posted once per city), then reads each JD into `.apply/digest.json`. The Philippines geo seed is what fixes the old "0 in scope" problem: LinkedIn "Remote" under Worldwide is almost always country-locked.
- **decide**: Codex scores fit and writes `.apply/decisions.json`. It skips roles needing 4+ years, .NET/AWS ops, or fixed night shifts. Apply only at fit 70+.
- **fill**: the script walks every modal page and fills every field it can answer from rules (`apply-profile.json`: links, phone, English level, work authorization for the Philippines only, years per technology, EEO = decline) or the learned `apply-answer-bank.json`. Anything else is collected in `.apply/pending.json`. Answers that match no option or are not a number in a numeric box are rejected, not typed.
- **answer**: one Codex call answers the pending questions from `apply-resume.md` + the facts. **Any `null` skips the job** (a null is the honest answer, not a failure). Jobs that stay unanswered get one retry next run, then are final.
- **Dry run**: `linkedin-codex-runner.sh apply --dry-run` does everything except Submit: every form is filled through to the Review page and discarded.
- **Files** (all in `~/Work/job-email-bot/marketing/outreach/`, none in this public repo): `apply-profile.json` (copy `scripts/apply-profile.example.json`; holds the phone number), `apply-resume.md`, `apply-answer-bank.json`, `apply-log.jsonl`, `.apply/`. Codex skill: `codex/skills/linkedin-apply/SKILL.md` (install to `~/.codex/skills/linkedin-apply/`), profile `codex/linkedin-apply.config.toml` (install to `~/.codex/`).
- **Cron**: not scheduled. Suggested line, parked until a live run is supervised: `27 9,13,17 * * * /Users/admin/agent-work/jobi/scripts/linkedin-codex-runner.sh apply`.
- **Cost measured 2026-10-01**: decide ~27K tokens, answer ~20K tokens, scan ~11 min wall time (16 searches + 12 JD pages).
- **Real-LinkedIn facts** (2026-10-01): the modal's Next button is now named just `Next` (older notes say "Continue to next step"); pages are Contact info (prefilled) -> Resume (your resume is remembered) -> Additional Questions -> Review; a blocked Next shows "This field is required" / "Invalid input" and the page does not advance; numeric boxes reject words; `navigator.webdriver` must be false or Submit silently does nothing (the Playwright launch here already sets that).
- The old MacBook skill `~/.claude/skills/linkedin-apply` (Claude-driven, interactive) still exists and is unchanged.

### Job links people send in DMs (added 2026-10-15)

People DM Jiv job openings. The **inbox pass** now chains an apply pass for them, through the same pipeline as above, so no new applier exists.

```
inbox read (linkedin-inbox.js)  ->  digest.json job_leads  ->  scan --dm --dm-only  ->  Codex: APPLY DECIDE  ->  fill  ->  ...same as Easy Apply
```

- **Where links come from**: `linkedin-inbox.js read` collects every URL from the OTHER person's messages (`.msg-s-event-listitem--other`; Jiv's own links never count) and classifies them in `scripts/linkedin-job-links.js` (LinkedIn job id, `lnkd.in` followed once, `safety/go` wrappers unwrapped, off-site job/ATS pages kept). It also opens "You: ..." threads, for links only, because a link usually sits in a chat the bot already answered. Those threads never reach Codex.
- **LinkedIn jobs** (`/jobs/view/<id>`, `currentJobId=`): `linkedin-apply.js scan --dm <digest> --dm-only` opens each new id (max 8 per run), skips closed / already applied / no Easy Apply, and queues the rest with `source: "dm"` and `shared_by`. They skip the keyword and location filters (a person chose them) but go through the same fit gate (70+) and every honesty rule. Submissions stay capped at 5 per run.
- **Not Easy Apply, or off LinkedIn**: the runner cannot apply there. One `needs-jiv.jsonl` row per person (Discord DM), once per URL.
- **Memory**: dead, closed and off-site LinkedIn jobs are written to `apply-log.jsonl` with `source: "dm"` so they are not re-opened every 3h. When no id is new the scan exits before launching Chrome and Codex never starts.
- **Cost**: no links, no extra work. With links: one decide pass (~27K tokens) plus, only if questions are unanswered, one answer pass.
- **Dry run**: `linkedin-codex-runner.sh inbox --dry-run` fills the forms to Review and records nothing.
- **Tests**: `tests/battle/test_job_links.js` (extractor), `run_runner_tests.sh` section 5e (the chained pass).
### OnlineJobs login (`scripts/onlinejobs-ensure-login.js`, added 2026-10-15)

The OnlineJobs automation signs itself in, so the session never has to be restored by hand. `npm run onlinejobs:login` runs it; the inbox and apply scripts call `ensureLoggedIn(page)` from it.

- **Two sites, two sessions (2026-10-22).** `www.onlinejobs.ph` and `v2.onlinejobs.ph` do not share cookies. The apply job reads postings on **www**, where the external form link is hidden behind "Please login or register" while signed out, so `ONLINEJOBS_SITE` defaults to `www`; `ONLINEJOBS_SITE=v2` selects the messaging site. The inbox checker (`onlinejobs-check.py`) signs in to v2 by itself and does NOT sign in the apply browser.
- **Normal run types nothing.** A persistent Chrome profile (`ONLINEJOBS_PROFILE`, default `~/.onlinejobs-profile`; the Mini apply job points it at `~/.onlinejobs-apply/browser-profile`) keeps the cookie. www has no redirect-to-login, so "signed in" is read from `/jobseekers/jobsearch`: the nav must show Messages + Account and no "LOG IN" link (both, so a Cloudflare page never reads as signed in). v2 still uses the `/message` redirect.
- **Expired session:** it signs in once with the saved credentials (www fields `info[email]` / `info[password]`) and verifies by loading the check page again.
- **Flags:** `--check` never signs in, only reports (exit 4 when signed out), so a person or a test can inspect the real session without typing. `--google` also requires the profile to be signed in to Google (exit 7 when not). It never types there: Google blocks scripted sign-in (device checks, 2-step), so Google is detect-and-tell, not re-login.
- **Credentials, first hit wins:** env `ONLINEJOBS_EMAIL`/`ONLINEJOBS_PASSWORD`, then `~/.onlinejobs.env` (the Mini, chmod 600), then Keychain service `claude-onlinejobs` (the MacBook). The password is never printed or screenshotted.
- **It cannot lock the account:** one attempt per run, at most 2 per hour (`~/.onlinejobs-login-state.json`); a rejected password sets a 6 hour cooldown and is never retried before it ends; a captcha, a verification code or a changed form exits 3 for a human.
- **Exit codes:** 0 logged in, 3 needs a human, 4 signed out (`--check` only), 5 credentials missing or rejected, 6 throttled, 7 Google signed out (`--google`).
- **Session cookies:** if OnlineJobs issues a session-only cookie (no expiry), Chrome drops it on close and every run signs in again; that is the case this script exists for, and the 2 per hour cap still applies, so run the apply passes in one browser session.
- **Tests:** `tests/battle/test_onlinejobs_login.js` (16, against a local mock login server with fake credentials: already logged in posts nothing, good login on www and v2, wrong password cools down and never retries, missing credentials, captcha, throttle, `--check`, `--google`).
- **Verified against the real www site 2026-10-22** on the Mini: a profile cloned from the MacBook had lost its OnlineJobs session (the posting read exactly like a brand-new profile, form link hidden); one scripted sign-in restored it, confirmed by a fresh Chrome launch and by `--check --google` printing `already`. Copying the profile is therefore not a reliable fix (the server ended the cloned session), and the runner no longer relies on it.

### Alerts to the iPhone and the OnlineJobs auto-reply (added 2026-10-19)

The replies exist to reach a booked meeting. When a conversation gets there, Jiv is alarmed, and the bot stops talking in that thread.

- **One notifier:** `scripts/linkedin-notify.py` is the only alert path (LinkedIn runner, `linkedin-email.py`, the OnlineJobs checker all call it). `--level info` = Discord DM only (default, every old `--text` call); `needs` = Discord + Pushover normal; `meeting` = Discord + Pushover **emergency** (iOS Critical Alert: breaks through silent and Do Not Disturb, repeats every 60 s for 30 min until Jiv taps Acknowledge). `--key K` rings once per event. Discord and Pushover fail independently. `needs`/`meeting` alerts carry `Conversation:` (the thread link) and `Calendar:` (any booking link found in their message, via `--calendar`; Calendly, Cal.com, Meet, Zoom, Teams and similar, see `meeting_signal.booking_links`), links first on Pushover so its 1024 char cap cannot cut them. Pushover is LIVE as of 2026-10-19 (`~/.pushover.env` on the Mini).
- **Pushover setup (Jiv, once):** install Pushover on the iPhone (one-time purchase), allow Critical Alerts in its settings, create an application at pushover.net/apps/build, then on the Mini write `~/.pushover.env` (chmod 600) with `PUSHOVER_TOKEN=...` and `PUSHOVER_USER=...`. Until that file exists the Pushover leg is skipped and only the Discord DM goes out. Discord cannot bypass Do Not Disturb; Apple only grants Critical Alerts to approved apps.
- **Meeting detector:** `scripts/meeting_signal.py` (their message only): a booking/call link (Calendly, Meet, Zoom...) or a request to schedule, "when are you available", or an interview with a day/time. A video request, a take-home or "before scheduling an interview" is NOT a meeting. LinkedIn escalations in `needs-jiv.jsonl` go through it too.
- **OnlineJobs checker:** `scripts/onlinejobs-check.py` (runs on the Mini from `~/Work/job-email-bot/`, cron `*/30` all day: scans and ALERTS around the clock, but only SENDS replies 16:00-22:59 UTC; outside that window a thread that needs a reply is left unrecorded for the night run, and the alert key stops a second ring). It reads the whole inbox (rows are `data-cy="thread-<id>"`, click to open, no links), parses the last message from the `<email>` header line (`onlinejobs_decide.parse_thread`; the last `<li>` is NOT a message), and keeps per-thread state in `oj-state.json`. Rules in `scripts/onlinejobs_decide.py`: first sight of an old thread is baselined and never replied to; max 3 bot replies per thread per 7 days; a meeting alarms first, sends one reply, then hands the thread over for good; a read-the-post questionnaire or a take-home with a deadline alerts Jiv and sends nothing; a video/form request sends a holding reply and alerts.
- **Kill switch:** `~/Work/job-email-bot/onlinejobs-check.disabled` stops only this checker. `job-email-bot.disabled` (2026-07-18, repeated interview emails) still stops `job-followup.py` and `oj-apply.py`.
- **Drafting:** standalone `codex exec` (read-only, 90 s), not `claude -p` (not logged in on the Mini). Em/en-dashes are stripped before sending. A reply only counts once it is visible in the reloaded thread.
- **Whole-thread links:** the checker expands every collapsed message (client side only; older messages show a one-line preview otherwise) and parses each one from its `<email>` header (`onlinejobs_decide.parse_messages`). Booking links come from EVERY message they wrote, newest first, deduped (`thread_booking_links`); Jiv's own messages are skipped because his application text carries his portfolio links.
- **Quiet meeting threads:** a meeting alarm records `alarm_ts`. If Jiv has not answered, he is reminded at 4 h (`needs`) and 24 h (`meeting`, the emergency alarm), then never again (`nudge_due`). Checked for every known thread, including ones deferred to the night run. Jiv replying himself clears it (`jiv_took_over`); the bot's own courtesy reply, sent from the same account, does not (it records `bot_probe`).
- **Draft safety:** every draft passes `reply_ok` (length, no `[placeholders]`, no model boilerplate, no dashes, signed, no link that is not in the profile or the thread). One retry with the reason; after two failed runs the thread is handed to Jiv with an alert instead of retrying every 30 minutes.
- **Facts the drafter may use:** `oj-profile-facts.md` (verified current roles, GoHighLevel and n8n work, results; private because it carries employer figures, so it is git-ignored; canonical copy in the Obsidian vault `Projects/jobi/oj-profile-facts.md`, placeholder at `scripts/oj-profile-facts.example.md`) is loaded before the old profile file, which predates Traciety and made a draft deny GoHighLevel experience he has. Standing facts (rate, hours, start date) are in `STANDING_FACTS`. Availability text is computed for the date (`availability_text`), so the New York label is right on both sides of the daylight-saving change.
- **Asks only Jiv can answer:** a request for examples, a portfolio or case studies, a video or a form gets a holding reply plus an alert; a read-the-post questionnaire, a take-home or a deadline gets an alert and no reply.
- **It cannot fail silently:** a crash, a rejected login, an unreadable inbox, an inbox that suddenly shows 0 threads, 3+ threads that will not open, or reply trouble each send one `needs` alert per kind per day (`health`). A daily Discord digest (after 09:00 PHT, info level) lists the last 24 h and what is still open for Jiv. Known gap: if cron itself stops, nothing runs to alert.
- **Deploy (Mini does not git pull):** `scp scripts/onlinejobs-check.py scripts/oj-profile-facts.md admin@100.98.219.58:Work/job-email-bot/` (the facts file is your local private copy) and `scp scripts/{onlinejobs_decide,meeting_signal,linkedin-notify}.py admin@100.98.219.58:agent-work/jobi/scripts/`.
- **Tests:** `tests/battle/test_meeting_signal.py` (24: detector, link extraction, notifier routing and links, dedupe, either channel down) and `tests/battle/test_onlinejobs_decide.py` (43: decisions, whole-thread parsing, nudges, draft safety, availability, digest; fixtures shaped like the live pages). No network.

### OnlineJobs external-application discovery (added 2026-10-20)

Most OnlineJobs postings are applied to natively (autonomousapply.com, which spends apply points). A minority send the candidate out of the site to a Google Form, Typeform, an ATS page, or an apply email. Those are free and nobody else was watching for them. First live scan (2026-10-20, five keywords, page 1): **140 postings, 10 with a form link, 8 with only an email, 62 already applied natively**; after the gates, about 3 of the 18 were worth a look.

- **Where it runs:** `scan_forms()` in `scripts/onlinejobs-check.py`, after the inbox pass, every 3 h (`FORMS_SCAN_EVERY_S`), reusing the checker's login. Pure parsing and gating live in `scripts/onlinejobs_forms.py` (no browser; `tests/battle/test_onlinejobs_forms.py`, 22 tests built from the live page shapes). It sends nothing to any employer.
- **Breadth (changed 2026-10-22):** `search_plan()` scans 20 keywords on page 1 plus page 2 of five (25 pages per scan). It was 5 keywords, page 1: 337 postings in 1.8 days and 5 leads, 1 real fit. On 2026-10-22 the 16-page plan saw 395 postings and `developer`, `engineer`, `node js`, `nodejs`, `software engineer`, `programmer`, `javascript` added about 190 more, plus 31 from page 2 of `developer`/`engineer`; `node js` alone added 29 because the board matches words (`node.js developer` does not find "Node JS Full Stack"). Only unseen postings are opened, 80 per run, the rest next run, so the first scans after this change work through a one-time backlog. Link shorteners (`bit.ly`, `tinyurl.com`, `t.ly`, `cutt.ly`, `rb.gy`, `shorturl.at`, `ow.ly`) and `forms.office.com` count as form links; the apply run opens the target and applies its own gates. The form regex has a left boundary so `notbit.ly/x` and `me@tally.so/x` do not match. First wide scan: 564 postings judged, 77% native (autonomousapply.com's lane), 2 new leads. Postings still listed show Date Applied dates of 1 to 3 per day through 2026-10-22, so the native lane is applying; this lane is the thin 1 to 2%.
- **Gates (`judge`):** drops native, closed (deleted page OR the "This job has been closed." banner, 7 of 140 had it), already applied on the site (`Date Applied:`), non-engineering titles (misfit list), and a top wage under **$1,000/month** (floor lowered from $2,000 on 2026-10-22) (hourly x 4 x hours/week; bare number under 300 = hourly, from 15,000 = pesos at 56/USD). An unlisted wage is kept for a human read.
- **Output:** `oj-state.json` -> `forms.leads` (id, title, employer, wage, `form_url` or `apply_email`, `first_seen`). One Discord DM (info level, no Pushover) lists new leads. Leads expire after 14 days. `forms.seen` stops a posting being opened twice; a first scan opens at most 80 postings per run and finishes the backlog on the next run.
- **Who applies:** the `/onlinejobs-apply` skill (browser, Google signed in) reads the queue over SSH (`ssh admin@100.98.219.58 "python3 -c ..."` snippet in the skill) instead of re-scanning, fills the form and sends email-applies. The Mini never fills a form.
- **Email leads go out over the Gmail app password (decided by Jiv 2026-10-23).** Not through `linkedin-email.py send` itself, which only trusts a recipient on the employer's own domain, but through `onlinejobs_send_email.py`, which reuses its draft check and message builder and trusts the `apply_email` this scanner read off the posting (the same address the browser path used to email). See "The trigger".
- **Kill switch:** `touch ~/Work/job-email-bot/onlinejobs-forms.disabled` stops only the scan. Three failed scans in a row send one `needs` health alert; replies are never affected (the scan is wrapped so it cannot raise).
- **Deploy:** `scp scripts/onlinejobs-check.py admin@100.98.219.58:Work/job-email-bot/` and `scp scripts/onlinejobs_forms.py admin@100.98.219.58:agent-work/jobi/scripts/`.

**The trigger (added 2026-10-22, moved to the Mac Mini the same day).** Until then nothing ran `/onlinejobs-apply`: the Mini queued leads, DMed Jiv, and they sat. Now the Mini's cron runs `scripts/onlinejobs-apply-mini.sh` hourly (`5 * * * *`). It was first built as a MacBook launchd job and moved because a laptop sleeps with its lid; the Mini is always on.

- **Where everything lives (Mini):** runner `~/agent-work/jobi/scripts/onlinejobs-apply-mini.sh`; browser MCP config `~/.onlinejobs-apply/mcp.json` (repo: `claude/onlinejobs-apply.mcp.json`); skill `~/.codex/skills/onlinejobs-apply/SKILL.md` (repo: `codex/skills/onlinejobs-apply/`, the folder name is a leftover from the Codex port); state `~/.onlinejobs-apply/` (`state/applied.jsonl` and `TRACKER.md` are now the canonical tracker, `browser-profile/`, `resume.pdf`, `claude.env`, `login-state.json`, `logs/`). Deploy by `scp`, the Mini does not git pull. The MacBook's Claude skill `/onlinejobs-apply` stays for manual, interactive runs and keeps its own tracker copy; they are separate files now.
- **Claude, not Codex (switched 2026-10-22):** the ChatGPT quota behind Codex is shared with the Mini's LinkedIn automations, so a busy day there could starve this run. `claude -p --model sonnet` runs on the Claude subscription. The Mini's normal Claude login sits in the login keychain, which is locked in cron and over ssh, so the run authenticates with a long-lived token from `claude setup-token`, saved in `~/.onlinejobs-apply/claude.env` (chmod 600) by the one-time helper `scripts/onlinejobs-claude-token.sh` (`ssh -t admin@100.98.219.58 ~/agent-work/jobi/scripts/onlinejobs-claude-token.sh`). `ANTHROPIC_API_KEY` is dropped from the environment first (the key stored on the Mini is invalid and would win over the token). Permissions: `dontAsk` plus an allowlist of the `onlinejobs-browser` MCP, Read, the logging command and the send command; WebFetch, WebSearch and Agent are off. `--strict-mcp-config` loads only `mcp.json` (Playwright MCP 0.0.83 on real Chrome).
- **Sign-in is repaired before the model starts.** The runner calls `onlinejobs-ensure-login.js` on the run's own profile (see "OnlineJobs login"), adding `--google` only when a queued lead's form is a Google Form (`docs.google.com/forms`, `forms.gle`, `goo.gl/forms`). A dead OnlineJobs session is signed in again with the saved credentials; a captcha, a rejected password or a throttle stop the run with an action-first alert and the leads stay queued for the next tick. Google signed out holds back only the Google Form leads (they stay queued, the login streak counts toward the alert) and the run works the rest. No model run is spent on a dead session.
- **Email applies use the Gmail app password, not the browser (2026-10-23).** On 10-22 Google put the cloned profile behind "confirm it's you" around 23:00 and the old `--google` check stopped four runs in a row (23:05 to 02:05, phone alert at the 4th) though the only queued lead was a Breezy form. The model now sends with `scripts/onlinejobs_send_email.py`, allowlisted with its `--leads`/`--resume` prefix fixed by the runner. In code, not in the prompt: the recipient is the queued lead's `apply_email` (the model never names it), one email per recipient and per posting ever (its own `state/email-sends.jsonl`, `applied.jsonl`, and LinkedIn's `email-apply-log.jsonl`), 5 a day (`OJ_EMAIL_DAILY_CAP`), fit 70+, `linkedin-email.py`'s draft check (no dashes, no phone numbers, only Jiv's links). It logs `sent` itself only after Gmail accepts, so the model's logging command no longer offers `sent`. Kill switch: `touch ~/Work/job-email-bot/onlinejobs-email.disabled`. `OJ_EMAIL_DRY_RUN=1` on the runner makes it print the draft instead of sending; a live `claude -p` run on the Mini with it set (2026-10-23 02:22, throwaway state dir, alerts stubbed) proved the allowlist admits the command and the model logs the lead after a "not sent".
- **The browser profile began as a copy of the MacBook's** (Playwright profiles use a mock keychain, so cookies decrypt on another Mac). The Google session survived; the OnlineJobs one did not last (see "OnlineJobs login"), hence the scripted sign-in. Chrome allows ONE process per profile: the run skips a tick when `user-data-dir=<profile>` (with `=`) is held.
- **Gate first, Claude second.** `onlinejobs_apply_gate.py` reads `oj-state.json` locally (over SSH when run elsewhere) and drops what is already in the tracker by posting URL, form URL, apply email or employer name. Exit 0 work, 3 nothing (no Claude session), 2 queue unreadable (loud, never read as "nothing").
- **The run:** `claude -p` (see above), 40 min cap (`OJ_APPLY_CAP_S`, perl alarm because macOS has no `timeout`; a kill also closes its Chrome). It logs only through `onlinejobs_log_outcome.py`, which writes `applied.jsonl` and `TRACKER.md` together into `$OJ_SKILL_DIR`.
- **Done means logged.** After the run `onlinejobs_apply_report.py unhandled` checks every lead has an outcome; a lead without one is a failed run even if Claude exited 0 (it does that when the browser is signed out or the usage limit is hit). Failures speak at 2 runs in a row (Discord) and 4 (phone).
- **Hand-off alerts lead with the action.** A `handoff` note must START with what Jiv has to do (under 150 characters); a phone cuts the rest.
- **Switches:** `touch ~/.onlinejobs-apply/PAUSE` or `~/Work/job-email-bot/onlinejobs-apply.disabled` stops it. `onlinejobs-apply-mini.sh --dry-run` runs only the gate; `--leads FILE` works exactly those leads. Logs `~/.onlinejobs-apply/logs/`.
- **What can still stop it:** Google signing the profile out, now only for Google Form leads (it happened within 2 hours of cloning the MacBook profile on 10-22; sign in once in the Mini's own browser, e.g. by Screen Share to `vnc://100.98.219.58`, then `open -na "Google Chrome" --args --user-data-dir=$HOME/.onlinejobs-apply/browser-profile https://mail.google.com` and quit it before :05), a revoked Gmail app password (email applies), an OnlineJobs captcha at sign-in, a changed password in `~/.onlinejobs.env`, the Claude token being revoked (rerun the token helper), the Claude usage limit, or the Mini being off. The old MacBook launchd job, its keep-awake agent and the heartbeat check were removed.
- **Tests:** `tests/battle/test_onlinejobs_apply_{gate,report}.py`, `test_onlinejobs_log_outcome.py`, `test_onlinejobs_send_email.py` (12: sends only to the queued address, every refusal, kill switch, Gmail failure logs `failed` not `sent`, dry run writes nothing), `bash tests/battle/run_apply_runner_tests.sh` (18 checks of the runner with a fake `claude` and fake login helper: login runs before the model, Google is checked only for a Google Form lead and held leads do not stop the others, the send command is allowlisted, no token or any login failure never starts the model, the API key is dropped, a model that logs nothing counts as failed). The Mini chain was battle-tested with a canary lead (a misfit that must be skipped and logged) before the cron was installed.
- **Verified quirks:** (browser Gmail, retired for email applies 2026-10-23, kept for the MacBook skill) Gmail's `body=` deep-link parameter does not prefill; Gmail's "Attach files" exposes a file chooser the browser tool can fill, and the file must live in the working directory. Jotform hides its checkboxes under a styled span, so a normal click is intercepted: click the input by id in `browser_evaluate`. A Google Form's URL turns into `/formResponse` after the first Next; that is not a submission. The résumé (md5 `be84ec79...`) is staged at `~/.onlinejobs-apply/resume.pdf`; if it changes, update it there, the MacBook skill copy and the LinkedIn copy.
**What reaches Jiv's phone (changed 2026-10-22).** Before, every transient blip pushed and a mass "join our Discord" message rang the emergency alarm. Now:

| Event | Where |
|---|---|
| Application submitted or sent | Discord, one line per job. Skips are silent. |
| Application hand-off (sign-in, captcha, file) | Discord + normal push |
| Meeting request with a booking link, a day or a clock time, or "when are you free" | Discord + EMERGENCY alarm (repeats until acknowledged) |
| Meeting request without any of those ("we will set up an interview") | Discord + normal push |
| Reminder for an unanswered meeting (4 h, 24 h) | Discord + normal push (was emergency) |
| Employer wants your own work / reply cap hit | Discord + normal push, preview cut at a sentence |
| Automation problem (login, inbox, crash, apply run) | silent for 2 failed runs; Discord at 3 checker runs (~90 min) or 2 apply runs; phone at 6 checker runs or 4 apply runs; a success resets it |
| New external-application leads | no alert (queued silently) |

Rules live in `onlinejobs_decide.py` (`health_step`, `alarm_level`, `tidy`) and `onlinejobs_apply_report.py`. The checker's `log()` used to print AND append to `followup.log` while cron redirects stdout there too, so every line appeared twice; it now prints only on a terminal. Deploy the checker changes with `scp scripts/onlinejobs-check.py admin@100.98.219.58:Work/job-email-bot/` and `scp scripts/onlinejobs_decide.py scripts/onlinejobs_forms.py admin@100.98.219.58:agent-work/jobi/scripts/`.

### Email-apply for off-LinkedIn job links (added 2026-10-15)

A job link people DM that is not on LinkedIn (a careers page with `Email careers@...`) is now applied to by email from Jiv's Gmail. Chosen by Jiv 2026-10-15: auto-send with hard caps.

```
inbox read -> digest.json job_leads.external -> linkedin-email.py scan -> Codex: EMAIL APPLY (no browser, no mail) -> linkedin-email.py send (Gmail SMTP)
```

- **Scan** (`scripts/linkedin-email.py scan`): fetches each page (public hosts only, redirects re-checked; loopback, private and tailnet addresses are refused because the URLs come from DMs). A page counts as email-apply only when it publishes a `mailto:` on its OWN domain and has no application form. Everything else (forms, JS-only pages, a mailto on another domain) goes to `needs-jiv.jsonl`, one Discord DM per person.
- **Decide**: Codex gets the page text (untrusted data), `apply-profile.json`, `apply-resume.md`; writes `.email/drafts.json` (`apply`, `fit`, `subject`, `body`). Skill section `EMAIL APPLY` in `codex/skills/linkedin-apply/SKILL.md`.
- **Send**: SMTP SSL to `smtp.gmail.com:465` with the Gmail app password in `~/.job-followup-config.json` (only `email` and `app_password` are read), resume attached from `apply-resume.pdf`. Gmail still accepts app passwords on personal accounts in 2026.
- **Why the guard rails** (the old `job-followup.py` bot was switched off 2026-07-18 for repeated outbound emails; that kill file `job-email-bot.disabled` is a separate switch and stays):
  - the recipient is the address read off the page, never anything Codex wrote;
  - one email per recipient and per posting, ever (`email-apply-log.jsonl` is the memory; the Origami application sent by hand on 2026-10-15 is seeded in it);
  - max 5 sent per day (`LINKEDIN_EMAIL_DAILY_CAP`);
  - subject and body must have no em or en dash, no phone number, and only Jiv's own three links;
  - every send is DMed to Jiv on Discord afterwards;
  - `fit` must be 70 or more, and a posting that asks for money, an ID or a password is `apply: false`.
- **Kill switch**: `touch ~/Work/job-email-bot/marketing/outreach/email-apply.disabled` stops all sending on the next run (scans and Codex still run, nothing is mailed). Delete the file to resume.
- **Dry run**: `linkedin-codex-runner.sh inbox --dry-run` scans and decides, logs `dry_run_ok`, sends nothing, and dry rows never count against dedupe or the cap.
- **Files** (outreach folder): `email-apply-log.jsonl`, `apply-resume.pdf`, `.email/`.
- **Tests**: `tests/battle/test_email_apply.py` (19: page classification, SSRF, redirects, draft validation, caps, dedupe, kill switch, fake SMTP) and `run_runner_tests.sh` section 5f.
- **Found only by running it on the real links**: `OpenerDirector.open()` has no `context` argument, so every fetch failed until the opener was built with an `HTTPSHandler(context=...)`. A patched-`fetch` unit test could not see it; `RealFetch` in the tests now runs the real code against a local server.

- **Real job-page facts** (2026-10-15, found by dry-running the DM path on live jobs): no `<h1>` (title and company come from `document.title`, "Title | Company | LinkedIn"); an applied job shows an "Application status" block instead of Easy Apply; a taken-down job says "Unable to load the page"; location is the first `a · b ago · N applicants` line.
- **Real Easy Apply radio markup** (same day): question text is the radio's `aria-label` (and a `<p>` before the fieldset), the `<label for>` is empty and is the click target, option text sits in an ancestor, and the ids are React `useId` values that change after a click. The filler now finds radios by position and verifies they stayed checked. Before this fix, any job with Yes/No questions asked Codex about `radio-group-_r_f_` and could never be answered.
- **Real markup** (2026-10-15): there is no `.msg-s-message-group`; messages are `.msg-s-event-listitem`, the other person's carry `--other`. Thread rows have no `a[href*="/messaging/thread/"]` right now, so the reader falls back to the first anchor.

## How It Works

```
pm2 cron (*/15 * * * *)
  └── linkedin-grow-runner.sh
        ├── Phase 1: linkedin-ensure-login.js
        │     └── Opens persistent Playwright/Chrome profile
        │         Waits up to 5 min for login if session is cold
        │         Exits 0 once LinkedIn feed is detected
        └── Phase 2: claude --dangerously-skip-permissions --print "/linkedin-grow"
              └── Runs the /linkedin-grow Claude Code skill
                  Uses Playwright MCP with saved session
                  Sends connections, follows, comments
                  Step 7: decision-maker outreach (personalized pitch DMs)
                          reads/writes ~/.linkedin_outreach_log.jsonl for
                          dedupe + rolling weekly-cap enforcement
```

Runs once per day (8am+ guard), every 15 min polling window.

## Setup

### 1. Install the runner scripts

```bash
cp scripts/linkedin-grow-runner.sh ~/
cp scripts/linkedin-ensure-login.js ~/
chmod +x ~/linkedin-grow-runner.sh
```

### 2. Configure Playwright MCP for persistent sessions

Edit both Playwright MCP config files (find them at `~/.claude/plugins/`):

```json
{
  "playwright": {
    "command": "npx",
    "args": [
      "@playwright/mcp@latest",
      "--user-data-dir", "/Users/<you>/.playwright-linkedin-profile",
      "--executable-path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ]
  }
}
```

Paths to update:
- `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/playwright/.mcp.json`
- `~/.claude/plugins/cache/claude-plugins-official/playwright/unknown/.mcp.json`

### 3. Register with pm2

```bash
pm2 start ~/linkedin-grow-runner.sh \
  --name linkedin-grow \
  --cron "*/15 * * * *" \
  --interpreter /bin/bash \
  --no-autorestart

pm2 save
pm2 startup  # follow the printed command to survive reboots
```

### 4. One-time login (first run only)

pm2 will open a Chrome window automatically on the first run. Sign in with Google — the session saves to `~/.playwright-linkedin-profile` and all future runs are fully automated.

---

## Key Learnings / Gotchas

### 1. `claude --print` is headless — no Claude-in-Chrome

The `/linkedin-grow` skill is designed to use `mcp__claude-in-chrome__*` tools (which connect to your running Chrome via the desktop app extension). This works in interactive sessions.

**In pm2 / `claude --print`:** The desktop app extension isn't connected to the new isolated CLI session. The skill falls back to Playwright MCP instead.

**Fix:** Accept Playwright as the browser for automated runs. Configure it with a persistent profile.

### 2. Google OAuth is blocked in Playwright Chromium ("Chrome for Testing")

Google rejects OAuth sign-in when the browser is "Google Chrome for Testing" — their policy explicitly blocks it.

**Fix:** Use the real Chrome binary via `--executable-path /Applications/Google Chrome.app/...` or `--browser chrome`.

### 3. Google OAuth is blocked even in real Chrome under WebDriver automation

Playwright sets `navigator.webdriver = true` and launches Chrome with `--enable-automation`. Google detects this and blocks OAuth regardless of which Chrome binary you use.

**Fix (for the one-time login script):**
```javascript
await chromium.launchPersistentContext(profile, {
  ignoreDefaultArgs: ['--enable-automation'],
  args: ['--disable-blink-features=AutomationControlled'],
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
```

Once session cookies are saved, subsequent headless runs don't need OAuth — they reuse the saved session and Google's detection doesn't matter.

### 4. Playwright profile lock between Phase 1 and Phase 2

After the login script (`linkedin-ensure-login.js`) closes the browser, Chrome may not immediately release the profile lock. If Phase 2 (`claude --print`) starts too fast, the Playwright MCP server fails to acquire the lock.

**Fix:** The `linkedin-ensure-login.js` closes the context gracefully (`await ctx.close()`), which releases the lock. A small buffer between phases would help if this recurs.

### 5. `< /dev/null` is required for non-interactive `claude --print`

Without `< /dev/null`, the claude process waits 3 seconds for stdin, produces a warning, and the skill treats the wait as an opportunity to ask for user input — then hangs.

**Fix:** Always run `claude --print "..." < /dev/null` in automation.

### 6. Daily-once guard prevents runaway runs

The 15-min cron means the script fires 96 times a day. Without a guard, it would spam LinkedIn.

**Fix:** Timestamp file at `~/.linkedin_grow_last_run`. Script skips if today's date is already written there.

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/linkedin-grow-runner.sh` | Main pm2 entry point. Daily guard + two-phase execution. |
| `scripts/linkedin-ensure-login.js` | Phase 1. Opens persistent Chrome profile, waits for LinkedIn login (up to 5 min). |
| `~/.playwright-linkedin-profile/` | Persistent Playwright browser profile. LinkedIn cookies live here. |
| `~/.linkedin_grow_last_run` | Timestamp file. Prevents duplicate runs on same day. |
| `~/.linkedin_outreach_log.jsonl` | Outreach ledger. One line per contacted decision-maker (dedupe + rolling weekly-cap + follow-up tracking). Written by Step 7 of the skill. |
| `~/.claude/skills/linkedin-grow/` | The Claude Code skill that drives the actual LinkedIn actions. |

---

## Cron Schedule

```
*/15 * * * *   — polls every 15 min
```

With the 8am hour guard + daily-once stamp, this effectively runs once per day at the first 15-min window after 8am local time.
