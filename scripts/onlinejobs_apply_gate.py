#!/usr/bin/env python3
"""Decides whether a headless /onlinejobs-apply run is worth starting.

Why this exists: the Mini finds and queues external-application leads (`scan_forms`), but the
applying is the /onlinejobs-apply skill on the MacBook, and nothing ever triggered it, so leads
sat unactioned. The Mini also cannot see `applied.jsonl`, so its queue keeps showing leads that
were already applied to or skipped. This gate does that dedup here, on the MacBook, before a
Claude session (tokens, a browser, Gmail sends) is spent.

Prints the open leads as JSON lines and exits 0 when there is work, exits 3 when there is none,
exits 2 when the queue could not be read (a broken read must never look like "nothing to do").
"""
import json
import os
import subprocess
import sys

MINI = "admin@100.98.219.58"
MINI_STATE = "/Users/admin/Work/job-email-bot/oj-state.json"
APPLIED = os.path.expanduser("~/.claude/skills/onlinejobs-apply/applied.jsonl")


def read_leads(ssh_run=subprocess.run):
    """Leads the Mini has queued. Raises on any failure so the caller can exit 2."""
    code = f'import json;d=json.load(open("{MINI_STATE}"));print(json.dumps(list(d.get("forms",{{}}).get("leads",{{}}).values())))'
    r = ssh_run(["ssh", "-o", "ConnectTimeout=10", MINI, f"python3 -c '{code}'"],
                capture_output=True, text=True, timeout=40)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def read_applied(path=APPLIED):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _norm(s):
    return (s or "").strip().lower()


def open_leads(leads, applied):
    """Drop leads already in applied.jsonl by posting url, form url, apply email or employer.

    Employer match is why A Man & His Cave (applied 2026-08-01 to another posting) stops
    reappearing. An unnamed employer never matches, so it cannot hide a real lead.
    """
    seen = set()
    for row in applied:
        for key in ("id_or_url", "form_url"):
            if row.get(key):
                seen.add(_norm(row[key]))
        method = row.get("method") or ""
        if method.startswith("email:"):
            seen.add(_norm(method.split(":", 1)[1]))
        emp = _norm(row.get("employer"))
        if emp and not emp.startswith("("):
            seen.add("emp:" + emp)
    out = []
    for lead in leads:
        if lead.get("applied") or lead.get("closed"):
            continue
        keys = [_norm(lead.get("url")), _norm(lead.get("form_url")), _norm(lead.get("apply_email"))]
        emp = _norm(lead.get("employer"))
        if emp:
            keys.append("emp:" + emp)
        if any(k and k in seen for k in keys):
            continue
        out.append(lead)
    return out


def main():
    try:
        leads = read_leads()
        applied = read_applied()
    except Exception as e:  # noqa: BLE001 - any failure must be loud, not "no work"
        print(f"gate: cannot read the queue: {e}", file=sys.stderr)
        return 2
    todo = open_leads(leads, applied)
    for lead in todo:
        print(json.dumps(lead))
    return 0 if todo else 3


if __name__ == "__main__":
    sys.exit(main())
