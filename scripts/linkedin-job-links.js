// Pure helpers: pull job-opening links out of the URLs found in a LinkedIn DM thread.
//
// WHY a module: people DM Jiv job links (mostly LinkedIn job pages, some company ATS pages).
// The reader collects every URL a thread holds; deciding which of them are jobs is plain
// string work, so it lives here where it can be unit-tested without a browser or Codex
// (tests/battle/test_job_links.js).
//
// extract(urls) -> { linkedin_job_ids: ['4012345678'], external: ['https://boards.greenhouse.io/...'],
//                    short: ['https://lnkd.in/abc'] }
//   linkedin_job_ids  jobs the Easy Apply pipeline can open by id
//   external          job pages off LinkedIn: the runner cannot apply there, it tells Jiv
//   short             lnkd.in links: the reader follows these in the browser, then re-extracts

const MIN_JOB_ID_DIGITS = 8; // real ids are 9-10 digits; shorter numbers are not job ids

// Company ATS / job boards where a link is a job even when the path says nothing.
const ATS_HOSTS = /(^|\.)(greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|myworkdayjobs\.com|smartrecruiters\.com|bamboohr\.com|recruitee\.com|breezy\.hr|teamtailor\.com|personio\.(de|com)|rippling\.com|wellfound\.com|angel\.co|indeed\.com|glassdoor\.com|onlinejobs\.ph|jobstreet\.com|kalibrr\.com|remotive\.com|weworkremotely\.com|remoteok\.com|himalayas\.app|workatastartup\.com|jobs\.[a-z0-9-]+\.[a-z]+)$/i;
// A job-ish path on any other host (a company's own careers page).
const JOB_PATH = /\/(jobs?|careers?|positions?|openings?|vacanc(y|ies)|apply|join-us|work-with-us)(\/|$|\?)/i;
// Never a job, whatever the path: files, calendars, social profiles, the company's own link-in-bio.
const NOT_JOB_HOST = /(^|\.)(calendly\.com|cal\.com|zoom\.us|meet\.google\.com|docs\.google\.com|drive\.google\.com|github\.com|youtube\.com|youtu\.be|facebook\.com|instagram\.com|twitter\.com|x\.com|tiktok\.com|farfolio\.vercel\.app)$/i;

const isLinkedIn = (host) => /(^|\.)linkedin\.com$/i.test(host);

function parse(raw) {
  const cleaned = String(raw || '').trim().replace(/[)\]>.,;:!?'"]+$/, '');
  try {
    const u = new URL(cleaned);
    return /^https?:$/.test(u.protocol) ? u : null;
  } catch (_) {
    return null;
  }
}

/** The id of a LinkedIn job URL, or null. Handles /jobs/view/<id>, /jobs/view/<slug>-<id>, ?currentJobId=<id>. */
function linkedinJobId(u) {
  const view = u.pathname.match(/\/jobs\/view\/(?:[^/]*-)?(\d+)\/?$/);
  if (view && view[1].length >= MIN_JOB_ID_DIGITS) return view[1];
  if (/^\/(comm\/)?jobs\//.test(u.pathname)) {
    const cur = u.searchParams.get('currentJobId');
    if (cur && /^\d+$/.test(cur) && cur.length >= MIN_JOB_ID_DIGITS) return cur;
  }
  return null;
}

/** LinkedIn wraps off-site links in /safety/go/?url=<encoded>; peel that off. */
function unwrap(u) {
  if (isLinkedIn(u.hostname) && /^\/(safety\/go|redir\/redirect)\/?$/.test(u.pathname)) {
    const inner = parse(u.searchParams.get('url'));
    if (inner) return inner;
  }
  return u;
}

function extract(urls) {
  const out = { linkedin_job_ids: [], external: [], short: [] };
  const seen = new Set();
  const add = (list, v) => { if (!seen.has(list + v)) { seen.add(list + v); out[list === 'li' ? 'linkedin_job_ids' : list].push(v); } };
  for (const raw of urls || []) {
    let u = parse(raw);
    if (!u) continue;
    u = unwrap(u);
    const host = u.hostname.toLowerCase();
    if (host === 'lnkd.in') { add('short', u.href); continue; }
    if (isLinkedIn(host)) {
      const id = linkedinJobId(u);
      if (id) add('li', id);
      continue; // every other LinkedIn link is a profile, post or company page
    }
    if (NOT_JOB_HOST.test(host)) continue;
    if (ATS_HOSTS.test(host) || JOB_PATH.test(u.pathname)) add('external', u.origin + u.pathname + (u.search || ''));
  }
  return out;
}

/** Plain-text fallback (mock markup has no anchors): every http(s) token in the text. */
const urlsInText = (text) => (String(text || '').match(/https?:\/\/[^\s<>"']+/g) || []);

module.exports = { extract, urlsInText, linkedinJobId, MIN_JOB_ID_DIGITS };
