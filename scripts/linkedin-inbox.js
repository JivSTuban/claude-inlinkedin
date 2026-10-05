#!/usr/bin/env node
// Deterministic LinkedIn inbox I/O for the Mac Mini Codex runs.
//
//   node scripts/linkedin-inbox.js read --out <digest.json> [--base URL] [--max 15] [--scan 30]
//   node scripts/linkedin-inbox.js send --actions <actions.json> --digest <digest.json> --log <sent.jsonl> [--base URL]
//
// WHY: letting Codex drive the browser cost ~3M tokens per inbox run (36 tool calls, 27-43K
// char page snapshots, every one re-read on each later turn) and burned the ChatGPT 5-hour
// quota in two test runs on 2026-09-30. This script does the page reading and the typing;
// Codex only reads the compact digest and decides. Judgement stays with Codex, mechanics here.
//
// Exit codes: 0 ok, 1 error, 3 login wall (session expired; credentials are never typed),
//             4 send: one or more replies failed or were rejected (see the log).

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PROFILE = process.env.LINKEDIN_PROFILE || path.join(process.env.HOME, '.linkedin-codex-profile');
const MAX_SENDS = 10;
// Last-line safety net for what the skill already forbids: em/en-dashes and PH phone numbers.
const FORBIDDEN = [/[—–]/, /\+?63[ -]?9\d{2}/, /\b09\d{9}\b/];

const argv = process.argv.slice(2);
const cmd = argv[0];
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const BASE = (opt('base') || process.env.LINKEDIN_TEST_BASE || 'https://www.linkedin.com').replace(/\/$/, '');
const log = (...a) => console.log('[linkedin-inbox]', ...a);

// Real LinkedIn first, then the plain markup of tests/battle/mock_linkedin.py.
const LIST_ITEMS = '[aria-label="Conversation List"] li.msg-conversation-listitem, [aria-label="Conversation List"] > li, main ul > li';
// Tried IN ORDER: a comma list would match in page order and `main` (an ancestor) would always win.
const THREAD_PANES = ['.msg-s-message-list-content', 'ol.conversation', 'main'];
// Sender name of each message group, to know who spoke last.
const SENDERS = '.msg-s-message-group__name, ol.conversation > li > strong';
const COMPOSER = 'div.msg-form__contenteditable[contenteditable="true"], [contenteditable="true"][role="textbox"], textarea[aria-label^="Write a message"]';
const SEND_BTN = 'button.msg-form__send-button, form button[type="submit"]:has-text("Send")';

async function paneText(page) {
  for (const sel of THREAD_PANES) {
    const el = page.locator(sel).first();
    if (!(await el.count())) continue;
    let text = clean(await el.innerText().catch(() => ''));
    // LinkedIn's suggested-reply chips ("Yes, I did") sit at the end of the list; they are not messages.
    const chips = page.locator('.msg-s-message-list__quick-replies-container').first();
    if (await chips.count()) {
      const q = clean(await chips.innerText().catch(() => ''));
      if (q && text.endsWith(q)) text = text.slice(0, -q.length).trim();
    }
    return text;
  }
  return '';
}

async function lastSender(page) {
  const names = await page.locator(SENDERS).allInnerTexts().catch(() => []);
  return (names[names.length - 1] || '').trim();
}

const isJiv = (name) => /^(you|jiv tuban)\b/i.test(name);

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

const clean = (s) => (s || '').split('\n').map((l) => l.trim()).filter(Boolean).join('\n');

