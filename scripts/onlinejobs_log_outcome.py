#!/usr/bin/env python3
"""Records ONE /onlinejobs-apply outcome in applied.jsonl and TRACKER.md.

Why a script: the headless run is allowed to write nothing but this. Letting it Edit the two files
directly meant either broad write permission outside the repo or, with `dontAsk`, no logging at all
(seen 2026-10-22: it made the right call on a lead and was denied the write). One narrow command also
keeps the two files in step and the JSON valid, which free-hand edits do not.

  onlinejobs_log_outcome.py --url U --title T --status skipped --fit 10 --note "why" \
      [--employer E] [--method form|email] [--form-url F] [--email A]
Status is one of submitted, sent, handoff, skipped, queued.
"""
import argparse
import json
import os
import sys
from datetime import date

SKILL = os.path.expanduser("~/.claude/skills/onlinejobs-apply")
STATUSES = ("submitted", "sent", "handoff", "skipped", "queued")


def build_row(a, today=None):
    emp = (a.employer or "").strip() or "(not named)"
    method = a.method + (f":{a.email}" if a.email and a.method == "email" else "")
    row = {"source": "onlinejobs", "id_or_url": a.url, "employer": emp, "title": a.title.strip(),
           "method": method, "fit": a.fit, "date": today or date.today().isoformat(),
           "status": a.status, "next": a.note.strip()}
    if a.form_url:
        row["form_url"] = a.form_url
    return row


def tracker_line(row):
    cell = lambda s: str(s).replace("|", "/").replace("\n", " ")
    kind = {"form": "Form", "email": "Email"}.get(row["method"].split(":")[0], row["method"])
    return (f"| {row['date']} | {cell(row['title'])} | {cell(row['employer'])} | {kind} | ~{row['fit']} | "
            f"{row['status'].upper()} | {cell(row['next'])} |\n")


def write(row, skill=SKILL):
    with open(os.path.join(skill, "applied.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")
    path = os.path.join(skill, "TRACKER.md")
    text = ""
    if os.path.exists(path):
        with open(path) as f:
            text = f.read()
    line = tracker_line(row)
    marker = "\n**Learning:**"
    if marker in text:
        i = text.index(marker)
        text = text[:i].rstrip("\n") + "\n" + line + text[i:]
    else:
        text = text.rstrip("\n") + "\n" + line
    with open(path, "w") as f:
        f.write(text)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--status", required=True, choices=STATUSES)
    p.add_argument("--fit", required=True, type=int)
    p.add_argument("--note", required=True)
    p.add_argument("--employer", default="")
    p.add_argument("--method", default="form", choices=("form", "email"))
    p.add_argument("--form-url", default="")
    p.add_argument("--email", default="")
    a = p.parse_args(argv)
    if not 0 <= a.fit <= 100:
        p.error("--fit must be 0 to 100")
    row = build_row(a)
    write(row)
    print(f"logged: {row['status']} {row['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
