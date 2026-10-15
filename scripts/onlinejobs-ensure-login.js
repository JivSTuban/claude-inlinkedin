#!/usr/bin/env node
// Keeps the OnlineJobs.ph session alive for the automation so Jiv never signs in by hand.
//
//   node scripts/onlinejobs-ensure-login.js          # CLI: exit 0 = logged in (already, or after signing in)
//   const { ensureLoggedIn } = require('./onlinejobs-ensure-login');   // library: used by the inbox/apply scripts
//
// How it works: a persistent Chrome profile keeps the session cookie between runs, so most runs
// are only a check and type nothing. When the session has expired it signs in with the credentials
// below, once, and verifies the result.
//
// Credentials, first hit wins (the password is never printed, logged or screenshotted):
//   1. env ONLINEJOBS_EMAIL / ONLINEJOBS_PASSWORD
//   2. dotenv file ONLINEJOBS_ENV_FILE or ~/.onlinejobs.env   (the Mac Mini copy, chmod 600)
//   3. macOS Keychain, service `claude-onlinejobs`            (the MacBook copy)
//
// Safety, because a login loop on a wrong password can lock the account:
//   - one sign-in attempt per run, and at most MAX_ATTEMPTS_PER_HOUR across runs;
//   - a rejected password writes a cooldown (REJECT_COOLDOWN_H) and is never retried before it ends;
//   - a captcha, verification code or changed form stops with exit 3 and asks for a human.
//
// Exit codes: 0 logged in, 3 needs a human (captcha / verification / form changed),
//             5 credentials missing or rejected, 6 throttled (too many recent attempts).

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const BASE = (process.env.ONLINEJOBS_BASE || 'https://v2.onlinejobs.ph').replace(/\/$/, '');
const PROFILE = process.env.ONLINEJOBS_PROFILE || path.join(os.homedir(), '.onlinejobs-profile');
const STATE_FILE = process.env.ONLINEJOBS_STATE_FILE || path.join(os.homedir(), '.onlinejobs-login-state.json');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const MAX_ATTEMPTS_PER_HOUR = 2;
const REJECT_COOLDOWN_H = 6;
// A page behind the login: redirects to /login when the session is gone.
const CHECK_PATH = '/message';

const log = (...a) => console.log('[onlinejobs-login]', ...a);

// ---------------------------------------------------------------- credentials (pure, tested)

