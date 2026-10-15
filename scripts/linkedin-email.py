#!/usr/bin/env python3
"""Email-apply for job links people DM to Jiv (Mac Mini, called by linkedin-codex-runner.sh).

  linkedin-email.py scan --digest <inbox digest.json> --out <candidates.json> --log <email-apply-log.jsonl>
                         [--needs-jiv <needs-jiv.jsonl>] [--dry-run]
  linkedin-email.py send --candidates <candidates.json> --drafts <drafts.json> --log <email-apply-log.jsonl>
                         --resume <apply-resume.pdf> [--disabled-file <path>] [--dry-run]

Same split as linkedin-inbox.js / linkedin-apply.js: this script does the page reading and the sending,
Codex (no browser, no mail access) only decides fit and writes the words. Exit: 0 ok, 4 a send failed.

WHY the guard rails: the earlier Gmail bot (job-email-bot/job-followup.py) was switched off on
2026-07-18 after "repeated outbound interview scheduling emails". So everything here is written to be
unable to repeat that, whatever Codex or a job page says:
  - the RECIPIENT comes only from the page this script fetched (a mailto on the posting's own domain),
    never from Codex output;
  - one email per recipient address and per posting URL, ever (the log is the memory);
  - a daily cap (DAILY_CAP), and a kill-switch file that stops all sends;
  - subject/body are validated (no dashes, no phone numbers, only Jiv's own links) before sending;
  - job-page text is untrusted: pages are fetched with SSRF checks and never executed.
Credentials: ~/.job-followup-config.json (email + app_password), the same Gmail app password the old
bot used; only those two keys are read.
"""
import argparse
import ipaddress
import json
import os
import re
import smtplib
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from html.parser import HTMLParser

DAILY_CAP = int(os.environ.get("LINKEDIN_EMAIL_DAILY_CAP", "5"))
MAX_SCAN = 5            # candidates handed to Codex per run
MAX_FETCH_BYTES = 1_500_000
MIN_FIT = 70
CONFIG = os.environ.get("LINKEDIN_EMAIL_CONFIG", os.path.expanduser("~/.job-followup-config.json"))
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; JivApplyBot/1.0)"

# Links Jiv's own emails may contain. Anything else in a draft is rejected (an injected page could
# try to make a draft point somewhere else).
ALLOWED_LINK = re.compile(r"^(https?://)?(www\.)?(github\.com/JivSTuban|linkedin\.com/in/jiv-tuban|farfolio\.vercel\.app)(/|$)", re.I)
PH_PHONE = re.compile(r"(\+?63[ -]?9\d{2})|(\b09\d{9}\b)")
DASH = re.compile(r"[—–]")
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


def now():
    return datetime.now(timezone.utc).isoformat()


def log(*a):
    print("[linkedin-email]", *a, flush=True)


# ---------------------------------------------------------------- pure helpers (unit tested)

def registrable(host):
    """Naive registrable domain: example.com, example.co.uk. Good enough to compare a mailto to its page."""
    parts = (host or "").lower().strip(".").split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    if len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class _Page(HTMLParser):
    """Collects mailto links, visible text, <title> and whether the page has a real form."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.mailtos, self.text, self.title = [], [], ""
        self._skip = 0
        self._in_title = False
        self.form_inputs = 0
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and (a.get("href") or "").lower().startswith("mailto:"):
            self.mailtos.append(a["href"])
        if tag == "form":
            self._in_form = True
        if self._in_form and tag in ("input", "textarea", "select") and a.get("type") not in ("hidden", "submit", "button"):
            self.form_inputs += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "form":
            self._in_form = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.text.append(data.strip())


def classify(html, url):
    """-> {'kind': 'email'|'other', 'why': str, 'to', 'subject_hint', 'title', 'text'}.

    'email' only when the posting itself exposes a mailto on its own domain and has no application
    form (a form means the mailto is probably a contact address, not the way to apply).
    """
    p = _Page()
    try:
        p.feed(html)
    except Exception:  # malformed markup must not crash a run
        pass
    text = " ".join(p.text)
    out = {"kind": "other", "why": "no_mailto", "to": "", "subject_hint": "", "title": p.title.strip()[:160], "text": text[:6000]}
    host = urllib.parse.urlparse(url).hostname or ""
    if p.form_inputs >= 3:
        out["why"] = "has_application_form"
        return out
    for href in p.mailtos:
        parsed = urllib.parse.urlparse(href)
        addr = urllib.parse.unquote(parsed.path).strip().lower()
        if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", addr):
            continue
        if registrable(addr.split("@", 1)[1]) != registrable(host):
            out["why"] = "recipient_domain_mismatch"
            continue
        q = urllib.parse.parse_qs(parsed.query)
        out.update(kind="email", why="ok", to=addr, subject_hint=(q.get("subject") or [""])[0][:160])
        return out
    return out


def validate_draft(subject, body):
    """Return a reason string when the draft must not be sent, else None."""
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject or not body:
        return "empty subject or body"
    if len(subject) > 140 or len(body) > 3000:
        return "too long"
    if DASH.search(subject + body):
        return "contains an em or en dash"
    if PH_PHONE.search(subject + body):
        return "contains a phone number"
    for url in re.findall(r"(?:https?://|www\.)\S+|\b(?:github|linkedin)\.com/\S+|\b\S+\.vercel\.app\S*", body):
        if not ALLOWED_LINK.match(url.rstrip(".,;:)")):
            return "link not on the allowlist: " + url[:60]
    return None


def host_is_public(host):
    """SSRF guard: job links come from DMs, so never fetch loopback/private/link-local/tailnet hosts."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return bool(infos)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_log(path):
    rows = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass  # a torn line must not stop a run
    return [r for r in rows if not r.get("dry_run")]


