# Architecture Research

**Project:** AutonomousApply — Multi-Platform Expansion
**Researched:** 2026-06-11
**Confidence:** HIGH (patterns well-established; Supabase schema is project-specific inference)

---

## Multi-Platform Scraper Structure

**Recommendation: Adapter pattern with a shared PlatformRunner contract.**

Each platform is an adapter module that satisfies a common interface. The orchestrator (`runner.js`) imports all adapters and calls them uniformly.

```
backend/
  platforms/
    base/
      platform-interface.js   ← defines the contract (JSDoc or TypeScript interface)
      pipeline.js             ← shared pre-filter + apply pipeline
    onlinejobs/
      scraper.js              ← existing code, wrapped to satisfy interface
      config.js               ← interval, base URL, selectors
    remoteok/
      scraper.js
      config.js
    weworkremotely/
      scraper.js
      config.js
    wellfound/
      scraper.js
      config.js
  runner.js                   ← orchestrator, imports platform registry
  scheduler.js                ← PM2-managed, per-platform intervals
```

**Platform interface contract (every adapter must export):**

```js
module.exports = {
  name: 'remoteok',           // matches platform column in DB
  fetchListings(options),     // returns raw listings array
  parseJob(rawListing),       // normalizes to shared Job shape
  applyToJob(job, userCtx),   // performs application, returns result
};
```

The `pipeline.js` sits between `fetchListings` and `applyToJob` — it calls pre-filters and quota checks before any application is attempted. This keeps business logic out of individual scrapers.

**Migration path for OnlineJobs.ph:** Wrap the existing script inside the `onlinejobs/scraper.js` adapter. No logic changes needed — only extract config constants to `config.js` and export the three interface methods. Run it through the shared pipeline on the next pass.

---

## Pre-Filter Pipeline Design

**Run filters on the parsed job summary, before fetching the full listing page, where possible. Run AI-based filters before calling `applyToJob`.**

Two-stage design:

**Stage 1 — Cheap filters (no AI, no extra HTTP)** — run immediately after `parseJob()` on the listing preview data:
- Salary floor: compare `job.salaryMin` against user's `min_salary` preference. Most platforms expose salary in the listing card. Skip if below floor — zero cost.
- Keyword blocklist: title/snippet contains "US only", "must be located in", etc. String match, no AI needed.

**Stage 2 — AI filters (one OpenAI call per job that passes Stage 1)** — run before `applyToJob()`:
- Country restriction detector: send job description to GPT with a prompt asking for `{ restricted: bool, reason: string }`. Cache result in `application_logs` so a re-run doesn't re-query.
- Timezone scoring: same call or a chained prompt. Return a 0–1 UTC+8 compatibility score. Configurable threshold in user settings (e.g., skip if score < 0.4).

**Why not fetch full listing first?** Fetching the full page costs an HTTP request and Playwright render time per job. Stage 1 catches ~30–50% of disqualified listings for free. Stage 2 catches most of the rest before any form interaction happens. Playwright only runs for jobs that clear both filters.

**Pipeline execution order:**

```
fetchListings()
  → parseJob() [normalize shape]
    → Stage 1 filters [salary, keyword blocklist]
      → Stage 2 AI filters [country, timezone]
        → quotaCheck() [see below]
          → applyToJob()
            → log result to application_logs
```

---

## Quota Enforcement Pattern

**Enforce in application code (pipeline.js), with the source of truth in the DB. Do not rely on DB-level constraints alone.**

Rationale: DB constraints (CHECK, triggers) are a safety net but not the right UX layer — they throw errors rather than returning meaningful responses. RLS policies can enforce isolation but are blunt for counting quotas. Application code reads the count, compares against the plan limit, and returns a structured `{ allowed: bool, reason: string }` before any scraping work happens.

**Implementation:**

1. Add `user_plans` table (see Schema section) with `applications_per_month` limit per plan tier.
2. Add `user_subscriptions` table linking users to plans with `current_period_start`.
3. At the start of each user's run cycle, `pipeline.js` queries:
   ```sql
   SELECT COUNT(*) FROM application_logs
   WHERE user_id = $1
     AND applied_at >= date_trunc('month', now());
   ```
