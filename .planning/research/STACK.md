# Stack Research

**Project:** AutonomousApply — Multi-Platform Expansion Milestone
**Researched:** 2026-06-11
**Scope:** New capabilities only. Existing stack (React/Vite/Supabase/Playwright/OpenAI/PM2) is locked.

---

## Playwright Anti-Detection (2026)

### Current Landscape

The Node.js `playwright-extra` stealth plugin is **stale** — last released March 2023, no new evasion modules since. It patches `navigator.webdriver` and obvious fingerprint signals but cannot handle Cloudflare behavioral analysis or DataDome. For job boards like Wellfound that run DataDome, it will fail quickly.

The active replacement is **`rebrowser-patches`** / **`rebrowser-playwright`** — a drop-in replacement for `playwright-core` that patches at the Chrome DevTools Protocol level, modifies browser binary signatures, and adds fingerprint randomization. This is the 2026 standard for intermediate anti-bot bypass.

### Recommended Approach

**Layer 1 — rebrowser-playwright** (replaces `playwright-core`): Handles fingerprint and CDP-level detection. Install as `rebrowser-playwright` and `rebrowser-playwright-core`. It is a drop-in swap for the existing Playwright setup.

**Layer 2 — Request spacing**: Add randomized delays (1.5s–4s jitter) between page loads. A flat `page.goto()` loop is the most common detection signal. Use human-like navigation patterns (visit listing page → wait → open job → wait → close).

**Layer 3 — User-Agent rotation**: Rotate Chrome/Windows UA strings per session. Pair with matching `Accept-Language`, `Accept-Encoding`, and `sec-ch-ua` headers for consistency. Inconsistent headers are a red flag.

**Layer 4 — Per-platform scheduling**: RemoteOK is checked every 2h (aligns with their hourly post rate); WeWorkRemotely and Wellfound every 12h. Spreading runs reduces IP reputation damage.

### What It Does NOT Solve

Stealth does not fix IP reputation. The Mac mini runs from a residential IP which is an advantage — residential IPs pass most job board rate limit heuristics. Do not route through datacenter proxies. If a board starts blocking, add a 30-min cooldown before retry.

### Verdict

Use `rebrowser-playwright` as the drop-in core replacement. The existing Playwright code requires minimal changes — swap the import, add delay helpers, rotate UAs per session. This covers RemoteOK and WeWorkRemotely. Wellfound needs residential proxy backup (see Wellfound section).

---

## Stripe + Supabase Freemium Integration

### Recommended Pattern

The standard 2025/2026 pattern for Supabase + Stripe freemium is a **webhook-driven subscription sync**:

1. **Stripe Checkout** (not Billing Portal as entry point) — User clicks "Upgrade" → frontend calls your backend to create a `checkout.Session` → redirect to Stripe-hosted checkout page. Use `mode: 'subscription'` with a single monthly price.

2. **Stripe Billing Portal** — After subscription, user manages (cancel, update card) via the Billing Portal. Your backend creates a `billingPortal.Session` and redirects. This keeps PCI and subscription management fully off your stack.

3. **Webhook sync to Supabase** — Listen for `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`. On each event, upsert a `subscriptions` table in Supabase with `user_id`, `stripe_customer_id`, `status` (`active`/`canceled`/`past_due`), and `plan` (`free`/`pro`).

4. **Feature gating via Supabase column** — Add `applications_used_this_month` (integer) and `plan` (enum) to the `automation_status` or a new `user_plans` table. The backend checks this before each application run. Free tier cap: configurable constant (e.g., 25 apps/month).

5. **Payment UI already exists** — `PaymentSuccess.tsx` and `PaymentCancel.tsx` are present. Wire Stripe Checkout redirect to existing success/cancel routes. No new pages needed.

### Which Stripe Product

- **Stripe Checkout**: Use for the upgrade flow. Hosted, handles SCA/PSD2, supports Apple Pay and Google Pay automatically. No custom UI needed.
- **Stripe Billing Portal**: Use for subscription management. Do not build a custom cancel/update UI.
- **Stripe Webhooks**: The critical integration point. Run a webhook handler in the existing Node.js backend (a new Express route or PM2 worker). Verify signatures with `stripe.webhooks.constructEvent()`.

### Supabase Side

Add a Supabase Edge Function or a backend route (not frontend) for:
- `POST /stripe/create-checkout-session` — creates Checkout Session, returns URL
- `POST /stripe/webhook` — receives and processes Stripe events

Row Level Security does not need changes — gate at application logic level (check `plan` column before running automations), not at DB query level.

### Monthly Reset

Use a Supabase cron job (pg_cron, available in Supabase) or a PM2 scheduled task to reset `applications_used_this_month = 0` on the 1st of each month per user.

---

## RemoteOK Scraping

### API vs Scrape

**Use the public API. Do not scrape HTML.**

RemoteOK exposes an official public JSON API at `https://remoteok.com/api`. It requires no authentication, no API key. Returns an array of job objects with fields: `id`, `position`, `company`, `description`, `tags`, `salary`, `url`, `date`, `location`.