def append_log(path, row, dry=False):
    row = {"at": now(), **row}
    if dry:
        row["dry_run"] = True
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def sent_today(rows, today=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in rows if r.get("status") == "sent" and str(r.get("at", "")).startswith(today))


def already_sent(rows, to, url):
    return any(r.get("status") == "sent" and (r.get("to") == to or r.get("url") == url) for r in rows)


# ---------------------------------------------------------------- network

def fetch(url, max_hops=3):
    """GET with a public-host check on every hop. Returns (final_url, html) or raises."""
    for _ in range(max_hops + 1):
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname or not host_is_public(u.hostname):
            raise ValueError("blocked host or scheme")
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            r = opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise
        return url, r.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
    raise ValueError("too many redirects")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # surface 3xx so fetch() can re-validate the next hop
        return None


# ---------------------------------------------------------------- scan

def scan(a):
    digest = load_json(a.digest, {})
    rows = read_log(a.log)
    done = {r.get("url") for r in rows if r.get("status") != "fetch_failed"}
    fails = {}
    for r in rows:
        if r.get("status") == "fetch_failed":
            fails[r.get("url")] = fails.get(r.get("url"), 0) + 1
    candidates, jiv_by_thread = [], {}
    for lead in digest.get("job_leads", []):
        for url in lead.get("external", []):
            if url in done or fails.get(url, 0) >= 2 or any(c["url"] == url for c in candidates):
                continue
            try:
                final, html = fetch(url)
            except Exception as e:  # network, blocked host, bad TLS: try again next run, twice at most
                append_log(a.log, {"url": url, "status": "fetch_failed", "reason": str(e)[:120]}, a.dry_run)
                log(f"fetch failed: {url} ({str(e)[:80]})")
                continue
            c = classify(html, final)
            if c["kind"] == "email" and already_sent(rows, c["to"], url):
                append_log(a.log, {"url": url, "to": c["to"], "status": "duplicate_recipient"}, a.dry_run)
                log(f"already emailed {c['to']}, skipping {url}")
            elif c["kind"] == "email" and len(candidates) < MAX_SCAN:
                host = urllib.parse.urlparse(final).hostname or ""
                candidates.append({"id": str(len(candidates) + 1), "url": url, "to": c["to"], "subject_hint": c["subject_hint"],
                                   "title": c["title"], "company": registrable(host), "jd": c["text"],
                                   "shared_by": lead.get("name", ""), "thread_url": lead.get("thread_url", "")})
            elif c["kind"] == "other":
                append_log(a.log, {"url": url, "status": "needs_jiv", "reason": c["why"]}, a.dry_run)
                jiv_by_thread.setdefault(lead.get("thread_url", ""), {"name": lead.get("name", ""), "urls": []})["urls"].append(url)
    if a.needs_jiv and jiv_by_thread:
        existing = open(a.needs_jiv).read() if os.path.exists(a.needs_jiv) else ""  # noqa: SIM115
        for thread, v in jiv_by_thread.items():
            fresh = [u for u in v["urls"] if u not in existing]
            if not fresh or a.dry_run:
                log("(dry run) would tell Jiv: " + " ".join(fresh)) if fresh else None
                continue
            row = {"at": now(), "name": v["name"], "thread_url": thread, "their_message": "Sent " + ("job links: " if len(fresh) > 1 else "a job link: ") + " ".join(fresh),
                   "why": "Job link the runner cannot email-apply to (an application form, no email address, or a recipient on another domain). Yours to apply.", "suggested_reply": ""}
            with open(a.needs_jiv, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    with open(a.out, "w") as f:
        json.dump({"generated_at": now(), "candidates": candidates}, f, indent=1)
    log(f"{len(candidates)} email-apply candidate(s), {sum(len(v['urls']) for v in jiv_by_thread.values())} for Jiv")
    return 0


# ---------------------------------------------------------------- send

def smtp_login():
    cfg = load_json(CONFIG, {})
    s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30, context=ssl.create_default_context())
    s.login(cfg["email"], cfg["app_password"])
    return s, cfg["email"]