4. Compare against `user_plans.applications_per_month`. If at limit, skip all `applyToJob` calls for this user and write a `quota_reached` event to `application_logs` (so the dashboard can surface it).
5. For multi-user: run this check per-user inside the platform loop, not once globally. Each user has independent quota.

**Do NOT** enforce quota inside individual platform adapters — it belongs in `pipeline.js` so the check runs identically across all platforms with no duplication.

**DB constraint as a safety net only:** Add a Postgres `BEFORE INSERT` trigger on `application_logs` that raises an error if the monthly count exceeds the plan limit. This prevents runaway bugs from double-applying but is not the primary enforcement path.

---

## PM2 Multi-Interval Scheduling

**Use a single PM2-managed entry point (`scheduler.js`) with `node-cron` internally. Do not create one PM2 process per platform.**

Multiple PM2 processes for the same codebase create deployment and logging complexity. One scheduler process owns all cron slots:

```js
// scheduler.js
const cron = require('node-cron');
const { runPlatform } = require('./runner');

// RemoteOK: every 2 hours
cron.schedule('0 */2 * * *', () => runPlatform('remoteok'));

// All others: every 12 hours
cron.schedule('0 */12 * * *', () => runPlatform('onlinejobs'));
cron.schedule('0 */12 * * *', () => runPlatform('weworkremotely'));
cron.schedule('0 */12 * * *', () => runPlatform('wellfound'));
```

PM2 ecosystem file:

```js
// ecosystem.config.js
module.exports = {
  apps: [{
    name: 'jobi-scheduler',
    script: './scheduler.js',
    instances: 1,          // critical: always 1, never cluster mode
    autorestart: true,
    watch: false,
    env: { NODE_ENV: 'production' }
  }]
};
```

**Why `instances: 1`?** PM2 cluster mode spawns multiple Node processes. With multiple instances, `node-cron` fires once per instance, causing duplicate runs. Single instance avoids this entirely without needing Redis or a lock table.

**Staggering:** Offset the 12h platforms by 30–60 minutes to avoid simultaneous Playwright sessions hammering the Mac mini:
```
onlinejobs:      0 0,12 * * *
weworkremotely:  0 1,13 * * *
wellfound:       0 2,14 * * *
remoteok:        0 */2 * * *
```

---

## Supabase Schema Extensions

### New tables

**`user_plans`** — plan definitions (static reference table):
```sql
CREATE TABLE user_plans (
  id                     text PRIMARY KEY,  -- 'free', 'pro'
  name                   text NOT NULL,
  applications_per_month integer NOT NULL,  -- 50 for free, 9999 for pro
  platforms_allowed      text[] NOT NULL,   -- ['onlinejobs','remoteok'] for free
  created_at             timestamptz DEFAULT now()
);
```

**`user_subscriptions`** — one row per user, their current plan:
```sql
CREATE TABLE user_subscriptions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid REFERENCES auth.users NOT NULL UNIQUE,
  plan_id              text REFERENCES user_plans NOT NULL DEFAULT 'free',
  current_period_start timestamptz NOT NULL DEFAULT date_trunc('month', now()),
  current_period_end   timestamptz,
  stripe_customer_id   text,
  stripe_subscription_id text,
  created_at           timestamptz DEFAULT now(),
  updated_at           timestamptz DEFAULT now()
);
```

**`platform_stats`** — per-user, per-platform aggregate (for the dashboard):
```sql
CREATE TABLE platform_stats (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid REFERENCES auth.users NOT NULL,
  platform        text NOT NULL,          -- 'remoteok', 'wellfound', etc.
  period_start    date NOT NULL,          -- monthly bucketing
  apps_sent       integer DEFAULT 0,
  responses       integer DEFAULT 0,
  last_run_at     timestamptz,
  status          text DEFAULT 'active',  -- 'active' | 'paused' | 'error'
  UNIQUE (user_id, platform, period_start)
);
```