The API is monitored for reliability and shows near-100% uptime. Multiple production scrapers (Apify, Spider.cloud) use this endpoint directly — it is intentionally public.

### Rate Limits

No officially documented rate limit. The endpoint is designed for public consumption. Practical guidance from community: do not poll more than once every 5–10 minutes. The 2h schedule in the project plan is well within safe bounds.

### Quirks

- The first element in the returned JSON array is metadata (not a job). Skip index 0 when iterating.
- `salary` field is often null or a freeform string (e.g., "120k-160k"). Parse with regex or pass to GPT-4 mini for normalization.
- `location` is freeform ("Worldwide", "US only", "Americas"). Feed directly into the country restriction detector.
- No pagination — the API returns all recent listings in one call (typically 100–300 jobs).
- No Playwright needed for RemoteOK. Use `node-fetch` or `axios` — a plain HTTP GET is sufficient.

---

## WeWorkRemotely Scraping

### API vs Scrape

**Use the official READ API.**

WeWorkRemotely publishes a documented READ API at `https://weworkremotely.com/api`. It returns job listings in JSON format. The API terms explicitly permit read access for job listing data.

Endpoints include category-based listing feeds. No authentication required for read access, but the API terms prohibit attempting to circumvent rate limits via multiple applications.

### Rate Limits

WeWorkRemotely reserves the right to throttle or block excessive usage and returns HTTP 429 when a quota is exceeded. The API supports `ETag` and `Last-Modified` response headers — implement conditional requests with `If-None-Match` / `If-Modified-Since` to avoid re-fetching unchanged data and reduce request count.

The 12h schedule in the project plan is conservative and safe. Do not poll more frequently than hourly.

### Quirks

- Responses include `ETag` headers. Cache the last ETag per category and send `If-None-Match` on subsequent requests. A 304 Not Modified response means no new jobs — skip processing entirely.
- Job descriptions are HTML — strip tags before passing to GPT-4 for country restriction detection.
- Like RemoteOK, no Playwright needed. Use plain HTTP.

---

## Wellfound Scraping

### API Availability

Wellfound has **no public API**. They offer no official programmatic access to job listings.

### Scraping Complexity: HIGH

Wellfound is the hardest of the three new platforms:

- Protected by **DataDome** (behavioral analysis) and **Cloudflare** in combination.
- Powered by a **GraphQL API** internally — data is not in HTML, it is loaded via XHR calls to Apollo GraphQL endpoints. HTML scraping alone won't work.
- Requires **residential proxies** for reliable access. Datacenter IPs are blocked. The Mac mini's residential IP is an asset here, but if blocked, there is no easy fallback without a proxy service.
- Multiple third-party solutions (Apify actors, Bright Data) exist but at cost ($12+/mo per actor or API usage fees).

### Recommended Approach

Given the Mac mini residential IP advantage:

1. Use `rebrowser-playwright` with full stealth settings.
2. Target the GraphQL endpoint directly (inspect network traffic in DevTools to find the jobs query endpoint and required headers/cookies). This is more stable than HTML parsing — GraphQL responses are structured JSON.
3. Add 3–5 second delays between requests. Wellfound's DataDome monitors scroll velocity and click timing.
4. Do not run Wellfound on the same 12h cycle as other platforms — stagger it to offset from RemoteOK/WeWorkRemotely runs.

### Risk Assessment

If the residential IP gets flagged, Wellfound scraping will break with no easy fix short of a proxy service (~$50–100/mo for residential proxies). This is the most fragile integration. Build it with an `active/paused` toggle in the per-platform dashboard so it can be disabled without affecting other platforms.

The project plan already notes RemoteOK + WeWorkRemotely first, Wellfound second — this ordering is correct given complexity.

---

## AI Country Restriction Detection

### Approach

Use **OpenAI Structured Outputs** (`response_format: { type: "json_schema" }`) with GPT-4o-mini for cost efficiency. The classification call is short-input, low-latency, and does not need GPT-4-level reasoning.

### Recommended Prompt Pattern

```
system: |
  You are a job listing classifier. Your job is to determine whether a remote job listing
  is open to applicants in the Philippines (UTC+8, Asia-Pacific region).

  Classify the listing as one of three statuses:
  - "open": No geographic restrictions mentioned, or explicitly worldwide/global
  - "restricted": Explicitly requires US-based, US citizen, US work authorization,
    specific US states, or "Americas only" without including Asia
  - "unclear": Mentions timezone requirements, partial restrictions, or ambiguous language
    (e.g., "overlap with EST" — technically possible from Philippines but harder)

  Return JSON matching this schema exactly.

user: |
  Job Title: {title}
  Company: {company}
  Location field: {location}
  Description excerpt (first 500 chars): {description_excerpt}
```

### JSON Schema (Structured Output)

