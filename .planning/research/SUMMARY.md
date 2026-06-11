# Project Research Summary

**Project:** AutonomousApply — Multi-Platform Expansion Milestone
**Domain:** Job application automation SaaS for APAC developers seeking global remote work
**Researched:** 2026-06-11
**Confidence:** HIGH

---

## Recommended Stack Additions

- **rebrowser-playwright** (replaces `playwright-core`): Drop-in Playwright replacement patching at the CDP level. `playwright-extra` stealth is stale (last release March 2023) and actively detected by Cloudflare in 2026.
- **node-fetch / axios** (RemoteOK + WeWorkRemotely listing fetch): Both platforms have official public APIs — no Playwright needed, eliminating anti-bot risk for listing retrieval entirely.
- **Stripe Checkout + Billing Portal** (not custom UI): Handles SCA/PSD2/Apple Pay. No custom subscription UI to build.
- **stripe npm package** (server-side only): Webhook verification, Checkout/Billing Portal session creation.
- **node-cron** (single PM2 process): Replaces multiple PM2 cron processes. `instances: 1` prevents duplicate cron firing.
- **pg_cron** (Supabase built-in): Monthly `applications_used` reset — no extra service.
- **GPT-4o-mini with Structured Outputs** (`strict: true`): Country restriction + timezone scoring. ~$0.018/day at expected volume.
- **disposable-email-blocklist npm package**: Block throwaway emails at signup with minimal friction.

---

## Table Stakes Features

- Application log / history with per-job detail view
- Salary floor filter (74% of candidates cite it as #1 filter criterion)
- Application status tracking (Applied / Viewed / Responded / Rejected)
- Pause / resume per platform (required to independently disable Wellfound if it breaks)
- Cover letter preview per application (differentiates from LazyApply complaints)
- Monthly quota counter visible in dashboard
- Experience level filter

---

## Top Differentiator

**Country restriction detection before applying.** No competitor solves the "remote = US only" problem for APAC developers. GPT-4o-mini classifies each listing as `open / restricted / unclear` before spending a credit or submitting a form. This is the defensible moat — it saves PH developers from wasting applications on jobs they legally cannot take.

---

## Architecture in One Paragraph

Each platform is an adapter module satisfying `{ name, fetchListings, parseJob, applyToJob }`. A shared `pipeline.js` runs Stage 1 cheap filters (salary floor, keyword blocklist) on normalized previews at zero AI cost, then Stage 2 GPT-4o-mini filters (country restriction + timezone score) on jobs that pass Stage 1, then `quotaCheck()` against `user_subscriptions` before any form interaction. Playwright (rebrowser) fires only for `applyToJob` — RemoteOK and WeWorkRemotely listings are fetched via HTTP-only. A single PM2 process runs `scheduler.js` with `node-cron` (RemoteOK every 2h, others staggered at 12h offsets, `instances: 1`). Stripe webhooks sync to `user_subscriptions`; the dashboard reads `platform_stats` aggregated from `application_logs`.

---

## Critical Pitfalls (Top 5)

1. **Plaintext credential storage** (CRITICAL — before adding any new platform): AES-256-GCM encrypt `user_credentials` with key in backend `.env` only. Frontend RLS must deny all reads.
2. **Stripe webhook race condition on success page** (CRITICAL): User pays → redirected → webhook not yet delivered → Supabase still shows `free`. Fix: call Stripe API directly from success page handler to sync subscription synchronously; use webhooks as eventual-consistency backup.
3. **Stripe webhook idempotency** (CRITICAL): Store processed `event.id` in a `stripe_events` table; reject duplicates. Use `express.raw()` on the webhook route — `express.json()` breaks signature verification.
4. **Cross-platform job deduplication** (HIGH): Same job appears on multiple boards simultaneously. Compute SHA-256 fingerprint from `normalize(company) + normalize(title) + iso_week(posted_date)`; check `application_logs` within 30 days before any submission.
5. **Playwright memory leak** (HIGH): Wrap every browser/context in `try/finally` with explicit `.close()`. Without it, 12h processes grow to 1GB+ and macOS kills silently. Set `max_memory_restart: '800M'` in PM2 config.

---

## Build Order

1. **Phase 0 — Infrastructure audit**: Encrypt credentials. `pm2 startup`. `caffeinate`. Schema migration: add `platform`, `user_id`, `filter_stage`, `ai_filter_result` to `application_logs`; create `user_plans`, `user_subscriptions`, `platform_stats`; back-fill existing rows.
2. **Phase 1 — Adapter interface + pipeline**: Define contract, wrap OnlineJobs into adapter to validate without new risk. Replace PM2 cron with `scheduler.js` + `node-cron`.
3. **Phase 2 — RemoteOK + AI filters**: Public JSON API, no auth, no Playwright for listing fetch. Ship end-to-end through pipeline. Validate GPT-4o-mini classification accuracy on real listings before expanding.
4. **Phase 3 — Freemium billing**: Stripe Checkout + webhook + `user_subscriptions` sync. Wire `quotaCheck()` into pipeline. Upgrade prompt at 80% of cap.
5. **Phase 4 — WeWorkRemotely**: Official READ API + ETag caching. Adapter-only work.
6. **Phase 5 — Wellfound**: Highest complexity (DataDome + Cloudflare + GraphQL via XHR). Build `active/paused` toggle first. Build last.
7. **Phase 6 — Dashboard + analytics**: `platform_stats` aggregation, per-platform response rate charts, blurred upgrade teasers, cover letter preview, "jobs skipped as US-only" counter.

---

## Watch Out For

1. **Wellfound is fragile by design.** No public API, DataDome + Cloudflare, internal GraphQL endpoint must be discovered via DevTools at implementation time. Build the `active/paused` toggle before writing a single line of Wellfound scraping code.
2. **Quota enforcement race condition.** Concurrent sessions can exceed quota if `quotaCheck()` and INSERT are separate calls. Use atomic `UPDATE ... WHERE applications_used < quota RETURNING id` or a Postgres row-level lock.
3. **Free cap placement determines conversion.** 25 apps/month is the right pressure point — active job seekers hit it in 1–2 days and have clear motivation to upgrade.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | RemoteOK + WeWorkRemotely APIs confirmed public; rebrowser-playwright confirmed active 2026 |
| Features | MEDIUM-HIGH | Competitor analysis solid; conversion benchmarks from aggregated SaaS data |
| Architecture | HIGH | Adapter + pipeline are established patterns; schema is logically sound |
| Pitfalls | HIGH | Cross-referenced from multiple production scraping and billing sources |

**Gaps to resolve during execution:**
- Wellfound GraphQL endpoint: identify via DevTools at implementation time
- GPT-4o-mini PH edge case accuracy: tune against real listing data in Phase 2
- Pro tier pricing ($19–$29/mo): validate with early users before locking in