def build_message(sender, to, subject, body, resume_path):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = f"Jiv Tuban <{sender}>", to, subject
    m.set_content(body)
    with open(resume_path, "rb") as f:
        m.add_attachment(f.read(), maintype="application", subtype="pdf", filename="Jiv-Tuban-Resume.pdf")
    return m


def send(a, smtp_factory=smtp_login):
    if a.disabled_file and os.path.exists(a.disabled_file):
        log(f"disabled by {a.disabled_file}, sending nothing")
        return 0
    cands = {c["id"]: c for c in load_json(a.candidates, {}).get("candidates", [])}
    drafts = load_json(a.drafts, [])
    rows = read_log(a.log)
    failed = 0
    server, sender = (None, None)
    decided = {str(d.get("id")) for d in drafts if isinstance(d, dict)} if isinstance(drafts, list) else set()
    for cid, c in cands.items():
        if cid not in decided:  # Codex wrote no draft for it: record it so it is not re-offered every run
            append_log(a.log, {"url": c["url"], "to": c["to"], "status": "no_decision"}, a.dry_run)
    try:
        for d in drafts if isinstance(drafts, list) else []:
            c = cands.get(str(d.get("id")))
            if not c:
                continue
            base = {"url": c["url"], "to": c["to"], "title": c["title"][:80], "fit": d.get("fit")}
            reason = None
            if not d.get("apply") or int(d.get("fit") or 0) < MIN_FIT:
                append_log(a.log, {**base, "status": "skipped", "reason": str(d.get("reason", "not a fit"))[:160]}, a.dry_run)
                continue
            reason = validate_draft(d.get("subject"), d.get("body"))
            if not reason and already_sent(rows, c["to"], c["url"]):
                reason = "already emailed this recipient or posting"
            if not reason and sent_today(rows) >= DAILY_CAP:
                reason = f"daily cap of {DAILY_CAP} reached"
            if not reason and not os.path.exists(a.resume):
                reason = "resume file missing"
            if reason:
                append_log(a.log, {**base, "status": "rejected", "reason": reason}, a.dry_run)
                log(f"rejected {c['to']}: {reason}")
                failed += 1
                continue
            if a.dry_run:
                append_log(a.log, {**base, "status": "dry_run_ok", "subject": d["subject"]}, True)
                log(f"(dry run) would email {c['to']}: {d['subject']}")
                continue
            try:
                if server is None:
                    server, sender = smtp_factory()
                msg = build_message(sender, c["to"], d["subject"].strip(), d["body"].strip(), a.resume)
                server.send_message(msg)
                row = {**base, "status": "sent", "subject": d["subject"].strip()}
                append_log(a.log, row)
                rows.append({**row, "at": now()})
                log(f"sent: {c['to']} ({c['title'][:50]})")
                notify(f"Emailed an application to {c['to']} for {c['title'][:80] or c['url']}. Source: {c['shared_by'] or 'DM'}. Resume attached. Kill-switch: {a.disabled_file or 'email-apply.disabled'}")
            except Exception as e:  # one failure must not stop the others, and is never retried this run
                failed += 1
                append_log(a.log, {**base, "status": "failed", "reason": str(e)[:160]})
                log(f"FAILED {c['to']}: {str(e)[:100]}")
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
    return 4 if failed else 0


def notify(text):
    """One Discord DM per sent email, through the same notifier the inbox bot uses."""
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "linkedin-notify.py"), "--text", text], timeout=30, check=False)
    except Exception:
        pass  # the email is already sent and logged; a missed DM must not look like a failure


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--digest", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--log", required=True)
    s.add_argument("--needs-jiv")
    s.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("send")
    t.add_argument("--candidates", required=True)
    t.add_argument("--drafts", required=True)
    t.add_argument("--log", required=True)
    t.add_argument("--resume", required=True)
    t.add_argument("--disabled-file")
    t.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return scan(a) if a.cmd == "scan" else send(a)


if __name__ == "__main__":
    sys.exit(main())
