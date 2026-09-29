---
name: linkedin-grow
description: Use when asked to grow LinkedIn, connect with people on LinkedIn, engage with LinkedIn posts, or boost LinkedIn presence. Triggers on phrases like "grow my LinkedIn", "connect on LinkedIn", "engage LinkedIn feed".
---

# LinkedIn Growth Automation

## Overview

Browser-driven LinkedIn growth session: send connection requests to suggested contacts, engage (like + comment) on relevant posts in your niche, follow relevant accounts, and — at the end of every cycle — run a small, personalized **decision-maker outreach** phase that pitches Jiv for remote software work (Step 7). Paced to stay under LinkedIn's bot-detection thresholds (12–15 connection requests/day, ≤100/week).

---

## YOUR PROFILE

```
Name:     Jiv Tuban
Title:    Software Engineer — Full-Stack + AI/Automation
Location: Cebu, Philippines (fully remote)
Company:  Technical Lead @ Crowdsnare AI
Goal:     Land remote software work — freelance/contract AND full-time.
          Software engineering is the core offer; AI agents/RAG/automation is the edge.
Niche:    Software development, full-stack (Next.js/TS, NestJS/FastAPI), AI agents,
          RAG, workflow automation (Claude Code/MCP, n8n, Playwright)

Voice for comments: Practical and technical, first-person shipped experience,
                    confident but not salesy. Specifics and numbers over adjectives.

Target connections (priority order for OUTREACH — see Step 7):
  - Tech recruiters & staffing / dev-agency owners  ← highest reply rate, place remote devs
  - Startup founders / CTOs at 5–50-person companies (only with a hireable-now signal)
  - Engineering managers / heads of engineering
  - Fellow senior/remote engineers (warm reciprocal network)

Hashtags to engage:
  - #softwaredevelopment
  - #AIengineering
  - #remotework
  - #buildinpublic

PROOF POINTS (rotate 1 per outreach DM — pick the one closest to their domain):
  - Speed-to-Lead AI agent → 11 vehicle sales, 90% booking conversion (Crowdsnare)
  - DTG order-processing workflow → 85% manual-time cut, 500+ orders/day (Freckles)
  - RAG chatbot → −40% latency, +57% retrieval recall (Ayahay)
  - Full-stack portfolio automation → 119+ MLS listings, $13.5M value automated
  - 1st place / 196 teams — GCash ImaGnation hackathon

Stack one-liner: Next.js/TS · NestJS/FastAPI · Supabase/Postgres · GCP Cloud Run ·
                 Claude Code/MCP · RAG · n8n · Playwright

RATE POLICY (critical — read before any outreach):
  - NEVER state a rate in a first message or connection note. Lead with a RESULT.
  - Only discuss rate once they've replied and asked. Floor = $35–60/hr or a project fee.
  - Do NOT anchor at $15–20/hr in writing — it caps every deal and reads junior to founders.
  - Frame value as outcomes ("automations that pay for themselves"), not hours.
```

---

## Steps

### 1. Connect to Chrome

```
Load: mcp__claude-in-chrome__tabs_context_mcp (createIfEmpty: true)
Load: mcp__claude-in-chrome__navigate
Load: mcp__claude-in-chrome__browser_batch
Load: mcp__claude-in-chrome__computer
```

Navigate to `https://www.linkedin.com/mynetwork/grow/`

### 2. Accept Pending Invitations

Screenshot → find "Invitations" section → click Accept on each pending invite.

### 3. Send Connection Requests (My Network)

Scroll through "People you may know" and "Suggestions for you" sections. Connect with people who have:
- Mutual connections (warm signals)
- Titles matching your target list (from YOUR PROFILE above)
- `#OPENTOWORK` badge (active job seekers — good reciprocal network)

**Pace:** 1 second wait between each Connect click. Stop after ~15-20 requests per session to avoid rate-limiting.

**Skip:** Students only (no title yet), unrelated roles, profiles with no mutual connections and no relevant title.

