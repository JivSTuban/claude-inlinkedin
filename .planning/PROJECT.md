# AutonomousApply — Multi-Platform Expansion

## What This Is

AutonomousApply (autonomousapply.com) is an AI-powered job application automation platform for developers seeking global remote work. It scrapes job listings from multiple platforms, uses AI to match them against the user's resume, and automatically applies with personalized cover letters — giving users the volume of 100s of applications with the quality of a targeted, tailored approach. The primary audience is developers in the Philippines and similar Asia-Pacific markets who face geographic restrictions on "remote" job boards and need to cast a wide net intelligently.

## Core Value

Apply to the right jobs at scale — high volume without noise, personalized cover letters so replies actually come back.

## Requirements

### Validated

- ✓ OnlineJobs.ph automation — Playwright scraper + AI matching + personalized cover letters — existing
- ✓ React/TypeScript dashboard with auth, application logs, settings — existing
- ✓ Resume upload and AI parsing via Supabase Edge Function — existing
- ✓ Supabase for auth + DB + real-time status — existing
- ✓ OpenAI for job matching and cover letter generation — existing
- ✓ PM2 backend scheduler (12-hour cycle) on Mac mini — existing

### Active

- [ ] Multi-platform automation — RemoteOK, WeWorkRemotely, Wellfound scrapers added to backend
- [ ] Country restriction detector — AI pre-filter that reads listing text and flags US-only/restricted jobs before applying
- [ ] Salary floor filter — user sets minimum salary; listings below it are skipped
- [ ] Timezone compatibility scoring — AI reads job timezone requirements and scores against UTC+8 (Cebu)
- [ ] Platform performance dashboard — per-platform stats (apps sent, response rate, active/paused status)
- [ ] Freemium model — applications/month limit on free tier; unlimited on paid
- [ ] Subscription/payment flow — wire up payment to unlock unlimited applications
- [ ] Arc.dev tracker — manual progress card for vetting pipeline stages (screening → coding → assessment → soft skills)
- [ ] Per-platform scheduling — RemoteOK checks every 2h (posts hourly), other platforms every 12h

### Out of Scope

- Cloud backend migration — Mac mini + PM2 is sufficient for this milestone; migrate when user count justifies it
- LinkedIn Easy Apply automation — high complexity (anti-bot measures, complex form flows); defer to next milestone
- Mobile app — web-first; mobile deferred until product-market fit confirmed
- Arc.dev automation — their vetting pipeline is human-reviewed; cannot automate, only track

## Context

**Existing codebase:**
- Frontend: `github.com/JivSTuban/job-automation-frontend` — React 18 + TypeScript + Vite, Tailwind CSS, Supabase client, deployed on Vercel
- Backend: `github.com/JivSTuban/job-automation-backend` — Node.js + Playwright + OpenAI, PM2 on Mac mini (local), runs every 12h
- Key tables: `automation_status`, `application_logs`, `resumes`, `user_credentials` (encrypted)
- Payment UI exists (`PaymentSuccess.tsx`, `PaymentCancel.tsx`) but payment logic is not yet wired up

**Research findings (June 2026):**
- "Remote ≠ Global" — even "worldwide" listings often have hidden US-only restrictions; country detection is high-value
- Pre-vetted talent pools (Arc.dev) have higher ROI than job board spray-and-pray, but can't be automated
- Salary transparency correlates with global-friendliness (Wellfound 82% disclosure rate, Remote100K explicit floors)
- Cebu UTC+8 overlaps US West Coast afternoons and European mornings — timezone fit is a real gate on many "remote" roles
- Best platforms for PH devs: Arc.dev → Wellfound → RemoteOK → WeWorkRemotely → Remote100K

**Target user:**
PH-based (or similar Asia-Pacific) developers, senior-level, seeking global remote roles. Frustrated that "remote" listings silently exclude their geography. Need volume to compensate for hit rate.

## Constraints

- **Tech Stack**: React/TypeScript/Vite frontend + Supabase + Node.js/Playwright backend — extend existing, don't rewrite
- **Backend Deployment**: Mac mini + PM2 for this milestone — no cloud migration, design features to work with long-running local process
- **AI Provider**: OpenAI (already integrated) — use for country detection, salary parsing, and cover letters
- **Revenue Gate**: Freemium model — free tier capped by applications/month; paid tier unlocks unlimited + premium platforms

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Freemium with applications/month as paywall | Natural usage limit users understand; upgrade motivation tied to automation value | — Pending |
| Keep Mac mini backend for this milestone | Cloud migration is a separate workstream; premature to block product features on infra work | — Pending |
| Volume + quality guardrails (not pure spam) | Higher reply rate = better user outcomes = better retention; spam applying would hurt the product's reputation | — Pending |
| Country restriction detector before applying | Saves wasted applications and protects sender reputation on platforms that rate-limit | — Pending |
| RemoteOK + WeWorkRemotely first, Wellfound second, LinkedIn last | Complexity order: low → medium → high; ship value fast, tackle harder platforms after | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-11 after initialization*