```json
{
  "name": "geo_classification",
  "schema": {
    "type": "object",
    "properties": {
      "status": { "type": "string", "enum": ["open", "restricted", "unclear"] },
      "reason": { "type": "string" },
      "timezone_flag": { "type": "boolean" }
    },
    "required": ["status", "reason", "timezone_flag"],
    "additionalProperties": false
  },
  "strict": true
}
```

`timezone_flag: true` means the listing mentions specific timezone overlap requirements — pass these to the timezone compatibility scorer as a separate signal rather than outright rejecting them.

### Signal Words to Include in Prompt (Few-Shot Examples)

Include 2–3 few-shot examples covering:
- "Must be authorized to work in the US" → `restricted`
- "Open to applicants worldwide" → `open`
- "Requires 4h overlap with PST" → `unclear`, `timezone_flag: true`

### Cost Estimate

GPT-4o-mini input: ~$0.15/1M tokens. A 500-char job excerpt is ~150 tokens. At 200 listings/run, 4 runs/day: ~120K tokens/day = ~$0.018/day. Negligible.

### Accuracy Notes

OpenAI Structured Outputs with `strict: true` guarantees valid JSON — no parsing errors. Classification accuracy for explicit restriction language is high (the signal phrases are unambiguous). Edge cases are "LATAM only", "must work EST hours" — the `unclear` bucket handles these gracefully for human review or timezone scoring.

---

## Confidence Levels

| Finding | Confidence | Basis |
|---------|------------|-------|
| Playwright anti-detection — rebrowser-patches as replacement | HIGH | GitHub repo confirmed active, multiple 2025-2026 blog posts corroborate |
| Playwright-extra Node.js stale | HIGH | Confirmed last release March 2023 by multiple sources |
| Stripe Checkout + Billing Portal pattern | HIGH | Official Supabase + Stripe docs, Vercel starter kits, multiple tutorials corroborate |
| Webhook-driven subscription sync | HIGH | Universal pattern across all 2025-2026 SaaS guides |
| RemoteOK public JSON API (no auth) | HIGH | Documented, tested daily by freepublicapis.com, used by multiple production scrapers |
| RemoteOK skip index 0 quirk | MEDIUM | Reported by Apify scraper docs, not in official RemoteOK docs |
| WeWorkRemotely official READ API | HIGH | Official API page at weworkremotely.com/api confirmed |
| WeWorkRemotely ETag caching | HIGH | Documented in their API terms |
| Wellfound DataDome + Cloudflare protection | HIGH | Corroborated by Scrapfly, Bright Data, multiple Apify actors all mention it |
| Wellfound GraphQL backend | MEDIUM | Reported by Scrapfly scraping guide, needs verification via DevTools inspection |
| Wellfound residential proxy requirement | MEDIUM | Inferred from multiple scrapers requiring it; Mac mini IP may bypass this |
| GPT-4o-mini for classification | HIGH | OpenAI Structured Outputs documented, `strict: true` guarantees schema compliance |
| Country restriction prompt pattern | MEDIUM | Pattern derived from prompt engineering best practices; specific accuracy against PH detection needs empirical testing in Phase implementation |

---

## Sources

- [Best Playwright Stealth 2026 — ScrapewisAI](https://scrapewise.ai/blogs/playwright-stealth-2026)
- [Playwright Anti-Bot Detection: What Works (2026) — AlterLab](https://alterlab.io/blog/playwright-anti-bot-detection-what-actually-works-in-2026)
- [Playwright Stealth: What Works in 2026 — DiCloak](https://dicloak.com/blog-detail/playwright-stealth-what-works-in-2026-and-where-it-falls-short)
- [rebrowser-patches — GitHub](https://github.com/rebrowser/rebrowser-patches)
- [Playwright Stealth — Scrapfly](https://scrapfly.io/blog/posts/playwright-stealth-bypass-bot-detection)
- [Stripe + Supabase SaaS Starter Kit — Vercel](https://vercel.com/templates/next.js/stripe-supabase-saas-starter-kit)
- [Building a Next.js SaaS Starter with Supabase & Stripe — BrightCoding](https://www.blog.brightcoding.dev/2025/08/19/building-a-next-js-saas-starter-with-supabase-stripe/)
- [Supabase vs Stripe (2026) SaaS Stack — BuildMVPFast](https://www.buildmvpfast.com/compare/supabase-vs-stripe)
- [RemoteOK Jobs API — FreePublicAPIs](https://www.freepublicapis.com/remote-ok-jobs-api)
- [We Work Remotely READ API](https://weworkremotely.com/api)
- [We Work Remotely API Terms](https://weworkremotely.com/api-terms-and-guidelines)
- [How to Scrape Wellfound — Scrapfly](https://scrapfly.io/blog/posts/how-to-scrape-wellfound-aka-angellist)
- [Wellfound Scraper — Bright Data](https://brightdata.com/products/web-scraper/angellist)
- [OpenAI Structured Outputs Guide](https://platform.openai.com/docs/guides/structured-outputs)