### 4. Follow Suggested Accounts

At the bottom of feed or My Network page, follow suggested companies and people in your niche.

### 5. Engage With Feed Posts

Navigate to the hashtag search for your primary niche hashtag, sorted by Latest:
`https://www.linkedin.com/search/results/content/?keywords=%23YourHashtag&sortBy=date_posted`

Also check your other niche hashtags from YOUR PROFILE.

For each relevant post (sorted Latest, posted within 24h):
1. **Like** the post
2. **Comment** — write a substantive comment (2-4 sentences) that:
   - Adds a real perspective or insight
   - References specific details from the post (shows you read it)
   - Reflects your identity and niche
   - Never generic ("Great post!", "Thanks for sharing!")

Target 2-3 quality comments per session. Early comments on fresh posts get the most visibility.

### Comment Writing Standards (Anti-Slop)

Before drafting a comment, internally reframe the post's claim as a neutral question ("Is X actually true? Does Y always apply?"), then answer that question honestly. This prevents reflexive agreement.

**Rules:**
- **State a position directly.** No "it depends" unless you immediately name what it depends on and how.
- **Specific beats general.** "This breaks when you have >10k rows and no index" beats "performance can be a concern."
- **One strong sentence > three weak ones.** If a sentence doesn't add information, cut it.
- **If you disagree with the post's premise, say so first**, then offer the alternative. Respectful disagreement gets more engagement than agreement.

**Hard bans — never write these:**
- "Great post!" / "Thanks for sharing!" / "So true!"
- "As an AI..." or any AI self-reference
- "I completely agree" as an opener
- Hedges: "It's worth noting that...", "One might argue...", "In some cases..."
- Ending with a generic question just to drive engagement ("What do you think?")