### Columns to add to existing tables

**`application_logs`** — add:
- `platform text NOT NULL DEFAULT 'onlinejobs'` — which platform this log row came from
- `filter_stage text` — `'salary'|'keyword'|'country'|'timezone'|'quota'|'applied'` — where in the pipeline the job was handled
- `ai_filter_result jsonb` — store `{ restricted, timezone_score, reason }` to avoid re-querying OpenAI on re-runs
- `user_id uuid REFERENCES auth.users` — needed for multi-user; currently single-user so may already exist implicitly

**`automation_status`** — add:
- `platform text NOT NULL DEFAULT 'onlinejobs'` — one row per user+platform combination
- `user_id uuid REFERENCES auth.users` — for multi-user

**`user_credentials`** — add:
- `platform text NOT NULL DEFAULT 'onlinejobs'` — credentials are per-platform (each site has its own login)
- Composite unique constraint: `UNIQUE(user_id, platform)`

### RLS policies

Enable RLS on all new tables. Standard ownership pattern:
```sql
CREATE POLICY "users see own data" ON platform_stats
  FOR ALL USING (user_id = auth.uid());
```
Apply the same pattern to `user_subscriptions` and `application_logs`. `user_plans` is a public reference table — no RLS, read-only.

---

## Build Order Implications

**Dependencies determine order — do not parallelize these:**

1. **Schema migration first.** Add `platform`, `user_id`, and `filter_stage` columns to existing tables; create `user_plans`, `user_subscriptions`, `platform_stats`. Back-fill existing rows with `platform = 'onlinejobs'`. Everything else depends on this.

2. **Platform interface + pipeline.js second.** Define the adapter contract and shared pipeline before writing any new scraper. Wrap the existing OnlineJobs script into the adapter shape — this validates the interface without new platform risk.

3. **One new platform scraper (RemoteOK).** RemoteOK has a public JSON API (`remoteok.com/api`) in addition to HTML — lowest scraping complexity, no login required. Ship and verify end-to-end flow through the pipeline.

4. **Pre-filter pipeline.** Once RemoteOK is running, add Stage 1 (salary/keyword) and Stage 2 (AI country/timezone) filters. Stage 2 introduces OpenAI cost per-job — validate filtering accuracy before expanding to other platforms.

5. **Quota enforcement.** Add `user_subscriptions`, populate with free-tier defaults for existing users, wire `quotaCheck()` into pipeline. Gate RemoteOK and existing OnlineJobs behind quota before adding more platforms.

6. **WeWorkRemotely + Wellfound scrapers.** With the pipeline, quota, and scheduling infrastructure proven, these are adapter implementations only — no new architectural work.

7. **PM2 scheduler refactor.** Replace the current fixed 12h PM2 cron with `scheduler.js` + `node-cron`. Do this before launching the 2h RemoteOK schedule to avoid dual-scheduling the existing job.

8. **platform_stats aggregation.** Can run as a Supabase Edge Function triggered after each `application_logs` INSERT, or as a nightly aggregate query. Non-blocking — build after core flows are stable.

---

## Sources

- [Designing Plugin-Based Architecture in Node.js](https://www.cmarix.com/qanda/nodejs-plugin-architecture/)
- [Plugin architecture in JavaScript and Node.js — Adaltas](https://www.adaltas.com/en/2020/08/28/node-js-plugin-architecture/)
- [Setting Cron Jobs with PM2](https://greenydev.com/blog/pm2-cron-job-multiple-instances/)
- [Architecture Patterns for SaaS Platforms — Appfoster/Medium](https://medium.com/appfoster/architecture-patterns-for-saas-platforms-billing-rbac-and-onboarding-964ea071f571)
- [Supabase RLS Best Practices — Makerkit](https://makerkit.dev/blog/tutorials/supabase-rls-best-practices)
- [Enforcing RLS in Supabase Multi-Tenant Architecture — DEV Community](https://dev.to/blackie360/-enforcing-row-level-security-in-supabase-a-deep-dive-into-lockins-multi-tenant-architecture-4hd2)
