#!/usr/bin/env node
// Deterministic tests for scripts/linkedin-inbox-gate.js. No browser, no Codex, no quota.
// Fixtures are the real thread text the reader captured on 2026-10-07.
const assert = require('assert');
const { assess, isClosing, parseMessages, theirTail, sentCount, MAX_BOT_REPLIES } = require('../../scripts/linkedin-inbox-gate');

let fails = 0;
const t = (name, fn) => {
  try { fn(); console.log('PASS ' + name); } catch (e) { fails++; console.log('FAIL ' + name + '\n  ' + e.message); }
};

const thread = (...parts) => parts.join('\n');
const jiv = (time, text) => `Jiv Tuban sent the following message at ${time}\nView Jiv’s profile\nJiv Tuban  (He/Him)  ${time}\n${text}`;
const them = (name, time, text) => `${name} sent the following message at ${time}\nView ${name}’s profile\n${name}  ${time}\n${text}`;

const CLARK = 'Clark Kent Ibale';
const clark = thread(
  jiv('2:50 PM', 'That makes sense. What kind of product are you experimenting with right now?'),
  them(CLARK, '3:16 PM', 'Right now, I’m experimenting with a desktop app.\nBy the way, what made you reach out to me in the first place? 😄'),
  jiv('5:50 PM', 'It felt like we work in a similar lane. What developer problem are you hoping the desktop utility will solve?'),
  them(CLARK, '6:41 PM', 'It’s still an early-stage experiment.\nHow about you? Are you currently working on any interesting products?'),
  `View Clark Kent’s profile\n${CLARK}  6:43 PM\nMag binisaya guro ta sir, hahaha🤣`,
);

t('parser splits speakers and finds their unanswered tail', () => {
  const msgs = parseMessages(clark, CLARK);
  assert.strictEqual(msgs.filter((m) => m.who === 'jiv').length, 2);
  assert.match(theirTail(msgs), /Mag binisaya/);
  assert.match(theirTail(msgs), /interesting products/);
});

t('a body line that looks like a header does not split a message', () => {
  const c = thread(jiv('1:00 PM', 'Call?'), them(CLARK, '1:05 PM', 'Maybe tomorrow\nsee you at 5:00 PM then'));
  const msgs = parseMessages(c, CLARK);
  assert.strictEqual(msgs.length, 2);
  assert.match(msgs[1].text, /see you at 5:00 PM/);
});

t('Clark thread (open question, new topic) is NOT ended', () => {
  assert.strictEqual(assess({ conversation: clark, name: CLARK, threadUrl: 'u' }).ended, false);
});

const endsWith = (text, jivText = 'Glad it helps. Have a good week.') =>
  assess({ conversation: thread(jiv('1:00 PM', jivText), them(CLARK, '1:05 PM', text)), name: CLARK, threadUrl: 'u' }).ended;

for (const closer of ['Thanks!', 'Thank you so much 🙏', 'thanks sir', '👍', '😄', 'Salamat', 'Cheers', 'Take care', 'haha', 'Noted', 'Sounds good', 'Got it', 'ok']) {
  if (closer === 'Salamat') continue; // not in the vocabulary: Codex judges it
  t(`closer "${closer}" ends the conversation`, () => assert.strictEqual(endsWith(closer), true));
}

for (const live of [
  'Thanks, can you send your resume?',
  'Thanks! What rate do you charge?',
  'ok',
  'Yes',
  'Sure',
  'Here is the link https://kasama.example/mvp',
  'Thanks. We are hiring a Next.js dev, interested?',
  'Thank you for the intro, I will check with my team and revert on Friday about the contract',
]) {
  // "ok/yes/sure" answer a question, so they only close when Jiv did not ask one.
  t(`"${live}" after a question keeps the thread open`, () =>
    assert.strictEqual(endsWith(live, 'Are you still hiring a developer?'), false));
}

t('bare ack after a statement (no question) closes', () => assert.strictEqual(endsWith('Yes', 'Sounds good, talk soon.'), true));
t('thanks closes even after a question', () => assert.strictEqual(endsWith('Thanks!', 'Is the role still open?'), true));
t('thanks that carries a question never closes', () => assert.strictEqual(isClosing('Thanks! When can we talk?', false), false));
t('address words alone never close', () => assert.strictEqual(isClosing('bro', false), false));
t('unrecognised layout fails open', () => assert.strictEqual(assess({ conversation: 'some text with no headers', threadUrl: 'u' }).ended, false));

t('bot cap counts only sent rows inside the window', () => {
  const now = Date.parse('2026-10-07T13:00:00Z');
  const row = (at, status = 'sent', thread_url = 'u') => ({ at, status, thread_url });
  const rows = [row('2026-10-07T03:52:09Z'), row('2026-10-07T06:50:45Z'), row('2026-10-07T09:50:19Z'),
    row('2026-10-07T12:00:00Z', 'failed'), row('2026-10-07T12:01:00Z', 'sent', 'other'), row('2026-09-20T00:00:00Z')];
  assert.strictEqual(sentCount(rows, 'u', now), 3);
  const g = assess({ conversation: clark, name: CLARK, threadUrl: 'u', sentRows: rows, now });
  assert.strictEqual(g.bot_cap_reached, true);
  assert.strictEqual(g.bot_replies, MAX_BOT_REPLIES);
});

t('two bot replies this week is under the cap', () => {
  const now = Date.parse('2026-10-07T13:00:00Z');
  const rows = [{ at: '2026-10-07T03:52:09Z', status: 'sent', thread_url: 'u' }, { at: '2026-10-07T06:50:45Z', status: 'sent', thread_url: 'u' }];
  assert.strictEqual(assess({ conversation: clark, name: CLARK, threadUrl: 'u', sentRows: rows, now }).bot_cap_reached, false);
});

console.log(fails ? `${fails} FAILED` : 'all passed');
process.exit(fails ? 1 : 0);
