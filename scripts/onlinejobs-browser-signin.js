// Opens the Mini's OnlineJobs apply profile in a visible Chrome for a person to sign in to Google, and returns
// when they close the window. Called by onlinejobs-browser-signin.sh, which then checks the result.
//
// Why Playwright and not a plain Chrome launch (2026-10-23, twice): the runner's browser is Chrome started by
// Playwright, and cookies saved by any other kind of launch were unreadable to it, so Chrome discarded them and
// both the Google and the OnlineJobs sessions were lost. A plain `open -na` failed, and so did the Chrome binary
// started directly with --use-mock-keychain --password-store=basic copied from Playwright's switches. Launching
// through Playwright itself writes cookies exactly as the runner reads them. The automation flags are removed
// because Google refuses sign-in in a browser that announces automation (AUTOMATION.md "Google OAuth is blocked
// even in real Chrome under WebDriver automation").
//   SIGNIN_TIMEOUT_S  close by itself after this many seconds (tests; default 1800)
const path = require('path');
const { chromium } = require('playwright-core');

const PROFILE = process.env.ONLINEJOBS_PROFILE || path.join(process.env.HOME, '.onlinejobs-apply/browser-profile');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URLS = (process.env.SIGNIN_URLS || 'https://mail.google.com/mail/u/0/,https://www.onlinejobs.ph/jobseekers/jobsearch').split(',');
const TIMEOUT_S = Number(process.env.SIGNIN_TIMEOUT_S || 1800);

(async () => {
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: false,
    executablePath: CHROME,
    ignoreDefaultArgs: ['--enable-automation'],
    args: ['--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check'],
    viewport: null,
  });
  const first = ctx.pages()[0] || (await ctx.newPage());
  await first.goto(URLS[0], { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  for (const u of URLS.slice(1)) {
    const p = await ctx.newPage();
    await p.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  }
  await first.bringToFront().catch(() => {});
  // Done when the person closes the window (Cmd+Q or the last tab), or at the timeout.
  const closed = new Promise((res) => ctx.on('close', res));
  const watch = setInterval(() => { if (ctx.pages().length === 0) ctx.close().catch(() => {}); }, 1000);
  let tid;
  const timer = new Promise((res) => { tid = setTimeout(res, TIMEOUT_S * 1000); });
  await Promise.race([closed, timer]);
  clearInterval(watch);
  clearTimeout(tid);
  await ctx.close().catch(() => {});   // a graceful close is what writes the cookies to disk
  console.log('[signin] browser closed');
  // Exit explicitly: on 2026-10-23 the process stayed alive for 11 hours after the window closed, so the shell
  // helper never ran its check or lifted the pause.
  process.exit(0);
})().catch((e) => { console.error('[signin] error:', e.message); process.exit(1); });
