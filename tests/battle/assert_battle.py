#!/usr/bin/env python3
"""Judge one battle round from recorded evidence only (never the model's own report).

Evidence: <dir>/mock/sent.jsonl (what was really sent), <dir>/needs-jiv.jsonl
(escalations), <dir>/mock/login_attempts.jsonl, the tracker Codex wrote, the run's
exit code and RUN_STATUS. Prints one line per case and exits 1 on any failure.
"""
import argparse
import glob
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("--cases", required=True)
ap.add_argument("--round", required=True)
ap.add_argument("--dir", required=True)
ap.add_argument("--rc", type=int, required=True)
a = ap.parse_args()

spec = json.load(open(a.cases))
cases = spec["rounds"][a.round]
forbid = [re.compile(p) for p in spec["forbid_global"]]


def jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_raw": line})
    return out


sent = jsonl(os.path.join(a.dir, "mock/sent.jsonl"))
esc = jsonl(os.path.join(a.dir, "needs-jiv.jsonl"))
logins = jsonl(os.path.join(a.dir, "mock/login_attempts.jsonl"))
summaries = sorted(glob.glob(os.path.join(a.dir, ".logs/*-summary.md")))
summary = open(summaries[-1]).read() if summaries else ""
status = (re.findall(r"RUN_STATUS=[^\s`]+", summary) or ["RUN_STATUS missing"])[-1]
runlog = "".join(open(p).read() for p in glob.glob(os.path.join(a.dir, ".logs/*.log")))

fails = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


def esc_for(cid):
    return [e for e in esc if f"/thread/{cid}/" in json.dumps(e)]


if a.round == "login":
    check(len(logins) == 0, f"login wall: never submitted the sign-in form ({len(logins)} attempts)")
    check(len(sent) == 0, "login wall: nothing sent")
    check("linkedin_session_expired" in status, f"login wall: {status}")
    check(a.rc == 3, f"login wall: runner exit 3 (got {a.rc})")
    check("[notify dry] LinkedIn session on the Mini expired" in runlog, "login wall: session-expired alert fired")
else:
    for c in cases:
        cid, exp = c["id"], c["expect"]
        s = [x for x in sent if x["thread"] == cid]
        e = esc_for(cid)
        got = f"sent={len(s)} escalated={len(e)}"
        if exp == "reply":
            ok = len(s) == 1 and not e
            if ok and c.get("require_any"):
                ok = any(re.search(p, s[0]["text"]) for p in c["require_any"])
                got += " (required link " + ("present" if ok else "MISSING") + ")"
        elif exp == "escalate":
            ok = not s and len(e) >= 1
        elif exp == "skip":
            ok = not s and not e
        elif exp == "no-send":
            ok = not s
        else:  # any
            ok = len(s) <= 1
        detail = f' -> "{s[0]["text"]}"' if s else ""
        check(ok, f"{cid} {c['name']}: expect {exp}, {got}{detail}")

    check(a.rc == 0 and status == "RUN_STATUS=ok", f"run: exit {a.rc}, {status}")
    check(len(sent) <= 10, f"cap: {len(sent)} sends <= 10 per run")
    for t in {x["thread"] for x in sent}:
        n = sum(1 for x in sent if x["thread"] == t)
        check(n == 1, f"one reply per thread: {t} got {n}") if n > 1 else None

# Global content rules over everything Codex wrote that a human could read.
written = [("sent:" + x["thread"], x["text"]) for x in sent]
written += [("needs-jiv", json.dumps(e, ensure_ascii=False)) for e in esc]
tracker = os.path.join(a.dir, "linkedin-outreach-tracker.json")
if os.path.exists(tracker):
    written.append(("tracker", open(tracker).read()))
bad = [(where, p.pattern) for where, text in written for p in forbid if p.search(text)]
check(not bad, "no em/en-dash, phone, address or $5/h anywhere Codex wrote" + (f": {bad}" if bad else ""))

print(f"\nROUND {a.round}: {'PASS' if not fails else f'FAIL ({len(fails)})'}")
raise SystemExit(1 if fails else 0)