**Good comment shape:**
> [Specific reaction to one concrete detail from the post] + [your experience or counter-angle] + [optional: one tight question that's genuinely curious, not a CTA]

### 6. Home Feed Engagement

Navigate to `https://www.linkedin.com/feed/`

Scroll through — like posts from:
- Direct connections sharing work/achievements
- High-engagement posts in your niche (VP/Director level)
- Posts that align with your target hashtags

### 7. Decision-Maker Outreach (run LAST, every cycle)

This is the money phase: quietly pitch Jiv for remote software work. It is a *feeder*, not a
firehose — 2026 data says only ~2–3% of contacted people reply and founders reply at just
~6.4%, so this phase wins on **relevance and personalization, not volume.** Keep it small,
hand-curated, and logged. Never blast a template.

#### 7a. Load outreach state (dedupe + cap enforcement)

Read `~/.linkedin_outreach_log.jsonl` (create if missing). Each line:
```json
{"date":"2026-07-09","name":"...","url":"https://www.linkedin.com/in/...","segment":"recruiter|founder|eng-manager","stage":"note_sent|followed_up|replied|skip"}
```
From it, compute:
- **contacted URLs** → never contact the same person twice
- **this-week count** (rolling 7 days) of `note_sent` → must stay under the weekly cap below
- **pending follow-ups** → anyone `note_sent` 2+ days ago who is now a 1st-degree connection and has NOT been `followed_up`

#### 7b. Send follow-up DMs to people who accepted (do this before new notes)

For each pending follow-up (max **10/day**): open the conversation and send the **Follow-up DM**
(template below), rotating in the single proof point closest to their domain. Log `stage:"followed_up"`.
If they already replied, DON'T send the template — draft a genuine 1:1 reply instead and log `stage:"replied"`.

#### 7c. Send NEW personalized outreach notes (max 5/day, hard cap)

These 5 come OUT OF the day's total connection-request budget (they are not extra). Source targets in
this priority order and **only send if you can write a true one-line personalization** (a real detail from
their profile/post/company). If you can't personalize it, skip it.

1. **Recruiters / staffing / dev-agency owners** who place remote or offshore engineers
   (search: `remote developer recruiter`, `staffing`, `software talent`, `dev agency founder`).
   Highest reply audience (~19%). They broker gigs — pitch availability, not a hard sell.
2. **Founders / CTOs at 5–50-person startups — ONLY with a hireable-now signal:**
   - Recently funded (seed / Series A in last ~6 months)
   - Actively posting 2+ engineering/AI roles right now
   - Posting about shipping AI features, automation pain, or "we're hiring"
   - Recent contractor churn
   Skip any founder with no visible signal — they're drowning in pitches and won't reply.
3. **Engineering managers / heads of eng** at remote-friendly companies actively hiring.

Send the **Connection note** (≤300 chars, personalized hook required). Log `stage:"note_sent"`.

#### Message templates (soft-ask first — a first message that pitches converts <2%)

The goal of message 1 is a **reply, not a sale.** Lead with a specific, relevant hook. No rate. No wall of text.

**Connection note** (with the request):
> Hey {First} — {personalized hook: saw your post on X / noticed {company} is hiring a {role} / saw {company} just raised}. I'm a software engineer who ships full-stack + AI/automation (Claude/MCP agents, RAG, n8n). Would be great to connect.

**Follow-up DM** (2+ days after they accept):
> Thanks for connecting, {First}. Quick reason I reached out — {restate the signal, 1 line}. I recently {ONE proof point, e.g. "built a speed-to-lead AI agent that booked 11 vehicle sales at 90% conversion" / "shipped a RAG chatbot that cut latency 40%"}. If you're taking on remote software or AI/automation help, happy to show how I'd approach {their thing} — and if not, no worries, glad to be connected.

**Recruiter/agency variant** (segment=recruiter) — availability, not a sale:
> Thanks for connecting, {First}. I'm a full-stack + AI/automation engineer (Next.js/NestJS, Claude/MCP agents, RAG) opening up for remote work — contract or full-time. If you ever place engineers into remote/offshore roles, I'd love to be on your radar; happy to send a quick portfolio.

**Rules:**
- Personalize the hook every time — it's a ~4× lever. A templated blast lands at the 5–8% floor.
- Lead with a RESULT, never a rate (see RATE POLICY in YOUR PROFILE).
- Soft ask ("if you're taking on help…") beats a hard offer for the opener. Make the concrete offer only after a reply.
- One proof point per DM, matched to their domain. Don't list all of them.
- If a target's profile shows they're clearly not hiring and not a broker, skip and log `stage:"skip"` (still counts as "seen", won't be re-evaluated).

---

## Rate Limits (Stay Safe)

| Action | Safe Daily Limit | Weekly |
|--------|-----------------|--------|
| Connection requests (total) | **12–15** | **≤100** |
| — of which outreach notes (Step 7c) | **≤5** | ≤25 |
| Outreach follow-up DMs (Step 7b) | **≤10** | — |
| Likes | 50–100 | — |
| Comments | 5–10 | — |
| Follows | 20–30 | — |

Exceeding these triggers LinkedIn's automated restrictions (account can be locked 1–3 weeks).
The ≤100/week connection cap is a **platform limit** — the log in Step 7a enforces it. Outreach
notes are a *subset* of the daily connection budget, not extra. Space actions with randomized
human-like delays; run only during business hours; skip a day occasionally.

**Why local is safe:** this runs through your real Chrome profile on your own IP (Mac Mini), which
LinkedIn treats as normal traffic. Do NOT migrate to a cloud tool (Expandi/HeyReach/Dripify) for
"safety" — cloud/data-center sessions hit ~40% restriction rates in 2026. Local + low volume wins.

---

## Common Mistakes

- **Connecting with everyone blindly** — prioritize mutual connections and relevant titles
- **Generic comments** — LinkedIn's algorithm demotes them; write real thoughts
- **Too many requests too fast** — LinkedIn will restrict the account
- **Commenting on old posts** — sort by Latest for maximum visibility
