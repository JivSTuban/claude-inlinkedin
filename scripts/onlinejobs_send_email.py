#!/usr/bin/env python3
"""Sends ONE OnlineJobs email application over the Gmail app password, then logs it as `sent`.

Why this exists (2026-10-23): the scheduled run used to write and send email applications in Gmail inside its
browser profile, so a Google "confirm it's you" prompt on that profile stopped every lead for hours (23:05 to 02:05,
four runs) even though nothing else needed Google. The app password in ~/.job-followup-config.json does not depend
on any browser session; linkedin-email.py has sent through it since 2026-10-15. This reuses that script's draft
check and message builder rather than keeping a second copy.

Run by the headless model through one allowlisted command (scripts/onlinejobs-apply-mini.sh builds the prefix):

  onlinejobs_send_email.py --leads <leads.jsonl> --resume <pdf> [--dry-run] \
      --url <posting url> --title <real title> --fit <0-100> --subject <s> --body <b> [--employer <e>] [--note <n>]

The guard rails are in code, not in the prompt, because the old Gmail bot was switched off on 2026-07-18 for
repeated outbound emails:
  - the RECIPIENT is the queued lead's `apply_email` (read by the Mini's scanner from the posting). The model
    never names it, so a page or a model mistake cannot redirect an application;
  - one email per recipient and per posting, ever, across this log, applied.jsonl and LinkedIn's email-apply log;
  - a daily cap, a kill-switch file, fit >= 70, and linkedin-email.py's draft check (no dashes, no phone numbers,
    only Jiv's own links);
  - `sent` is written here and only after Gmail accepted the message, so a send cannot go unlogged and a log
    line cannot claim a send that did not happen.
Exit: 0 sent (or dry run), 2 refused (do not retry; log the lead yourself), 3 switched off, 4 Gmail failed.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import onlinejobs_log_outcome as outcome  # noqa: E402

_spec = importlib.util.spec_from_file_location("linkedin_email", os.path.join(HERE, "linkedin-email.py"))
LE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LE)

DAILY_CAP = int(os.environ.get("OJ_EMAIL_DAILY_CAP", "5"))
MIN_FIT = 70
DISABLED = os.environ.get("OJ_EMAIL_DISABLED_FILE", os.path.expanduser("~/Work/job-email-bot/onlinejobs-email.disabled"))
SEND_LOG = os.path.join(outcome.SKILL, "email-sends.jsonl")
# LinkedIn's email-apply log: a recipient emailed from there must not get a second application from here.
OTHER_LOGS = [os.path.expanduser("~/Work/job-email-bot/marketing/outreach/email-apply-log.jsonl")]
EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")


def find_lead(leads_path, url):
    with open(leads_path) as f:
        for line in f:
            line = line.strip()
            if line:
                lead = json.loads(line)
                if (lead.get("url") or "").strip() == url.strip():
                    return lead
    return None


def past_sends(applied_path, send_log, other_logs):
    """(recipient, url) pairs already emailed, from every log that records a real send."""
    pairs = []
    for row in LE.read_log(send_log):
        if row.get("status") == "sent":
            pairs.append((row.get("to", ""), row.get("url", "")))
    for path in other_logs:
        for row in LE.read_log(path):
            if row.get("status") == "sent":
                pairs.append((row.get("to", ""), row.get("url", "")))
    if os.path.exists(applied_path):
        for row in LE.read_log(applied_path):
            method = row.get("method") or ""
            if row.get("status") == "sent" and method.startswith("email:"):
                pairs.append((method.split(":", 1)[1], row.get("id_or_url", "")))
    return [(t.strip().lower(), u.strip()) for t, u in pairs]


def refusal(a, lead, sends, sent_today):
    """Reason the email must not go out, else None. `lead` is the queued lead or None."""
    if lead is None:
        return "not one of this run's queued leads"
    to = (lead.get("apply_email") or "").strip().lower()
    if not EMAIL.fullmatch(to):
        return "the queued lead has no apply email"
    if a.fit < MIN_FIT:
        return f"fit {a.fit} is under {MIN_FIT}"
    why = LE.validate_draft(a.subject, a.body)
    if why:
        return why
    if any(t == to or u == a.url.strip() for t, u in sends):
        return "already emailed this recipient or posting"
    if sent_today >= DAILY_CAP:
        return f"daily cap of {DAILY_CAP} reached"
    if not os.path.exists(a.resume):
        return "resume file missing"
    return None


def run(a, smtp_factory=None, applied_path=None, send_log=SEND_LOG, other_logs=OTHER_LOGS):
    smtp_factory = smtp_factory or LE.smtp_login
    applied_path = applied_path or os.path.join(outcome.SKILL, "applied.jsonl")
    # The model passes the body as one shell argument; a literal \n is how it writes a line break there.
    a.body = (a.body or "").replace("\\n", "\n").strip()
    a.subject = (a.subject or "").strip()
    if os.path.exists(DISABLED):
        print(f"not sent: switched off by {DISABLED}. Log this lead as handoff.")
        return 3
    lead = find_lead(a.leads, a.url)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today = sum(1 for r in LE.read_log(send_log) if r.get("status") == "sent" and str(r.get("at", "")).startswith(today))
    why = refusal(a, lead, past_sends(applied_path, send_log, other_logs), sent_today)
    if why:
        print(f"not sent: {why}. Do not retry; log this lead yourself (skipped or handoff).")
        return 2
    to = lead["apply_email"].strip().lower()
    if a.dry_run:
        print(f"dry run, not sent: would email {to} | {a.subject}\n{a.body}")
        return 0
    try:
        server, sender = smtp_factory()
        try:
            server.send_message(LE.build_message(sender, to, a.subject, a.body, a.resume))
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:  # never retried in this run: a half-sent message must not go twice
        LE.append_log(send_log, {"url": a.url, "to": to, "status": "failed", "reason": str(e)[:160]})
        print(f"not sent: Gmail refused ({str(e)[:120]}). Log this lead as handoff.")
        return 4
    # The send log first: it is what dedup reads, so a crash after this line can never cause a second email.
    LE.append_log(send_log, {"url": a.url, "to": to, "status": "sent", "subject": a.subject})
    args = argparse.Namespace(url=a.url, title=a.title, status="sent", fit=a.fit, employer=a.employer, method="email",
                              email=to, form_url="", note=a.note or f"Emailed {to} over the Gmail app password, resume attached.")
    outcome.write(outcome.build_row(args), skill=os.path.dirname(applied_path))
    print(f"sent to {to} and logged as sent. Do NOT log this lead again.")
    return 0


def main(argv=None, **kw):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--leads", required=True)
    p.add_argument("--resume", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--fit", required=True, type=int)
    p.add_argument("--subject", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--employer", default="")
    p.add_argument("--note", default="")
    return run(p.parse_args(argv), **kw)


if __name__ == "__main__":
    sys.exit(main())
