#!/usr/bin/env node
// Tests for scripts/onlinejobs-ensure-login.js against a LOCAL mock login server, with fake
// credentials. No real OnlineJobs account is touched and nothing real is typed anywhere.
const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const login = require('../../scripts/onlinejobs-ensure-login');

let fails = 0;
const t = (name, fn) => {
  try { fn(); console.log('PASS ' + name); } catch (e) { fails++; console.log('FAIL ' + name + '\n  ' + e.message); }
};

// ---- pure
t('parseEnvFile handles quotes, export and comments', () => {
  const r = login.parseEnvFile("# c\nONLINEJOBS_EMAIL='a@b.c'\nexport ONLINEJOBS_PASSWORD=\"p w?\"\nX=1\n");
  assert.deepStrictEqual(r, { ONLINEJOBS_EMAIL: 'a@b.c', ONLINEJOBS_PASSWORD: 'p w?', X: '1' });
});
t('credentials: env wins, then the env file, then nothing', () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ojc-')), 'e.env');
  fs.writeFileSync(f, "ONLINEJOBS_EMAIL='file@x.y'\nONLINEJOBS_PASSWORD='filepw'\n");
  const base = { ONLINEJOBS_NO_KEYCHAIN: '1', ONLINEJOBS_ENV_FILE: f };
  assert.strictEqual(login.loadCredentials({ ...base, ONLINEJOBS_EMAIL: 'env@x.y', ONLINEJOBS_PASSWORD: 'envpw' }).source, 'env');
  assert.strictEqual(login.loadCredentials(base).email, 'file@x.y');
  assert.strictEqual(login.loadCredentials({ ONLINEJOBS_NO_KEYCHAIN: '1', ONLINEJOBS_ENV_FILE: '/nonexistent' }), null);
});
t('throttle: two attempts in the hour, or a live rejection cooldown, block a sign-in', () => {
  const now = Date.now();
  assert.strictEqual(login.throttleReason({ attempts: [now - 1000] }, now), null);
  assert.ok(login.throttleReason({ attempts: [now - 1000, now - 2000] }, now));
  assert.ok(login.throttleReason({ attempts: [], rejected_until: now + 5000 }, now));
  assert.strictEqual(login.throttleReason({ attempts: [now - 7200e3, now - 7300e3] }, now), null);
});

// ---- browser flows against the mock
const EMAIL = 'tester@example.com';
const PW = 'mock-pass-123';
let mode = 'normal';
const posts = [];
const page = (extra = '') => `<html><body><h1>Log in</h1>${extra}<form method="post" action="/login">
<label for="e">Email Address</label><input id="e" name="email" type="text">
<label for="p">Password</label><input id="p" name="password" type="password">
<button type="submit">Log in</button></form></body></html>`;
const srv = http.createServer((q, r) => {
  const cookie = /oj=1/.test(q.headers.cookie || '');
  if (q.url.startsWith('/jobseekers/jobsearch')) {
    r.end(cookie ? '<html><body><nav><a>Messages</a> <a>JOB BOARD</a> <a>Account</a></nav><p>jobs</p></body></html>'
      : '<html><body><nav><a href="/login">LOG IN</a> <a>SIGN UP</a></nav><p>jobs</p></body></html>');
    return;
  }
  if (q.url.startsWith('/g/in')) { r.end('<html>account</html>'); return; }
  if (q.url.startsWith('/g/out')) { r.writeHead(302, { Location: '/signin/v2/identifier' }); r.end(); return; }
  // A profile with no Google cookies at all: myaccount.google.com sends it to the www.google.com/account/about
  // marketing page, another host. localhost vs the 127.0.0.1 base stands in for that host change.
  if (q.url.startsWith('/g/nocookies')) { r.writeHead(302, { Location: `http://localhost:${srv.address().port}/account/about/` }); r.end(); return; }
  if (q.url.startsWith('/account/about')) { r.end('<html>Learn more about Google accounts</html>'); return; }
  if (q.url.startsWith('/signin/')) { r.end('<html>Sign in to Google</html>'); return; }
  if (q.url.startsWith('/recaptcha')) { r.end('<html>captcha frame</html>'); return; }
  if (q.method === 'POST') {
    let b = '';
    q.on('data', (c) => (b += c));
    q.on('end', () => {
      const f = Object.fromEntries(new URLSearchParams(b));
      posts.push(f.email);
      if (f.email === EMAIL && f.password === PW) { r.writeHead(302, { 'Set-Cookie': 'oj=1; Path=/; Max-Age=86400', Location: '/message' }); r.end(); }
      else r.end(page('<p class="err">Invalid email or password.</p>'));
    });
    return;
  }
  if (q.url.startsWith('/message')) {
    if (cookie) { r.end('<html><body><h1>Inbox</h1></body></html>'); return; }
    r.writeHead(302, { Location: '/login?redirect=%2Fmessage' }); r.end(); return;
  }
  if (q.url.startsWith('/login')) {
    r.end(page(mode === 'captcha' ? `<iframe src="http://127.0.0.1:${srv.address().port}/recaptcha/api2/anchor"></iframe>` : ''));
    return;
  }
  r.statusCode = 404; r.end('x');
});

