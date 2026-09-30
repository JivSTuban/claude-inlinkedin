#!/usr/bin/env node
// Deterministic LinkedIn Easy Apply I/O for the Mac Mini Codex runs.
//
//   node scripts/linkedin-apply.js scan  --out <digest.json> [--max 12] [--window 86400] [--applied <log.jsonl>]
//   node scripts/linkedin-apply.js apply --digest <digest.json> --decisions <decisions.json> --profile <apply-profile.json>
//                                        --bank <answer-bank.json> --pending <pending.json> --log <apply-log.jsonl> [--dry-run]
//
// WHY this shape (same as linkedin-inbox.js): letting Codex drive the browser costs ~3M tokens
// per run and burned the ChatGPT quota on 2026-09-30. This script does the page reading and the
// form filling; Codex only reads compact JSON and decides (fit, and answers the script cannot
// derive from Jiv's facts). Judgement stays with Codex, mechanics stay here.
//
// Hard facts learned on real LinkedIn (see ~/.claude/skills/linkedin-apply/SKILL.md, 2026-08-17):
//  - `navigator.webdriver` must be false or the Easy Apply Submit button silently does nothing.
//  - The Easy Apply modal is shadow DOM: use Playwright locators / ariaSnapshot, not querySelector.
//  - Re-navigating with a modal open triggers "Save this application?"; always click Discard.
//  - LinkedIn "Remote" is almost always country-locked, so the Philippines geo seed is the one
//    that returns usable roles (the old Worldwide + past-hour seed came back empty 3 times).
//
// Exit codes: 0 ok, 1 error, 3 login wall (session expired; credentials are never typed),
//             4 apply: at least one job failed or was rejected (see the log).

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PROFILE = process.env.LINKEDIN_PROFILE || path.join(process.env.HOME, '.linkedin-codex-profile');

const argv = process.argv.slice(2);
const cmd = argv[0];
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const flag = (name) => argv.includes('--' + name);
const log = (...a) => console.log('[linkedin-apply]', ...a);
const BASE = (opt('base') || process.env.LINKEDIN_TEST_BASE || 'https://www.linkedin.com').replace(/\/$/, '');

// Seeds. geoId 103121230 = Philippines, 92000000 = Worldwide. f_WT=2 remote, f_AL=true Easy Apply only.
const SEEDS = [
  { name: 'ph', loc: 'location=Philippines&geoId=103121230' },
  { name: 'ww', loc: 'location=Worldwide&geoId=92000000' },
];
const KEYWORDS = ['AI Engineer', 'Full Stack Developer', 'Software Engineer', 'Automation Engineer', 'Backend Developer', 'Node.js Developer', 'React Developer', 'Python Developer'];

// Where Jiv can actually work from. Card text like "Philippines (Remote)" or "Worldwide".
const ELIGIBLE_LOC = /philippines|manila|cebu|makati|taguig|quezon|pasig|mandaluyong|davao|pampanga|laguna|cavite|luzon|visayas|mindanao|worldwide|anywhere|global|asia|apac/i;
// Obvious misfits only. Fit is Codex's call; this just saves it reading noise.
const TITLE_NOISE = /\b(qa tester|manual qa|\.net|c#|salesforce|sap |servicenow|wordpress|shopify|seo\b|virtual assistant|data entry|loan|nurse|customer service|sales (rep|executive)|recruiter|accountant|mechanical|electrical)\b/i;

const clean = (s) => (s || '').split('\n').map((l) => l.trim()).filter(Boolean).join('\n');
const read = (f) => (f && fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '');

async function launch() {
  return chromium.launchPersistentContext(PROFILE, {
    headless: false,
    executablePath: CHROME,
    ignoreDefaultArgs: ['--enable-automation'],
    args: ['--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check'],
    viewport: { width: 1280, height: 900 },
  });
}

async function loginWall(page) {
  if (/\/(login|checkpoint|authwall|uas\/|signup)/.test(page.url())) return true;
  return (await page.locator('input[type="password"]').count()) > 0;
}

/** jobIds and employer+title pairs we already applied to, skipped, or are waiting on. */
function loadSeen(file) {
  const ids = new Set();
  const pairs = new Set();
  const asked = new Map(); // jobId -> how many times it stopped on unanswered questions
  for (const line of read(file).split('\n')) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line);
      const id = String(r.jobId || r.id || '');
      // Dry runs never count. A job that needed answers gets ONE more try (the answer pass),
      // then it is final so it stops costing Codex tokens every run.
      if (r.dry_run) continue;
      if (r.status === 'needs_answer') { asked.set(id, (asked.get(id) || 0) + 1); if (asked.get(id) < 2) continue; }
      if (id) ids.add(id);
      if (r.company && r.title) pairs.add((r.company + '|' + r.title).toLowerCase());
    } catch (_) { /* a torn line must not stop a run */ }
  }
  return { ids, pairs };
}