async function openInbox(page) {
  await page.goto(BASE + '/messaging/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2500);
  if (await loginWall(page)) return false;
  await page.locator(LIST_ITEMS).first().waitFor({ timeout: 20000 }).catch(() => {});
  return true;
}

async function read() {
  const out = opt('out');
  const max = Number(opt('max', 15));
  const scan = Number(opt('scan', 30));
  const ctx = await launch();
  const page = ctx.pages()[0] || (await ctx.newPage());
  const digest = { generated_at: new Date().toISOString(), base: BASE, session_expired: false, threads: [], last_message_from_you: [] };
  try {
    if (!(await openInbox(page))) {
      digest.session_expired = true;
      fs.writeFileSync(out, JSON.stringify(digest, null, 1));
      log('login wall at', page.url());
      return 3;
    }
    const seen = new Set();
    for (let i = 0; i < scan && digest.threads.length < max; i++) {
      let items = page.locator(LIST_ITEMS);
      if ((await items.count()) <= i) {
        // Mock pages navigate away from the list; real LinkedIn keeps it. Reload if it's gone.
        if (!(await openInbox(page))) break;
        items = page.locator(LIST_ITEMS);
        if ((await items.count()) <= i) break;
      }
      const item = items.nth(i);
      const preview = clean(await item.innerText().catch(() => ''));
      if (!preview) continue;
      const name = preview.split('\n').find((l) => !/^Status is /.test(l)) || '';
      // The list shows "You: ..." when Jiv sent the last message: nothing to answer, don't open it.
      if (/(^|\n)You:/.test(preview)) {
        digest.last_message_from_you.push(name);
        continue;
      }
      // The first <a> in a row can be the avatar (href /in/...), which navigates to the
      // profile and times out waiting for that navigation: that failed the whole run on
      // 2026-10-02 and 2026-10-05. Prefer the thread link, and never let one stuck row
      // sink the rest of the inbox.
      const threadLink = item.locator('a[href*="/messaging/thread/"]').first();
      const anyLink = item.locator('a').first();
      const target = (await threadLink.count()) ? threadLink : (await anyLink.count()) ? anyLink : item;
      try {
        await target.click({ timeout: 10000, noWaitAfter: true });
      } catch (e) {
        digest.read_errors = (digest.read_errors || 0) + 1;
        log(`row ${i} (${name}) click failed: ${String(e.message).split('\n')[0]}`);
        if (!(await page.locator(LIST_ITEMS).count())) await openInbox(page);
        continue;
      }
      await page.waitForURL(/\/messaging\/thread\//, { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(1800);
      const url = page.url().split('?')[0];
      if (!/\/messaging\/thread\//.test(url) || seen.has(url)) continue;
      seen.add(url);
      await page.locator(THREAD_PANES[0] + ', ' + THREAD_PANES[1]).first().waitFor({ timeout: 10000 }).catch(() => {});
      const text = await paneText(page);
      const sender = await lastSender(page);
      // The list preview often shows a subject line, not "You:", so check the thread too.
      if (isJiv(sender)) {
        digest.last_message_from_you.push(name);
        if (!(await page.locator(LIST_ITEMS).count())) await openInbox(page);
        continue;
      }
      digest.threads.push({ n: digest.threads.length + 1, name, thread_url: url, last_sender: sender, list_preview: preview.slice(0, 300), conversation: text.slice(-2500) });
      if (!(await page.locator(LIST_ITEMS).count())) await openInbox(page);
    }
    fs.writeFileSync(out, JSON.stringify(digest, null, 1));
    log(`read ${digest.threads.length} threads awaiting a reply, ${digest.last_message_from_you.length} where Jiv spoke last`);
    return 0;
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function send() {
  const actionsFile = opt('actions');
  const logFile = opt('log');
  const digest = JSON.parse(fs.readFileSync(opt('digest'), 'utf8'));
  const known = new Set(digest.threads.map((t) => t.thread_url));
  let actions = [];
  if (fs.existsSync(actionsFile)) {
    const raw = JSON.parse(fs.readFileSync(actionsFile, 'utf8'));
    actions = Array.isArray(raw) ? raw : raw.replies || [];
  }
  const record = (o) => fs.appendFileSync(logFile, JSON.stringify({ at: new Date().toISOString(), ...o }) + '\n');
  let failed = 0;
  const done = new Set();
  const todo = [];
  for (const a of actions) {
    const text = (a.text || '').trim();
    let reason = '';
    if (!known.has(a.thread_url)) reason = 'thread not in this run\'s digest';
    else if (done.has(a.thread_url)) reason = 'second reply to the same thread';
    else if (!text) reason = 'empty text';
    else if (FORBIDDEN.some((re) => re.test(text))) reason = 'text contains a forbidden pattern (dash or phone)';
    else if (todo.length >= MAX_SENDS) reason = `over the ${MAX_SENDS}-reply cap`;
    if (reason) {
      failed++;
      record({ name: a.name, thread_url: a.thread_url, status: 'rejected', reason });
      continue;
    }
    done.add(a.thread_url);
    todo.push({ ...a, text });
  }
  if (!todo.length) {
    log(`nothing to send (${failed} rejected)`);
    return failed ? 4 : 0;
  }
  const ctx = await launch();
  const page = ctx.pages()[0] || (await ctx.newPage());
  try {
    for (const a of todo) {
      try {
        await page.goto(a.thread_url, { waitUntil: 'domcontentloaded', timeout: 45000 });
        await page.waitForTimeout(2500);
        if (await loginWall(page)) {
          record({ name: a.name, thread_url: a.thread_url, status: 'failed', reason: 'linkedin_session_expired' });
          failed++;
          return 3;
        }
        const box = page.locator(COMPOSER).first();
        await box.waitFor({ timeout: 15000 });
        await box.click();
        if ((await box.evaluate((el) => el.tagName)) === 'TEXTAREA') await box.fill(a.text);
        else await page.keyboard.insertText(a.text);
        await page.waitForTimeout(600);
        const btn = page.locator(SEND_BTN).first();
        if (await btn.count()) await btn.click({ timeout: 10000 });
        else await page.getByRole('button', { name: /^Send$/ }).first().click({ timeout: 10000 });
        await page.waitForTimeout(3000);
        // Verify from the page, not from the click: the sent text must now be in the thread.
        const probe = a.text.slice(0, 60);
        const pane = await paneText(page);
        const ok = pane.replace(/\s+/g, ' ').includes(probe.replace(/\s+/g, ' '));
        if (!ok) failed++;
        record({ name: a.name, thread_url: a.thread_url, status: ok ? 'sent' : 'unverified', text: a.text });
        log(`${ok ? 'sent' : 'UNVERIFIED'}: ${a.name}`);
      } catch (e) {
        failed++;
        record({ name: a.name, thread_url: a.thread_url, status: 'failed', reason: String(e.message || e).slice(0, 200) });
        log(`FAILED: ${a.name}: ${e.message}`);
      }
    }
  } finally {
    await ctx.close().catch(() => {});
  }
  return failed ? 4 : 0;
}

(async () => {
  let rc;
  if (cmd === 'read') rc = await read();
  else if (cmd === 'send') rc = await send();
  else {
    console.error('usage: linkedin-inbox.js read|send ...');
    rc = 2;
  }
  process.exit(rc);
})().catch((e) => {
  console.error('[linkedin-inbox] error:', e);
  process.exit(1);
});
