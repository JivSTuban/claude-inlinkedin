#!/usr/bin/env node
// Deterministic tests for scripts/linkedin-job-links.js. No browser, no Codex, no quota.
const assert = require('assert');
const { extract, urlsInText, parseJobTitle, parseJobLocation } = require('../../scripts/linkedin-job-links');

let fails = 0;
const t = (name, fn) => {
  try { fn(); console.log('PASS ' + name); } catch (e) { fails++; console.log('FAIL ' + name + '\n  ' + e.message); }
};

t('plain job view link gives its id', () => {
  assert.deepStrictEqual(extract(['https://www.linkedin.com/jobs/view/4012345678/']).linkedin_job_ids, ['4012345678']);
});
t('slug-id form and tracking params', () => {
  const r = extract(['https://ph.linkedin.com/jobs/view/ai-engineer-at-acme-4012345678?trk=public_jobs&refId=x']);
  assert.deepStrictEqual(r.linkedin_job_ids, ['4012345678']);
});
t('search page with currentJobId', () => {
  const r = extract(['https://www.linkedin.com/jobs/collections/recommended/?currentJobId=3999888777']);
  assert.deepStrictEqual(r.linkedin_job_ids, ['3999888777']);
});
t('safety/go wrapper is unwrapped to the real job', () => {
  const inner = encodeURIComponent('https://boards.greenhouse.io/acme/jobs/123');
  const r = extract([`https://www.linkedin.com/safety/go/?url=${inner}&trk=flagship`]);
  assert.deepStrictEqual(r.external, ['https://boards.greenhouse.io/acme/jobs/123']);
});
t('profile, post and company links are not jobs', () => {
  const r = extract(['https://www.linkedin.com/in/jane-doe/', 'https://www.linkedin.com/posts/jane_hiring-activity-1', 'https://www.linkedin.com/company/acme/']);
  assert.deepStrictEqual(r, { linkedin_job_ids: [], external: [], short: [] });
});
t('a short number in a jobs path is not a job id', () => {
  assert.deepStrictEqual(extract(['https://www.linkedin.com/jobs/view/12345/']).linkedin_job_ids, []);
});
t('company careers page and ATS hosts are external jobs', () => {
  const r = extract(['https://acme.com/careers/senior-engineer', 'https://jobs.lever.co/acme/abc', 'https://acme.ashbyhq.com/xyz']);
  assert.strictEqual(r.external.length, 3);
});
t('calendar, github and an unrelated site are ignored', () => {
  const r = extract(['https://calendly.com/jane/30min', 'https://github.com/jane/repo', 'https://example.com/blog/post']);
  assert.deepStrictEqual(r.external, []);
});
t('lnkd.in goes to short for the reader to follow', () => {
  assert.deepStrictEqual(extract(['https://lnkd.in/eAbCdEf']).short, ['https://lnkd.in/eAbCdEf']);
});
t('duplicates collapse and trailing punctuation is trimmed', () => {
  const r = extract(['https://www.linkedin.com/jobs/view/4012345678/).', 'https://www.linkedin.com/jobs/view/4012345678/?trk=a']);
  assert.deepStrictEqual(r.linkedin_job_ids, ['4012345678']);
});
t('junk input does not throw', () => {
  assert.deepStrictEqual(extract([null, '', 'not a url', 'ftp://x/y', undefined]), { linkedin_job_ids: [], external: [], short: [] });
});
t('text fallback finds urls in plain thread text', () => {
  const urls = urlsInText('Hey! Check this https://www.linkedin.com/jobs/view/4012345678/ it fits you.');
  assert.deepStrictEqual(extract(urls).linkedin_job_ids, ['4012345678']);
});

// Strings captured from live job pages on 2026-10-15.
t('job page title splits into title and company', () => {
  assert.deepStrictEqual(parseJobTitle('Senior Platform Engineer - On-Prem & Bare-Metal (Philippines/Malaysia) | X-Team | LinkedIn'),
    { title: 'Senior Platform Engineer - On-Prem & Bare-Metal (Philippines/Malaysia)', company: 'X-Team' });
});
t('a title that contains a pipe keeps it', () => {
  assert.deepStrictEqual(parseJobTitle('AI Automation Specialist (n8n) | Marketing & Creative | HGS OSS | LinkedIn'),
    { title: 'AI Automation Specialist (n8n) | Marketing & Creative', company: 'HGS OSS' });
});
t('a removed job page ("Jobs | LinkedIn") has no title or company', () => {
  assert.deepStrictEqual(parseJobTitle('Jobs | LinkedIn'), { title: '', company: '' });
});
t('location line is the first dotted line with an age or applicant count', () => {
  const lines = ['X-Team', 'Senior Platform Engineer', 'Philippines · 1 week ago · 49 applicants', 'Remote'];
  assert.strictEqual(parseJobLocation(lines), 'Philippines · 1 week ago · 49 applicants');
  assert.strictEqual(parseJobLocation(['no', 'dots here']), '');
});

console.log(fails ? `\n${fails} FAILED` : '\nall passed');
process.exit(fails ? 1 : 0);