async function scanCards(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(3500);
  if (await loginWall(page)) return null;
  for (let i = 0; i < 7; i++) { // the result list is virtualized: scroll to load more cards
    await page.evaluate(() => {
      const c = document.querySelector('.scaffold-layout__list > div, ul.scaffold-layout__list-container') || document.querySelector('main');
      if (c) c.scrollBy(0, 1400);
      window.scrollBy(0, 400);
    });
    await page.waitForTimeout(650);
  }
  return page.evaluate(() => {
    const jobs = [];
    document.querySelectorAll('li[data-occludable-job-id]').forEach((li) => {
      const id = li.getAttribute('data-occludable-job-id');
      const a = li.querySelector('a.job-card-container__link, a.job-card-list__title-link');
      const title = (a?.getAttribute('aria-label') || a?.innerText || '').trim().split('\n')[0];
      const company = (li.querySelector('.artdeco-entity-lockup__subtitle')?.innerText || '').trim();
      const location = (li.querySelector('.artdeco-entity-lockup__caption, .job-card-container__metadata-wrapper')?.innerText || '').trim();
      const posted = (li.innerText.match(/\d+\s+(minute|hour|second|day)s?\s+ago/i) || [''])[0];
      const applied = /(^|\n)\s*Applied\s*(\n|$)/.test(li.innerText);
      if (title && id) jobs.push({ id, title, company, location, posted, applied, easy_apply: /Easy Apply/i.test(li.innerText) });
    });
    return jobs;
  });
}

