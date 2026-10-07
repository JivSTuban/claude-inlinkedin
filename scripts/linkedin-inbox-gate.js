// Conversation-end gate for the LinkedIn inbox pass. Pure functions, no browser, so
// `tests/battle/test_inbox_gate.js` can pin them down without spending Codex quota.
//
// WHY: on 2026-10-07 the inbox auto-reply answered one casual chat (Clark Kent Ibale) four
// times in nine hours. Every reply ended with a question, so the other person always had
// something to answer, and nothing in the skill said "this conversation is over". Judgement
// about relevance stays with Codex; what is deterministic (a thank-you, an emoji, a thread the
// bot already answered 3 times this week) is decided here so Codex never even sees it.

const MAX_BOT_REPLIES = 3; // per thread, per rolling window
const WINDOW_DAYS = 7;

// "Clark Kent Ibale  6:43 PM" or "Jiv Tuban  (He/Him)  11:52 AM": one per message.
const HEADER = /^(.{2,80}?)\s+(?:\([^)]*\)\s+)?\d{1,2}:\d{2}\s?[AP]M$/;
// Noise lines LinkedIn puts around every message group.
const NOISE = /^(View .+ profile|.+ sent the following messages? at .+|.+ is typing.*|Seen|Delivered|Today|Yesterday|[A-Z][a-z]{2,8} \d{1,2}(, \d{4})?)$/;

const isJivName = (n) => /^(you|jiv tuban)\b/i.test(n.trim());

// Thread text -> [{who: 'jiv'|'them', text}]. Returns [] when the layout is not recognised,
// in which case callers must NOT drop the thread (fail open: Codex still judges it).
function parseMessages(conversation, otherName = '') {
  const msgs = [];
  let cur = null;
  const other = otherName.trim().toLowerCase();
  // A body line like "see you at 5:00 PM" looks like a header, so when we know who the
  // other person is, only their name or Jiv's opens a message.
  const speaks = (n) => isJivName(n) || (other ? other.includes(n.trim().toLowerCase()) || n.trim().toLowerCase().includes(other) : n.trim().split(/\s+/).length <= 4);
  for (const raw of String(conversation || '').split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const h = line.match(HEADER);
    if (h && !NOISE.test(line) && speaks(h[1])) {
      cur = { who: isJivName(h[1]) ? 'jiv' : 'them', text: '' };
      msgs.push(cur);
      continue;
    }
    if (!cur || NOISE.test(line)) continue;
    cur.text += (cur.text ? '\n' : '') + line;
  }
  return msgs.filter((m) => m.text);
}

// What they said since Jiv last spoke (a person often sends 2-3 short bubbles in a row).
function theirTail(msgs) {
  let i = msgs.length;
  while (i > 0 && msgs[i - 1].who === 'them') i--;
  return msgs.slice(i).map((m) => m.text).join('\n');
}

const lastFromJiv = (msgs) => [...msgs].reverse().find((m) => m.who === 'jiv')?.text || '';

// Gratitude and farewells need no answer whatever Jiv said before.
const CORE_FAREWELL = new Set(('thanks thank ty cheers appreciate appreciated bye goodbye bless luck congrats congratulations ' +
  'welcome worries np haha hahaha lol care').split(' '));
// Words that may surround a core farewell ("thank you so much sir") but never close a thread alone.
const FILLER = new Set('you u so much a lot again many too take god good no sir po maam bro brother jiv man'.split(' '));
const FAREWELL = new Set([...CORE_FAREWELL, ...FILLER]);
// Bare acknowledgements only close a thread when Jiv had not just asked something: after a
// question, "ok" or "yes" IS the answer and the conversation continues.
const ACK = new Set(('ok okay k noted sure alright cool great nice awesome perfect got it gotcha understood will do ' +
  'sounds good yes yep yup').split(' '));

function wordsOf(text) {
  return text
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, ' link ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ') // emoji and punctuation
    .split(/\s+/)
    .filter(Boolean);
}

// True when `tail` asks nothing and carries nothing new. Never true when it holds a question
// mark or a link (a shared link is content: Alistair's Kasama MVP needed a real read).
function isClosing(tail, jivAsked) {
  if (!tail || /\?/.test(tail) || /https?:\/\//i.test(tail)) return false;
  const words = wordsOf(tail);
  if (words.length === 0) return true; // emoji or punctuation only
  if (words.length > 8) return false;
  const phrase = words.join(' ');
  if (words.every((w) => FAREWELL.has(w)) && words.some((w) => CORE_FAREWELL.has(w))) return true;
  const known = words.every((w) => FAREWELL.has(w) || ACK.has(w));
  return known && !jivAsked && /\b(?:ok|okay|k|noted|sure|alright|cool|great|nice|awesome|perfect|got it|gotcha|understood|will do|sounds good|yes|yep|yup)\b/.test(phrase);
}

function sentCount(sentRows, threadUrl, now = Date.now()) {
  const since = now - WINDOW_DAYS * 86400000;
  return sentRows.filter((r) => r.thread_url === threadUrl && r.status === 'sent' && Date.parse(r.at) >= since).length;
}

// -> { ended: bool, why, bot_replies, bot_cap_reached }
function assess({ conversation, name = '', threadUrl, sentRows = [], now }) {
  const msgs = parseMessages(conversation, name);
  const bot = sentCount(sentRows, threadUrl, now);
  const out = { ended: false, why: '', bot_replies: bot, bot_cap_reached: bot >= MAX_BOT_REPLIES };
  if (!msgs.length) return out;
  const tail = theirTail(msgs);
  const jivAsked = /\?\s*$/.test(lastFromJiv(msgs).trim());
  if (isClosing(tail, jivAsked)) {
    out.ended = true;
    out.why = 'their last message needs no answer';
  }
  return out;
}

module.exports = { assess, parseMessages, theirTail, isClosing, sentCount, MAX_BOT_REPLIES, WINDOW_DAYS };
