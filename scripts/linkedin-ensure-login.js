#!/usr/bin/env node
// Phase 1: Open persistent Playwright profile, wait for LinkedIn login (email/password).
// Exits 0 when session is saved, exits 1 on timeout.

const { chromium } = require('playwright');

const CHROMIUM = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PROFILE  = process.env.PLAYWRIGHT_PROFILE || (process.env.HOME + '/.playwright-linkedin-profile');
const TIMEOUT  = 5 * 60 * 1000;

(async () => {
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: false,
    executablePath: CHROMIUM,
    ignoreDefaultArgs: ['--enable-automation'],
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-first-run',
      '--no-default-browser-check',
    ],
  });

  const page = await ctx.newPage();
  await page.goto('https://www.linkedin.com/feed', { timeout: 15000 }).catch(() => {});

  if (page.url().includes('linkedin.com/feed')) {
    console.log('[login-check] Already logged in.');
    await ctx.close();
    process.exit(0);
  }

  await page.goto('https://www.linkedin.com/login').catch(() => {});
  console.log('[login-check] Login page open. Sign in with email/password (NOT Google). Waiting up to 5 min...');

  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000).catch(() => {});
    const url = page.url();
    if (url.includes('linkedin.com/feed') || (url.includes('linkedin.com') && !url.includes('/login'))) {
      console.log('[login-check] Logged in! Session saved.');
      await page.waitForTimeout(2000).catch(() => {});
      await ctx.close();
      process.exit(0);
    }
  }

  console.error('[login-check] Timed out after 5 minutes.');
  await ctx.close();
  process.exit(1);
})();