/** Parse KEY='value' / KEY="value" / KEY=value lines. Returns {} for a missing file. */
function parseEnvFile(text) {
  const out = {};
  for (const line of String(text || '').split('\n')) {
    const m = line.match(/^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!m) continue;
    let v = m[2];
    if ((v.startsWith("'") && v.endsWith("'")) || (v.startsWith('"') && v.endsWith('"'))) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}

function loadCredentials(env = process.env) {
  if (env.ONLINEJOBS_EMAIL && env.ONLINEJOBS_PASSWORD) {
    return { email: env.ONLINEJOBS_EMAIL, password: env.ONLINEJOBS_PASSWORD, source: 'env' };
  }
  const file = env.ONLINEJOBS_ENV_FILE || path.join(os.homedir(), '.onlinejobs.env');
  try {
    const f = parseEnvFile(fs.readFileSync(file, 'utf8'));
    if (f.ONLINEJOBS_EMAIL && f.ONLINEJOBS_PASSWORD) return { email: f.ONLINEJOBS_EMAIL, password: f.ONLINEJOBS_PASSWORD, source: file };
  } catch (_) { /* no file: fall through */ }
  if (process.platform === 'darwin' && !env.ONLINEJOBS_NO_KEYCHAIN) {
    try {
      const args = ['find-generic-password', '-s', 'claude-onlinejobs'];
      const pw = execFileSync('security', [...args, '-w'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).replace(/\n$/, '');
      const meta = execFileSync('security', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      const acct = (meta.match(/"acct"<blob>="([^"]+)"/) || [])[1];
      if (pw && acct) return { email: acct, password: pw, source: 'keychain' };
    } catch (_) { /* no keychain item */ }
  }
  return null;
}

// ---------------------------------------------------------------- attempt throttle (pure, tested)

function readState(file = STATE_FILE) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return { attempts: [], rejected_until: 0 }; }
}

/** -> null when a sign-in may go ahead, else a reason string. */
function throttleReason(state, now = Date.now()) {
  if (state.rejected_until && now < state.rejected_until) {
    return `password was rejected; cooling down until ${new Date(state.rejected_until).toISOString()}`;
  }
  const recent = (state.attempts || []).filter((t) => now - t < 3600 * 1000);
  if (recent.length >= MAX_ATTEMPTS_PER_HOUR) return `${recent.length} sign-in attempts in the last hour`;
  return null;
}

function writeState(state, file = STATE_FILE) {
  fs.writeFileSync(file, JSON.stringify(state), { mode: 0o600 });
}

// ---------------------------------------------------------------- browser

async function onLoginPage(page) {
  if (/\/(login|register|resetpass)(\?|$|\/)/.test(page.url())) return true;
  return (await page.locator('input[type="password"]').count()) > 0;
}

async function isLoggedIn(page) {
  await page.goto(BASE + CHECK_PATH, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(1500).catch(() => {});
  return !(await onLoginPage(page));
}

async function humanCheck(page) {
  const frames = page.frames().map((f) => f.url()).join(' ');
  if (/recaptcha|hcaptcha|challenges\.cloudflare|turnstile/i.test(frames)) return 'captcha';
  const body = ((await page.locator('body').innerText().catch(() => '')) || '').slice(0, 4000);
  if (/verification code|one-time|two-factor|2-step|verify (it'?s|your) (you|identity)|security check|unusual (activity|sign)/i.test(body)) return 'verification';
  return null;
}

/**
 * Make sure `page` holds a logged-in OnlineJobs session. Returns {ok, status, detail}.
 * status: already | logged_in | needs_human | no_credentials | rejected | throttled
 */
async function ensureLoggedIn(page, opts = {}) {
  const stateFile = opts.stateFile || STATE_FILE;
  if (await isLoggedIn(page)) return { ok: true, status: 'already' };

  const state = readState(stateFile);
  const blocked = throttleReason(state);
  if (blocked) return { ok: false, status: 'throttled', detail: blocked };

  const creds = (opts.loadCredentials || loadCredentials)();
  if (!creds) return { ok: false, status: 'no_credentials', detail: 'set ONLINEJOBS_EMAIL/ONLINEJOBS_PASSWORD, ~/.onlinejobs.env or the claude-onlinejobs Keychain item' };

  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 45000 });
  const email = page.getByLabel(/email/i).first();
  const password = page.locator('input[type="password"]').first();
  if (!(await email.count().catch(() => 0)) || !(await password.count().catch(() => 0))) {
    return { ok: false, status: 'needs_human', detail: 'login form not found (page changed, or a challenge is showing)' };
  }
  const gate = await humanCheck(page);
  if (gate) return { ok: false, status: 'needs_human', detail: `${gate} before signing in` };

  // Count the attempt BEFORE submitting, so a crash mid-way still counts.
  state.attempts = [...(state.attempts || []).filter((t) => Date.now() - t < 3600 * 1000), Date.now()];
  writeState(state, stateFile);

  await email.fill(creds.email);
  await password.fill(creds.password);
  const submit = page.getByRole('button', { name: /^log ?in$/i }).first();
  if (await submit.count().catch(() => 0)) await submit.click(); else await password.press('Enter');

  // Wait for the page to leave /login, or for an error to show.
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(700).catch(() => {});
    if (!(await onLoginPage(page))) {
      if (await isLoggedIn(page)) return { ok: true, status: 'logged_in', source: creds.source };
      break;
    }
    const gate2 = await humanCheck(page);
    if (gate2) return { ok: false, status: 'needs_human', detail: `${gate2} after signing in` };
    const body = ((await page.locator('body').innerText().catch(() => '')) || '').slice(0, 3000);
    if (/invalid|incorrect|wrong|does not match|not recognized|no account/i.test(body)) {
      state.rejected_until = Date.now() + REJECT_COOLDOWN_H * 3600 * 1000;
      writeState(state, stateFile);
      return { ok: false, status: 'rejected', detail: `OnlineJobs rejected the credentials (from ${creds.source}); not retrying for ${REJECT_COOLDOWN_H}h` };
    }
  }
  return { ok: false, status: 'needs_human', detail: 'still on the login page after submitting, no error text recognised' };
}

const EXIT = { already: 0, logged_in: 0, needs_human: 3, no_credentials: 5, rejected: 5, throttled: 6 };

async function launch() {
  const { chromium } = require('playwright-core');
  return chromium.launchPersistentContext(PROFILE, {
    headless: process.env.ONLINEJOBS_HEADLESS === '1',
    executablePath: CHROME,
    ignoreDefaultArgs: ['--enable-automation'],
    args: ['--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check'],
    viewport: { width: 1280, height: 900 },
  });
}

async function main() {
  const ctx = await launch();
  let result;
  try {
    const page = ctx.pages()[0] || (await ctx.newPage());
    result = await ensureLoggedIn(page);
  } finally {
    await ctx.close().catch(() => {});
  }
  log(`${result.status}${result.detail ? ': ' + result.detail : ''}`);
  return EXIT[result.status] ?? 1;
}

module.exports = { ensureLoggedIn, loadCredentials, parseEnvFile, throttleReason, readState, EXIT };

if (require.main === module) {
  main().then((rc) => process.exit(rc)).catch((e) => { console.error('[onlinejobs-login] error:', e.message); process.exit(1); });
}
