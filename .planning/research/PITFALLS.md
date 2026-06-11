# Pitfalls Research

**Domain:** Job automation SaaS — multi-platform scraping + AI cover letters + freemium billing
**Researched:** 2026-06-11
**Overall confidence:** HIGH (cross-referenced multiple production sources)

---

## Anti-Bot Detection & Evasion

### What breaks in production vs dev

In dev, a plain `playwright.chromium.launch({ headless: true })` request works fine because you are running once, slowly, from a residential IP. In production, you run on a schedule, repeatedly, from the same IP, with the same browser fingerprint — and that pattern triggers detection within days.

**RemoteOK** — Uses Cloudflare. The JS detection engine (`navigator.webdriver = true`) blocks vanilla Playwright immediately. Cloudflare's ML engine detects headless browser cipher suites, HTTP/2 header ordering, and TLS fingerprints that do not match real Chrome. Rate limits are aggressive for repeated crawls from a single IP.

**WeWorkRemotely** — Cloudflare-protected as well. Basic scrapers frequently return 403 or 504. The site is considered one of the harder targets; community scrapers routinely break and get marked deprecated.

**Wellfound** — Actively hostile to scraping. Described as "notorious for blocking all web scrapers." Uses a combination of Cloudflare and custom bot detection. Login-gated content (most startup jobs) requires session handling, making detection surface larger.

### Detection vectors in order of danger

1. `navigator.webdriver` flag set to `true` in headless Playwright — trivially detected
2. TLS/HTTP fingerprint mismatch (cipher suite, extension order) — detected at the TCP layer before JS runs
3. Static IP with high request frequency — rate limited within hours
4. Identical browser profile (same user-agent, same viewport, same timezone) across all runs
5. No mouse movement / scroll simulation between actions
6. `puppeteer-stealth` — deprecated February 2025; Cloudflare now detects it

### Prevention

- Use `playwright-extra` with a maintained stealth plugin or switch to Camoufox/Nodriver for Cloudflare-protected targets
- Set random delays between requests (1–3 seconds minimum; 3–7 seconds for sensitive targets)
- Rotate user-agents and realistic browser profiles (OS, screen resolution, timezone matching UTC+8)
- Use residential proxy rotation for production runs — datacenter IPs are nearly always flagged
- Prefer official RSS feeds where available: RemoteOK provides `remoteok.com/remote-jobs.json` (JSON API, no JS rendering needed, much harder to block); WeWorkRemotely has `weworkremotely.com/remote-jobs.rss`
- Fetch RSS/JSON before falling back to browser automation — eliminates the detection problem entirely for listing pages
- Browser automation should only be used for the application submission step, not for scraping listings

### Warning signs

- Sudden drop in scraped job count with no change in code
- HTTP 403/429/503 responses mixed into previously working requests
- Scraper returns empty results but no error (silent block via redirect to CAPTCHA page)
- Jobs that should exist are missing (Cloudflare served a challenge page that Playwright silently accepted as the content)

---

## AI Cover Letter Quality Degradation

### When it fails

The problem is not AI detection per se — it is genericness. 61% of hiring managers (Indeed 2026 survey) spend under 30 seconds on obviously AI-generated letters vs 2–3 minutes on authentic-sounding ones. The issue activates at low volume if the letters are formulaic.

**Volume threshold:** There is no safe volume number. A single generic letter is worse than 50 well-personalized ones. The failure mode is the template, not the count.