// Async on purpose: the mock server lives in THIS process, so a blocking spawn would starve it.
function run(env) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ojl-'));
  const e = {
    ...process.env, ONLINEJOBS_BASE: `http://127.0.0.1:${srv.address().port}`, ONLINEJOBS_HEADLESS: '1', ONLINEJOBS_NO_KEYCHAIN: '1',
    ONLINEJOBS_PROFILE: env.profile || path.join(dir, 'profile'), ONLINEJOBS_STATE_FILE: env.state || path.join(dir, 'state.json'),
    ONLINEJOBS_ENV_FILE: '/nonexistent', ...env.vars,
  };
  return new Promise((resolve) => {
    const p = spawn('node', [path.join(__dirname, '..', '..', 'scripts', 'onlinejobs-ensure-login.js'), ...(env.args || [])], { env: e });
    let out = '';
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', (d) => (out += d));
    const timer = setTimeout(() => p.kill('SIGKILL'), 90000);
    p.on('close', (rc) => { clearTimeout(timer); resolve({ rc, out, dir, profile: e.ONLINEJOBS_PROFILE, state: e.ONLINEJOBS_STATE_FILE }); });
  });
}
const good = { ONLINEJOBS_EMAIL: EMAIL, ONLINEJOBS_PASSWORD: PW };

(async () => {
  await new Promise((res) => srv.listen(0, '127.0.0.1', res));
  const n0 = () => posts.length;

  let a = await run({ vars: good });
  t('logged out + good credentials: signs in once, exit 0', () => { assert.strictEqual(a.rc, 0, a.out); assert.match(a.out, /logged_in/); assert.strictEqual(posts.length, 1); });
  t('the password never appears in the output', () => assert.ok(!a.out.includes(PW)));

  const before = n0();
  const b = await run({ profile: a.profile, state: a.state, vars: good });
  t('already logged in (cookie in the profile): checks only, types and posts nothing', () => { assert.strictEqual(b.rc, 0, b.out); assert.match(b.out, /already/); assert.strictEqual(n0(), before); });

  let c = await run({ vars: { ONLINEJOBS_EMAIL: EMAIL, ONLINEJOBS_PASSWORD: 'wrong-pass' } });
  t('wrong password: exit 5, rejected, cooldown written', () => {
    assert.strictEqual(c.rc, 5, c.out); assert.match(c.out, /rejected/);
    assert.ok(login.readState(c.state).rejected_until > Date.now());
  });
  const afterReject = n0();
  const c2 = await run({ profile: c.profile, state: c.state, vars: { ONLINEJOBS_EMAIL: EMAIL, ONLINEJOBS_PASSWORD: 'wrong-pass' } });
  t('after a rejection it does NOT try again (no second POST, exit 6)', () => { assert.strictEqual(c2.rc, 6, c2.out); assert.strictEqual(n0(), afterReject); });

  const d0 = n0();
  const d = await run({ vars: {} });
  t('no credentials anywhere: exit 5, nothing posted', () => { assert.strictEqual(d.rc, 5, d.out); assert.match(d.out, /no_credentials/); assert.strictEqual(n0(), d0); });

  mode = 'captcha';
  const e0 = n0();
  const e = await run({ vars: good });
  t('captcha on the login page: exit 3 for a human, nothing posted', () => { assert.strictEqual(e.rc, 3, e.out); assert.match(e.out, /captcha/); assert.strictEqual(n0(), e0); });
  mode = 'normal';

  const dirS = fs.mkdtempSync(path.join(os.tmpdir(), 'ojs-'));
  const stateFile = path.join(dirS, 'state.json');
  fs.writeFileSync(stateFile, JSON.stringify({ attempts: [Date.now() - 60e3, Date.now() - 120e3] }));
  const f0 = n0();
  const f = await run({ state: stateFile, vars: good });
  t('two attempts in the last hour: throttled, exit 6, nothing posted', () => { assert.strictEqual(f.rc, 6, f.out); assert.strictEqual(n0(), f0); });

  // The older v2 site detects a dead session by the /message redirect instead of reading the nav.
  const v0 = n0();
  const v = await run({ vars: { ...good, ONLINEJOBS_SITE: 'v2' } });
  t('v2 site: logged out + good credentials signs in once', () => { assert.strictEqual(v.rc, 0, v.out); assert.match(v.out, /logged_in/); assert.strictEqual(n0(), v0 + 1); });

  // --check never types: signed out is exit 4 with nothing posted, a live session is exit 0.
  const g0 = n0();
  const g = await run({ args: ['--check'], vars: good });
  t('--check while signed out: exit 4, nothing typed or posted', () => { assert.strictEqual(g.rc, 4, g.out); assert.match(g.out, /signed_out/); assert.strictEqual(n0(), g0); });
  const g2 = await run({ args: ['--check'], profile: a.profile, state: a.state, vars: good });
  t('--check with a live session: exit 0', () => { assert.strictEqual(g2.rc, 0, g2.out); assert.match(g2.out, /already/); });

  // --google is detect-only: a profile bounced to the Google sign-in page is exit 7, never a typed password.
  const base = `http://127.0.0.1:${srv.address().port}`;
  const h0 = n0();
  const h = await run({ args: ['--google'], profile: a.profile, state: a.state, vars: { ...good, GOOGLE_PROBE_URL: base + '/g/out' } });
  t('--google while signed out of Google: exit 7, nothing posted', () => { assert.strictEqual(h.rc, 7, h.out); assert.match(h.out, /google_signed_out/); assert.strictEqual(n0(), h0); });
  const h2 = await run({ args: ['--google'], profile: a.profile, state: a.state, vars: { ...good, GOOGLE_PROBE_URL: base + '/g/in' } });
  t('--google while signed in to Google: exit 0', () => { assert.strictEqual(h2.rc, 0, h2.out); });
  // 2026-10-23: a cookieless profile landed on the account/about page and the old check called it signed in.
  const h3 = await run({ args: ['--google'], profile: a.profile, state: a.state, vars: { ...good, GOOGLE_PROBE_URL: base + '/g/nocookies' } });
  t('--google with no Google cookies (redirected to the about page on another host): exit 7', () => { assert.strictEqual(h3.rc, 7, h3.out); });

  srv.close();
  console.log(fails ? `\n${fails} FAILED` : '\nall passed');
  process.exit(fails ? 1 : 0);
})();
