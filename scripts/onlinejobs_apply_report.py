#!/usr/bin/env python3
"""Tells Jiv what the scheduled /onlinejobs-apply run DID, nothing else.

Replaces the per-lead "N new postings apply outside the site" alert (raw URLs, "N/A" wages, obvious
misfits, and it announced work instead of results). Silence is the normal outcome: a skipped lead
is not news. A message goes out only for:
  - an application submitted or sent  -> Discord, one line per job (no phone)
  - a hand-off the skill could not finish (sign-in, a captcha, a file) -> Discord + phone
  - the runner itself failing repeatedly -> Discord at 2 runs in a row, phone at 4

Delivery goes through the Mini's notifier (`linkedin-notify.py`), the one place the Discord token and
Pushover keys live. Usage:
  onlinejobs_apply_report.py outcomes <rows-before>     report the rows added to applied.jsonl since
  onlinejobs_apply_report.py unhandled <leads-file>     exit 0 if every lead now has a logged outcome, else 1
  onlinejobs_apply_report.py failed <kind> <detail>     count a failed run
  onlinejobs_apply_report.py ok <kind>                  reset that kind's failure streak
"""
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onlinejobs_apply_gate as gate  # noqa: E402
import onlinejobs_decide as decide  # noqa: E402

APPLIED = os.path.expanduser("~/.claude/skills/onlinejobs-apply/applied.jsonl")
STATE = os.path.expanduser("~/.onlinejobs-apply/health.json")
MINI = "admin@100.98.219.58"
MINI_NOTIFY = "/Users/admin/agent-work/jobi/scripts/linkedin-notify.py"
DONE = ("submitted", "sent")
# Runs are hourly here, so these are runs, not minutes.
FAIL_INFO_AT, FAIL_PUSH_AT = 2, 4


def rows_since(n, path=APPLIED):
    with open(path) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return rows[n:]


def _name(r):
    emp = (r.get("employer") or "").strip()
    emp = "" if emp.startswith("(") else emp
    title = decide.tidy(r.get("title") or "a job", 70)
    return f"{title} at {emp}" if emp else title


def summarize(rows):
    """[(level, title, text)] for new applied.jsonl rows. Skips produce nothing."""
    done = [r for r in rows if r.get("status") in DONE]
    out = []
    if done:
        lines = [f"- {_name(r)} ({'form' if r.get('status') == 'submitted' else 'email'})" for r in done]
        head = "Applied to 1 job:" if len(done) == 1 else f"Applied to {len(done)} jobs:"
        out.append(("info", "OnlineJobs: applied", head + "\n" + "\n".join(lines)))
    for r in rows:
        if r.get("status") == "handoff":
            why = decide.tidy(r.get("next") or "needs you to finish it", 160)
            out.append(("needs", "OnlineJobs: finish an application", f"{_name(r)}: {why}"))
    return out


def send(level, title, text, runner=subprocess.run):
    """Through the Mini's notifier. Returns True if it went out."""
    cmd = f"python3 {MINI_NOTIFY} --text {shlex.quote(text)} --level {level} --title {shlex.quote(title)}"
    r = runner(["ssh", "-o", "ConnectTimeout=10", MINI, cmd], capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def unhandled(leads_file, applied_path=APPLIED):
    """Leads from this run that still have no outcome in applied.jsonl. The skill logs every outcome,
    skips included, so a lead left here means the run did not really work it (browser signed out, MCP
    missing, cut off). Judged by the same dedup the gate uses, so a lead the skill found already logged
    counts as handled."""
    with open(leads_file) as f:
        leads = [json.loads(l) for l in f if l.strip()]
    return gate.open_leads(leads, gate.read_applied(applied_path))


def _load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f)


def failed(kind, detail, sender=send, now=None):
    """Count a failed run; speak only when the streak reaches 2 (Discord) or 4 (phone)."""
    now = now or datetime.now()
    state = _load()
    rec = state.setdefault(kind, {"streak": 0})
    rec["streak"] += 1
    n = rec["streak"]
    _save(state)
    if n not in (FAIL_INFO_AT, FAIL_PUSH_AT):
        return None
    level = "needs" if n == FAIL_PUSH_AT else "info"
    sender(level, "OnlineJobs apply problem",
           f"The scheduled OnlineJobs apply run has failed {n} times in a row: {detail}")
    return level


def ok(kind):
    state = _load()
    if state.pop(kind, None) is not None:
        _save(state)


def main(argv):
    if len(argv) >= 3 and argv[1] == "outcomes":
        for level, title, text in summarize(rows_since(int(argv[2]))):
            send(level, title, text)
        return 0
    if len(argv) >= 3 and argv[1] == "unhandled":
        left = unhandled(argv[2])
        for lead in left:
            print(f"unhandled: {lead.get('title')}")
        return 1 if left else 0
    if len(argv) >= 4 and argv[1] == "failed":
        failed(argv[2], " ".join(argv[3:]))
        return 0
    if len(argv) >= 3 and argv[1] == "ok":
        ok(argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