**Content patterns that get filtered:**
- Opening with "I am excited to apply for the [role] position at [company]..."
- Generic capability claims ("I am a results-driven developer with 5+ years...")
- No mention of the specific company product, funding stage, or tech stack
- Same cover letter structure for every application (detectable by the user's own response patterns over time)
- Failure to acknowledge geographic situation — for PH-based applicants, many managers notice when a letter doesn't address timezone/remote setup

**AI detection tools:** 65% of Fortune 500 companies use AI detection. Enterprise tools claim 96–99% accuracy on obvious AI content. However, well-prompted, personalized output scores poorly on detectors because it diverges from the statistical baseline.

### Prevention

- Inject company-specific data into the prompt: company name, product description, tech stack from the listing, funding stage if visible on Wellfound
- Inject user-specific data beyond the resume: specific projects, concrete metrics, the user's timezone and availability hours
- Add a system prompt instruction to vary sentence structure and avoid known AI phrasing patterns
- Set a temperature of 0.7–0.9 (not 0 or 1.0) for cover letter generation
- For the PH use case specifically: include a sentence acknowledging UTC+8 overlap with US West Coast afternoons — this is a differentiator, not a liability, and signals the letter was actually written for this context
- Monitor response rate per prompt version; treat it as an A/B test; replace templates showing zero replies after 30+ applications

---

## Stripe + Supabase Billing Gotchas

### Race condition: checkout → redirect → stale quota check

This is the most common production bug. Flow: user pays → Stripe redirects to success page → frontend immediately checks subscription status → Supabase still shows `free` because the webhook hasn't arrived yet (webhooks are async, arrive 1–5 seconds after redirect). Result: user sees a "you're still on free tier" error immediately after paying.

**Fix:** On the success page redirect, call Stripe's API directly to fetch the subscription status, update Supabase synchronously from that response, then render the success state. Do not rely on webhooks for the success page. Use webhooks only as the eventual-consistency safety net.

### Duplicate webhook delivery

Stripe delivers webhooks at least once and sometimes more than once. If your handler is not idempotent, a user can be upgraded twice or have their quota reset twice. Store every processed `event.id` in a `stripe_events` table; reject events whose ID already exists.

### Quota enforcement race condition

If the backend checks `applications_used < quota` and then inserts the application in two separate DB calls without a transaction, a user running two concurrent browser sessions can exceed their quota by the number of concurrent requests. Fix with either a Postgres row-level lock or a single atomic `UPDATE ... WHERE applications_used < quota RETURNING id` — only proceed if a row was returned.

### Subscription state drift

If a user cancels via Stripe dashboard, changes payment method, or their card is declined, Stripe fires webhooks but your Supabase `subscriptions` table may not update if the webhook handler errors silently. Required webhooks to handle: `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `invoice.payment_succeeded`. Log all webhook receipt and processing to a table; alert on processing failures.

### Webhook signature verification

Always verify `stripe.webhooks.constructEvent(body, sig, secret)` using the raw request body (not parsed JSON). Express's `json()` middleware transforms the body before it reaches the handler, breaking signature verification. Use `express.raw({ type: 'application/json' })` for the webhook route only.

---

## Cross-Platform Job Deduplication

### The problem

The same job posting routinely appears on RemoteOK, WeWorkRemotely, and Wellfound simultaneously — especially for funded startups that pay to post on multiple boards. Applying to the same job twice from the same user is a hard failure mode: it signals a bot and may get the user's account flagged or the application rejected outright.

### Why simple approaches fail

- Platform-specific job IDs are useless across platforms (each board assigns its own ID)
- URL comparison fails because the same job has different URLs on each board
- Exact title match fails because titles are slightly reformatted ("Senior Backend Engineer" vs "Senior Backend Engineer (Remote)")

### Standard solution: composite fingerprint

Compute a fingerprint from: `company_name_normalized + role_title_normalized + date_posted_week`. Normalize by lowercasing, removing punctuation, and collapsing whitespace. A job is a duplicate if the fingerprint matches a job applied to within the past 30 days.

**Implementation:**
```
fingerprint = sha256(
  normalize(company_name) +
  normalize(title) +
  iso_week(posted_date)   // week-level granularity tolerates small date differences
)
```

Store fingerprints in the `application_logs` table. Before submitting any application, check `SELECT 1 FROM application_logs WHERE fingerprint = $1 AND user_id = $2 AND created_at > NOW() - INTERVAL '30 days'`.

**Edge case:** The same company posts the same role again after a month (legitimate re-post). The 30-day window handles this.

---

## Credential Storage Security

### The risk

The `user_credentials` table (already exists in the schema) stores job platform login credentials for automation. This is the highest-risk surface in the entire product. If the Supabase instance is misconfigured, the RLS policies are wrong, or a service-role key leaks, all user credentials are exposed in plaintext.

### Standard safe approach

**Never store plaintext passwords.** The minimum viable secure approach:

1. Encrypt with AES-256-GCM before writing to the database. The encryption key must NOT be stored in Supabase — store it in an environment variable on the Mac mini backend only.
2. Use per-user encryption keys derived from a master key + user ID (key derivation with HKDF or PBKDF2), so a single leaked key does not expose all users.
3. The Supabase `user_credentials` table should be inaccessible to the frontend entirely — row-level security should deny all frontend reads. Only the backend (using the service role key) decrypts and uses credentials.
4. Never log credentials, never include them in error messages, never return them in API responses.

**Better approach (if complexity is justified):** Replace stored credentials with OAuth tokens where the platform supports it. Wellfound has OAuth; prefer that over password storage. For platforms without OAuth (OnlineJobs.ph), encrypted storage is unavoidable.

**Audit checklist:**
- Supabase RLS on `user_credentials`: frontend users can only read/write their own row
- Backend never sends credential data to the frontend (not even masked)
- Encryption key is in `.env`, not in the codebase or Supabase secrets (Supabase secrets are accessible to Edge Functions, which is a wider surface than needed)

---

## PM2 + Playwright Production Issues

### Memory accumulation

A Playwright browser context that is not explicitly closed after use leaks memory. With a 12-hour scheduler running multiple scrapers and application flows, a process that starts at 200MB reaches 1GB+ in under a day. macOS will eventually kill the process via memory pressure without PM2 noticing.

**Fix:** Every browser context and browser instance must be wrapped in try/finally with explicit `context.close()` and `browser.close()` calls. Never rely on garbage collection.

```js
const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  try {
    // work
  } finally {
    await context.close();
  }
} finally {
  await browser.close();
}
```

Set `max_memory_restart: '800M'` in the PM2 config as a safety net — PM2 will restart the process if it exceeds this threshold rather than letting it grow unbounded.

### Mac mini–specific issues

- **Sleep/wake cycles:** macOS defaults to sleep after inactivity. PM2 processes survive sleep but scheduled tasks (cron-based triggers) can fire at unexpected times if the machine was asleep during the scheduled window. Use `caffeinate -i` or configure Energy Saver to disable sleep while plugged in.
- **No automatic restart on machine reboot:** PM2's `pm2 startup` must be run to register the process manager as a launch daemon. Without it, a power cycle or forced restart loses all running processes.
- **Time zone drift on scheduler:** The Mac mini's local timezone affects cron expressions in PM2. Set the `TZ` environment variable explicitly in the PM2 ecosystem config.

### Orphaned browser processes

If Playwright crashes mid-run without the finally block executing, Chromium processes are left running. Over days, dozens of zombie Chrome processes accumulate, consuming CPU and ports. Add a startup cleanup step that kills any running Chromium processes before launching a new cycle.

### Crash loops

If a scraper throws an unhandled error, PM2 restarts it immediately. If the error is persistent (e.g., a job board changed its HTML structure), the process enters a restart loop. Set `max_restarts: 5` and `min_uptime: '10s'` to prevent infinite loops.

---

## Freemium Abuse Prevention

### Common circumvention patterns

1. **Multiple email accounts** — create a new Gmail/Yahoo account when the monthly limit is hit. Cost: 2 minutes.
2. **Disposable email addresses** — services like Mailinator, TempMail provide infinite fresh emails.
3. **Sharing accounts** — multiple users sharing one paid account credential.
4. **Browser storage manipulation** — if the quota is tracked client-side (localStorage or a cookie), users can simply clear it.

### The structural fix

**Enforce quota server-side only.** The quota check must happen in the backend before each application is submitted — never trust a frontend-reported count. The `application_logs` table already exists; count rows per user per billing period there.

### Identity signal strengthening

For the free tier (PH developer audience), an aggressive verification wall is counterproductive — it adds friction before users see value. The pragmatic approach:

1. **Block disposable email domains** at signup — use a maintained blocklist (e.g., the `disposable-email-blocklist` npm package). This eliminates the lowest-effort abuse with minimal impact on legitimate users.
2. **IP-based account linking** — track IP at signup; flag accounts created from the same IP within a short window. Do not block, but flag for review.
3. **Design the free tier to convert, not just limit** — a limit of 10 applications/month is low enough that real users feel the constraint and upgrade; it is also low enough that abusers get minimal value from spinning up fake accounts.
4. **Quota resets on a fixed calendar date, not rolling 30 days** — prevents the edge case where a user creates an account on the 29th, uses 10 applications, then "resets" in one day.

### What not to do

Do not require phone number verification for the PH market — SMS verification services that bypass it are cheap and widely used. Phone verification adds friction for real users without stopping determined abusers.

---

## Phase Mapping

| Pitfall | Phase to Address | Priority |
|---------|-----------------|----------|
| Anti-bot detection — RSS/JSON API preference | Phase 1: Scraper implementation | Critical — design scrapers correctly from the start |
| Anti-bot detection — stealth Playwright | Phase 1: Scraper implementation | High — required for Wellfound application submission |
| AI cover letter genericness | Phase 1: Cover letter prompt | High — affects core value proposition immediately |
| AI volume/quality monitoring | Phase 2+: Analytics | Medium — add prompt versioning and reply-rate tracking |
| Stripe webhook idempotency + signature | Phase: Billing implementation | Critical — implement correctly on day one |
| Stripe/Supabase race condition on success page | Phase: Billing implementation | High — visible user-facing bug |
| Quota enforcement race condition | Phase: Billing implementation | High — financial integrity |
| Subscription state drift | Phase: Billing implementation | Medium — handle all relevant webhook event types |
| Job deduplication fingerprinting | Phase 1: Scraper implementation | High — multi-platform adds this immediately |
| Credential encryption at rest | Existing / Phase 0 | Critical — audit `user_credentials` table before adding more platforms |
| Playwright memory leak (try/finally) | Phase 1: Scraper implementation | High — production stability |
| PM2 startup on reboot | Phase 0: Infrastructure audit | Medium — one-time setup |
| Mac mini sleep prevention | Phase 0: Infrastructure audit | Medium — one-time setup |
| Freemium server-side enforcement | Phase: Billing implementation | Critical — enforce in backend, not frontend |
| Disposable email blocking | Phase: Billing implementation | Medium — implement at signup |

---

## Sources

- [How to Bypass Cloudflare When Web Scraping in 2026 — Scrapfly](https://scrapfly.io/blog/posts/how-to-bypass-cloudflare-anti-scraping)
- [Playwright Anti-Bot Detection: What Works (2026) — AlterLab](https://alterlab.io/blog/playwright-bot-detection-what-actually-works-in-2026)
- [How to Scrape Wellfound — Scrapfly](https://scrapfly.io/blog/posts/how-to-scrape-wellfound-aka-angellist)
- [Cloudflare bot detection engines — Cloudflare Docs](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)
- [Are AI Cover Letters Detectable? 850+ Recruiters — Cover Letter Copilot](https://coverlettercopilot.ai/blog/are-ai-cover-letters-detectable-by-recruiters)
- [AI Cover Letter Checker — Pangram Labs](https://www.pangram.com/blog/ai-cover-letter-checker)
- [Billing webhook race condition solution guide — Steven Yung](https://excessivecoding.com/blog/billing-webhook-race-condition-solution-guide)
- [How I wired Stripe subscriptions to Supabase — DEV Community](https://dev.to/jonathan_diniz_cee738f10e/how-i-wired-stripe-subscriptions-to-supabase-in-nextjs-15-the-parts-tutorials-skip-2b9l)
- [Handling Stripe Webhooks — Supabase Docs](https://supabase.com/docs/guides/functions/examples/stripe-webhooks)
- [Inside JobsPikr's Data Pipeline — JobsPikr](https://www.jobspikr.com/blog/how-jobspikr-data-pipeline-processes-job-data/)
- [PM2 Memory Profiling — PM2 Plus Docs](https://pm2.io/docs/plus/guide/memory-profiling/)
- [Playwright memory leak issue — GitHub](https://github.com/microsoft/playwright/issues/15400)
- [How to Prevent Free Tier Abuse — VinDevs](https://vindevs.com/blog/how-to-prevent-users-from-abusing-free-tiers-and-creating-multiple-accounts-p68/)
- [Free Tier Abuse: How to Protect Your SaaS — Fidro](https://fidro.io/blog/free-tier-abuse-how-to-protect-your-saas)