async function jobDetail(page, id) {
  await page.goto(`${BASE}/jobs/view/${id}/`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(3500);
  const body = clean(await page.locator('main').first().innerText().catch(() => ''));
  const jd = clean(await page.locator('#job-details, .jobs-description__content, .jobs-description').first().innerText().catch(() => ''));
  const closed = /No longer accepting applications/i.test(body);
  const easy = (await page.locator('[aria-label^="Easy Apply"]').count()) > 0;
  const applied = /Applied \d|You applied/i.test(body) && !easy;
  // #job-details often misses on the current markup and `main` then includes Premium upsells.
  // The real description always follows "About the job", so cut there and keep the top-card line.
  let text = jd;
  if (!text) {
    const i = body.search(/About the job/i);
    const top = body.split('\n').slice(0, 4).join(' | ');
    text = i >= 0 ? `${top}\n${body.slice(i + 'About the job'.length).trim()}` : body;
  }
  return { jd: text.slice(0, 2600), closed, easy_apply: easy, applied };
}

async function scan() {
  const out = opt('out');
  const max = Number(opt('max', 12));
  const windowSec = Number(opt('window', 86400));
  const seen = loadSeen(opt('applied'));
  const ctx = await launch();
  const page = ctx.pages()[0] || (await ctx.newPage());
  const digest = { generated_at: new Date().toISOString(), window_seconds: windowSec, session_expired: false, stats: {}, jobs: [] };
  try {
    const pool = new Map();
    let cards = 0;
    for (const seed of SEEDS) {
      for (const kw of KEYWORDS) {
        const url = `${BASE}/jobs/search/?keywords=${encodeURIComponent(kw)}&${seed.loc}&f_TPR=r${windowSec}&f_WT=2&f_AL=true&sortBy=DD`;
        const found = await scanCards(page, url);
        if (found === null) {
          digest.session_expired = true;
          fs.writeFileSync(out, JSON.stringify(digest, null, 1));
          log('login wall at', page.url());
          return 3;
        }
        cards += found.length;
        for (const j of found) if (!pool.has(j.id)) pool.set(j.id, { ...j, seed: seed.name });
      }
    }
    const all = [...pool.values()];
    const keep = all.filter((j) =>
      j.easy_apply && !j.applied && !seen.ids.has(j.id)
      && !seen.pairs.has((j.company + '|' + j.title).toLowerCase())
      && ELIGIBLE_LOC.test(j.location) && !TITLE_NOISE.test(j.title));
    digest.stats = { cards, unique: all.length, eligible_location: all.filter((j) => ELIGIBLE_LOC.test(j.location)).length, after_filters: keep.length };
    // Newest first, and PH-geo seed before worldwide: those are the ones we can actually take.
    keep.sort((a, b) => (a.seed === b.seed ? 0 : a.seed === 'ph' ? -1 : 1));
    for (const j of keep) {
      if (digest.jobs.length >= max) break;
      try {
        const d = await jobDetail(page, j.id);
        if (d.closed || d.applied || !d.easy_apply) continue;
        digest.jobs.push({ n: digest.jobs.length + 1, id: j.id, title: j.title, company: j.company, location: j.location, posted: j.posted, jd: d.jd });
      } catch (e) {
        log(`detail failed for ${j.id}: ${e.message.split('\n')[0]}`);
      }
    }
    fs.writeFileSync(out, JSON.stringify(digest, null, 1));
    log(`cards=${cards} unique=${all.length} eligible=${digest.stats.eligible_location} candidates=${digest.jobs.length}`);
    return 0;
  } finally {
    await ctx.close().catch(() => {});
  }
}

// ---------------------------------------------------------------------------------------------
// apply: walk the Easy Apply modal, fill EVERY field, submit (or stop at Review with --dry-run).
// ---------------------------------------------------------------------------------------------

const DRY = flag('dry-run');
const MAX_APPLIES = Number(opt('cap', 5));
const norm = (s) => (s || '').toLowerCase().replace(/\*/g, ' ').replace(/[^a-z0-9+#. ]+/g, ' ').replace(/\s+/g, ' ').trim();
const loadJson = (f, dflt) => {
  try { return f && fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : dflt; } catch (_) { return dflt; }
};
// Jiv's hard rule: no em/en-dashes in anything typed. Rewrite, never reject, so a good answer is not lost.
const undash = (s) => String(s).replace(/\s*[—–]\s*/g, ', ');
const NUMERIC_LABEL = /how many|years?|number of|notice|salary|compensation|expected pay|income|earning|\bctc\b|hourly|monthly|per hour|rate\b|from 1 to \d+|scale of|out of \d+/i;
const firstInt = (s) => { const m = String(s).match(/\d+(\.\d+)?/); return m ? String(Math.round(Number(m[0]))) : null; };

/** Pick the option that best matches `want` (exact > starts-with > contains), else null. */
function pickOption(options, want) {
  const w = norm(want);
  const real = options.filter((o) => norm(o) && !/^select an option$/i.test(o.trim()));
  return real.find((o) => norm(o) === w) || real.find((o) => norm(o).startsWith(w)) || real.find((o) => w && norm(o).includes(w)) || null;
}

/**
 * Answer one field from Jiv's facts. Returns {value, source} or null when nothing honest can be derived.
 * Rules only cover facts that are the same on every application; anything judgement-shaped
 * (do you have experience with X, willing to do Y, salary with no stated unit) goes to Codex.
 */
function ruleAnswer(f, P) {
  const L = norm(f.label);
  const opts = f.options || [];
  const yesNo = (yes) => pickOption(opts, yes ? 'yes' : 'no');
  const eeo = /gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun|transgender|hispanic|military/.test(L);
  if (eeo && opts.length) {
    const d = opts.find((o) => /decline|prefer not|do not wish|don.?t wish|not to (say|answer|disclose)|rather not/i.test(o));
    return d ? { value: d, source: 'rule:eeo' } : null;
  }
  if (/linkedin/.test(L) && f.kind === 'text') return { value: P.linkedin, source: 'rule:linkedin' };
  if (/github/.test(L) && f.kind === 'text') return { value: P.github, source: 'rule:github' };
  if (/(portfolio|personal (web)?site|website|blog)/.test(L) && f.kind === 'text') return { value: P.portfolio, source: 'rule:portfolio' };
  if (/^(first|given) name/.test(L)) return { value: P.first_name, source: 'rule:name' };
  if (/^(last|family|sur) ?name/.test(L)) return { value: P.last_name, source: 'rule:name' };
  if (/phone country|country code/.test(L)) { const o = pickOption(opts, P.phone_country); return o ? { value: o, source: 'rule:phone' } : null; }
  if (/(mobile|phone)/.test(L) && f.kind === 'text') return { value: P.phone, source: 'rule:phone' };
  if (/^email/.test(L) && f.kind === 'text') return { value: P.email, source: 'rule:email' };
  if (/english/.test(L) && /proficien|level|fluen/.test(L) && opts.length) {
    const o = pickOption(opts, P.english_level) || pickOption(opts, 'native');
    return o ? { value: o, source: 'rule:english' } : null;
  }
  if (/(city|where are you (based|located)|current location|location \(city\))/.test(L) && f.kind === 'text') return { value: P.city, source: 'rule:city' };
  if (/^country|country of residence|which country/.test(L) && opts.length) { const o = pickOption(opts, P.country); return o ? { value: o, source: 'rule:country' } : null; }
  // Work authorization: only ever answered for the Philippines. Any other country is a no-go, not a guess.
  const auth = L.match(/(legally )?(authori[sz]ed|eligible|permitted|right) to work (in|within|for)? ?(the )?(.+)/);
  if (auth) {
    if (/philippines/.test(auth[5])) { const a = yesNo(true); return a ? { value: a, source: 'rule:auth-ph' } : null; }
    return null;
  }
  if (/sponsorship/.test(L) && !/(us|united states|uk|canada|australia|eu|europe)\b/.test(L)) { const a = yesNo(false); return a ? { value: a, source: 'rule:sponsorship' } : null; }
  // Years with a named technology: a fixed table or nothing (an unknown tech goes to Codex, never a guess).
  const yrs = L.match(/years?.*?(?:experience|work(?:ing)?).*?(?:with|in|using|of|on)\s+(.+)$/) || L.match(/how many years.*?(?:of\s+)?(.+?)\s+experience/);
  if (yrs) {
    const tech = yrs[1].replace(/\b(do you have|have you|you)\b.*$/, '').trim();
    const hit = Object.keys(P.years || {}).sort((a, b) => b.length - a.length).find((k) => tech.includes(k));
    if (hit) return { value: String(P.years[hit]), source: `rule:years:${hit}` };
  }
  if (/total|overall/.test(L) && /years/.test(L) && /experience/.test(L)) return { value: String(P.years_overall), source: 'rule:years-overall' };
  if (/notice period/.test(L) && f.kind === 'text') return { value: String(P.notice_days ?? 0), source: 'rule:notice' };
  if (/(salary|compensation|expected pay|pay expectation|income|earning|rate)/.test(L) && f.kind === 'text') {
    if (/php|peso|₱/i.test(f.label)) return { value: String(P.salary_php_monthly), source: 'rule:salary-php' };
    if (/usd|\$|dollar/i.test(f.label)) {
      if (/hour/i.test(f.label)) return { value: String(P.salary_usd_hourly), source: 'rule:salary-usd-hr' };
      if (/(annual|year|yearly)/i.test(f.label)) return { value: String(P.salary_usd_annual), source: 'rule:salary-usd-yr' };
      if (/month/i.test(f.label)) return { value: String(P.salary_usd_monthly), source: 'rule:salary-usd-mo' };
    }
    return null; // no stated currency/unit: Codex reads the JD's posted range and decides
  }
  return null;
}

/** All controls on the current modal step, in DOM order, with enough to fill and to re-find them. */
async function readStep(page) {
  const dlg = page.getByRole('dialog').first();
  const fields = [];
  const sels = dlg.locator('select');
  for (let i = 0; i < (await sels.count()); i++) {
    const info = await sels.nth(i).evaluate((e) => ({
      label: e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute('aria-label') || '',
      options: [...e.options].map((o) => o.text.trim()),
      value: e.options[e.selectedIndex] ? e.options[e.selectedIndex].text.trim() : '',
      required: e.required,
    }));
    fields.push({ kind: 'select', i, ...info, empty: !info.value || /^select an option$/i.test(info.value) });
  }
  const txt = dlg.locator('input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]), textarea');
  for (let i = 0; i < (await txt.count()); i++) {
    const info = await txt.nth(i).evaluate((e) => ({
      label: e.getAttribute('aria-label') || (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.placeholder || '',
      value: e.value, required: e.required, multiline: e.tagName === 'TEXTAREA', combo: e.getAttribute('role') === 'combobox',
    }));
    fields.push({ kind: 'text', i, ...info, empty: !info.value.trim() });
  }
  // Radios on the current markup: <div role=radio aria-label="<question>"><p>Yes</p></div>
  const rads = await dlg.locator('div[role=radio]').evaluateAll((els) => els.map((e, idx) => ({
    idx, label: (e.getAttribute('aria-label') || '').trim(), text: (e.innerText || '').trim(),
    checked: e.getAttribute('aria-checked') === 'true' || !!e.querySelector('input:checked'),
  })));
  const groups = new Map();
  for (const r of rads) {
    if (!groups.has(r.label)) groups.set(r.label, []);
    groups.get(r.label).push(r);
  }
  for (const [label, rs] of groups) {
    fields.push({ kind: 'radio', label, options: rs.map((r) => r.text), idxs: rs.map((r) => r.idx), empty: !rs.some((r) => r.checked), required: true });
  }
  // Fallback: plain <input type=radio> not wrapped in a role=radio div (older forms), grouped by name.
  const plain = await dlg.locator('input[type=radio]').evaluateAll((els) => els.filter((e) => !e.closest('[role=radio]')).map((e, idx) => ({
    name: e.name || e.id, text: (e.labels && e.labels[0] ? e.labels[0].innerText : e.value).trim(),
    legend: (e.closest('fieldset')?.querySelector('legend')?.innerText || '').trim(), checked: e.checked,
    id: e.id,
  })));
  const pg = new Map();
  for (const r of plain) {
    const k = r.name;
    if (!pg.has(k)) pg.set(k, []);
    pg.get(k).push(r);
  }
  for (const [, rs] of pg) fields.push({ kind: 'plainradio', label: rs[0].legend || rs[0].name, options: rs.map((r) => r.text), ids: rs.map((r) => r.id), empty: !rs.some((r) => r.checked), required: true });
  const cbs = await dlg.locator('input[type=checkbox]').evaluateAll((els) => els.map((e, idx) => ({
    idx, label: (e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute('aria-label') || '').trim(), checked: e.checked, required: e.required,
  })));
  for (const c of cbs) fields.push({ kind: 'checkbox', ...c, empty: !c.checked });
  return fields;
}

async function fillField(page, f, value) {
  const dlg = page.getByRole('dialog').first();
  if (f.kind === 'select') {
    await dlg.locator('select').nth(f.i).selectOption({ label: value });
  } else if (f.kind === 'text') {
    const loc = dlg.locator('input:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=hidden]):not([type=submit]), textarea').nth(f.i);
    await loc.fill(value);
    if (f.combo) { // typeahead (city/location): LinkedIn needs a suggestion picked
      await page.waitForTimeout(900);
      const sug = page.getByRole('option').first();
      if (await sug.isVisible().catch(() => false)) await sug.click().catch(() => {});
    }
  } else if (f.kind === 'radio') {
    const k = f.options.findIndex((o) => norm(o) === norm(value));
    await dlg.locator('div[role=radio]').nth(f.idxs[k]).click();
  } else if (f.kind === 'plainradio') {
    const k = f.options.findIndex((o) => norm(o) === norm(value));
    await dlg.locator(`input[type=radio][id="${f.ids[k]}"]`).check({ force: true });
  } else if (f.kind === 'checkbox') {
    await dlg.locator('input[type=checkbox]').nth(f.idx).check({ force: true });
  }
  await page.waitForTimeout(250);
}

async function dialogErrors(page) {
  const dlg = page.getByRole('dialog').first();
  const t = await dlg.innerText().catch(() => '');
  return [...new Set((t.match(/(This field is required|Invalid input|Enter a (whole )?(decimal )?number[^\n]*|Please (enter|select|provide)[^\n]*|must be[^\n]*|is required[^\n]*|Select an option)/gi) || []))];
}

async function discardModal(page) {
  for (let i = 0; i < 3; i++) {
    const x = page.getByRole('button', { name: /^(Dismiss|Close)$/i }).first();
    if (await x.isVisible().catch(() => false)) { await x.click().catch(() => {}); await page.waitForTimeout(1200); }
    const d = page.getByRole('button', { name: /^Discard$/i }).first();
    if (await d.isVisible().catch(() => false)) { await d.click().catch(() => {}); await page.waitForTimeout(1000); }
    if (!(await page.getByRole('dialog').first().isVisible().catch(() => false))) return;
  }
}

/**
 * Apply to one job. Returns {status, ...}. Statuses: submitted | dry_run_ok | needs_answer |
 * skipped_unanswerable | no_easy_apply | validation_error | error.
 */
async function applyJob(page, job, env) {
  const { P, bank, answers } = env;
  await discardModal(page);
  await page.goto(`${BASE}/jobs/view/${job.id}/`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(4000);
  if (await loginWall(page)) return { status: 'session_expired' };
  const easy = page.locator('[aria-label^="Easy Apply"]').first();
  if (!(await easy.count())) return { status: 'no_easy_apply' };
  await easy.click(); // a NORMAL click: force-click lands on the backdrop and opens "Save this application?"
  await page.waitForTimeout(3500);
  if (!(await page.getByRole('dialog').first().isVisible().catch(() => false))) return { status: 'error', reason: 'modal did not open' };

  const used = []; // [{label, source}] for the log: what was filled and from where
  const pending = [];
  let stuck = 0;
  let lastText = '';
  for (let step = 1; step <= 10; step++) {
    const fields = await readStep(page);
    const todo = fields.filter((f) => f.empty && (f.required || f.kind === 'radio' || f.kind === 'plainradio'));
    for (const f of todo) {
      if (f.kind === 'checkbox') {
        // Only tick plain acknowledgements; never "follow company" or anything unknown.
        if (/(certify|acknowledg|agree|accurate|true and complete|privacy|terms)/i.test(f.label) && !/follow/i.test(f.label)) {
          await fillField(page, f, 'on').catch(() => {});
          used.push({ label: f.label, source: 'rule:ack' });
        } else if (f.required) pending.push({ label: f.label, kind: f.kind, options: [] });
        continue;
      }
      const key = norm(f.label);
      let ans = ruleAnswer(f, P);
      if (!ans && bank[key] != null) ans = { value: bank[key], source: 'bank' };
      if (!ans && answers.has(job.id + '|' + key)) {
        const v = answers.get(job.id + '|' + key);
        if (v === null) return { status: 'skipped_unanswerable', question: f.label, used };
        ans = { value: v, source: 'codex' };
      }
      if (ans && f.options && f.options.length) {
        const o = pickOption(f.options, ans.value);
        ans = o ? { value: o, source: ans.source } : null; // an answer that matches no option is not an answer
      }
      if (ans && f.kind === 'text') {
        ans.value = undash(ans.value);
        if (NUMERIC_LABEL.test(f.label) && !f.multiline) {
          const n = firstInt(ans.value);
          if (n === null) ans = null; else ans.value = n;
        }
      }
      if (!ans || ans.value == null || String(ans.value).trim() === '') {
        if (f.required || f.kind === 'radio' || f.kind === 'plainradio') pending.push({ label: f.label, kind: f.kind, options: f.options || [], required: !!f.required, multiline: !!f.multiline });
        continue;
      }
      try {
        await fillField(page, f, String(ans.value));
        used.push({ label: f.label, source: ans.source, value: ans.source.startsWith('rule:phone') ? '<phone>' : String(ans.value).slice(0, 60) });
      } catch (e) {
        pending.push({ label: f.label, kind: f.kind, options: f.options || [], reason: 'fill failed: ' + e.message.split('\n')[0] });
      }
    }
    if (pending.length) return { status: 'needs_answer', pending, used };

    const submit = page.getByRole('button', { name: /^Submit application$/i }).first();
    if (await submit.isVisible().catch(() => false)) {
      if (DRY) return { status: 'dry_run_ok', used, steps: step };
      await submit.click();
      await page.waitForTimeout(5000);
      const sent = await page.getByText(/your application was sent|application was sent to|Application submitted/i).first().isVisible().catch(() => false);
      const done = page.getByRole('button', { name: /^(Not now|Done|Dismiss)$/i }).first();
      if (await done.isVisible().catch(() => false)) await done.click().catch(() => {});
      return sent ? { status: 'submitted', used, steps: step } : { status: 'error', reason: 'submit clicked but "application was sent" never appeared (webdriver true?)', used };
    }
    const next = page.getByRole('button', { name: /^(Next|Continue to next step|Review|Review your application)$/i }).first();
    if (!(await next.isVisible().catch(() => false))) return { status: 'error', reason: 'no Next/Review/Submit button on step ' + step, used };
    await next.click();
    await page.waitForTimeout(2200);
    const text = await page.getByRole('dialog').first().innerText().catch(() => '');
    const errs = await dialogErrors(page);
    if (errs.length && text === lastText) stuck++;
    else if (errs.length) stuck++;
    else stuck = 0;
    lastText = text;
    if (stuck >= 2) return { status: 'validation_error', reason: errs.join('; ').slice(0, 200), used };
  }
  return { status: 'error', reason: 'more than 10 steps', used };
}

async function apply() {
  const digest = loadJson(opt('digest'), { jobs: [] });
  const decisions = loadJson(opt('decisions'), []);
  const P = loadJson(opt('profile'), null);
  if (!P) { console.error('apply needs --profile <apply-profile.json>'); return 1; }
  const bankFile = opt('bank');
  const bank = loadJson(bankFile, {});
  const pendingFile = opt('pending');
  const logFile = opt('log');
  const only = (opt('only') || '').split(',').filter(Boolean);
  const answers = new Map();
  for (const a of loadJson(opt('answers'), [])) {
    const k = a.job_id + '|' + norm(a.label);
    answers.set(k, a.answer == null || String(a.answer).trim() === '' ? null : String(a.answer));
    if (a.reusable && a.answer != null && bankFile) bank[norm(a.label)] = String(a.answer);
  }
  if (bankFile && Object.keys(bank).length) fs.writeFileSync(bankFile, JSON.stringify(bank, null, 1));

  const want = new Map(decisions.filter((d) => d.apply && Number(d.fit) >= 70).map((d) => [String(d.id), d]));
  const jobs = digest.jobs.filter((j) => (only.length ? only.includes(j.id) : want.has(j.id))).slice(0, MAX_APPLIES);
  const record = (o) => { if (logFile) fs.appendFileSync(logFile, JSON.stringify({ at: new Date().toISOString(), ...o }) + '\n'); };
  if (!jobs.length) { log('nothing to apply to'); fs.writeFileSync(pendingFile || '/dev/null', '[]'); return 0; }

  const ctx = await launch();
  const page = ctx.pages()[0] || (await ctx.newPage());
  const pendingOut = [];
  let failed = 0;
  let rc = 0;
  try {
    for (const job of jobs) {
      let r;
      try { r = await applyJob(page, job, { P, bank, answers }); } catch (e) { r = { status: 'error', reason: String(e.message || e).slice(0, 200) }; }
      await discardModal(page).catch(() => {});
      const fit = want.get(job.id)?.fit;
      log(`${r.status}: ${job.company} | ${job.title}${r.reason ? ' (' + r.reason + ')' : ''}${r.pending ? ` (${r.pending.length} unanswered)` : ''}`);
      record({ jobId: job.id, company: job.company, title: job.title, fit, status: r.status, reason: r.reason, question: r.question, filled: (r.used || []).length, sources: (r.used || []).map((u) => u.source), dry_run: DRY || undefined });
      if (r.status === 'session_expired') { rc = 3; break; }
      if (r.status === 'needs_answer') pendingOut.push({ job_id: job.id, company: job.company, title: job.title, jd: (job.jd || '').slice(0, 1800), questions: r.pending });
      if (['error', 'validation_error'].includes(r.status)) failed++;
    }
  } finally {
    if (pendingFile) fs.writeFileSync(pendingFile, JSON.stringify(pendingOut, null, 1));
    await ctx.close().catch(() => {});
  }
  return rc || (failed ? 4 : 0);
}

(async () => {
  let rc;
  if (cmd === 'scan') rc = await scan();
  else if (cmd === 'apply') rc = await apply();
  else {
    console.error('usage: linkedin-apply.js scan|apply ...');
    rc = 2;
  }
  process.exit(rc);
})().catch((e) => {
  console.error('[linkedin-apply] error:', e);
  process.exit(1);
});
