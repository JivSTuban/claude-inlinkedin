#!/usr/bin/env python3
"""After-the-fact check that LinkedIn outreach went to the people it is meant for.

Why this exists: the targeting rule lives in the skill (a prompt), and a prompt is advice. Measured on the
Mini's tracker on 2026-10-22: of the 15 invitations that carried a `hirer_role`, nearly all were recruiters and
almost all were based in the Philippines, which is Jiv's own market and not where he wants a job. In October 2026
he changed the target to FOREIGN FOUNDERS (founder, co-founder, CEO or CTO of an early-stage software/AI company
outside the Philippines), with at most one recruiter or hiring lead per run. This script reads the tracker after
each outreach run and reports every new connection request that broke that, so a drifting prompt shows up as an
alert the same day instead of as a month of wasted free connection notes.

  linkedin-outreach-audit.py --tracker FILE --since EPOCH     print violations, exit 1 if any

A row counts as "new this run" when its status is `connection_requested` and `last_action_at` is at or after
EPOCH. Rows must carry `prospect_type` (founder | hiring_lead | recruiter), `location` and `hire_signal`, which
the skill writes before sending.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone

# Words that put a profile in the Philippines. "Philippines" alone is not enough: LinkedIn shows "Metro Cebu" or
# "Makati" with no country, and 13 of 68 tracked rows had no location at all.
PH_WORDS = (
    "philippines", "philippine", "metro manila", "metro cebu", "manila", "cebu", "makati", "taguig", "pasig",
    "quezon city", "mandaluyong", "paranaque", "parañaque", "pasay", "muntinlupa", "caloocan", "marikina",
    "davao", "iloilo", "bacolod", "cagayan de oro", "lapu-lapu", "mandaue", "baguio", "calabarzon", "cavite",
    "laguna", "central visayas", "western visayas", "central luzon", "national capital region", "zamboanga",
    "pampanga", "angeles city", "batangas", "bulacan", "cainta", "imus", "binangonan", "balanga", "dasmarinas",
    "dasmariñas", "antipolo", "taytay", "las pinas", "las piñas", "valenzuela", "navotas", "malabon",
)
_PH_RE = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in PH_WORDS) + r")(?![a-z])", re.I)
FOUNDER_TYPES = ("founder",)
KNOWN_TYPES = ("founder", "hiring_lead", "recruiter")
MAX_NON_FOUNDER_PER_RUN = 1


def is_philippines(location):
    return bool(_PH_RE.search(location or ""))


def _epoch(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def new_invitations(rows, since):
    out = []
    for r in rows:
        if r.get("status") != "connection_requested":
            continue
        t = _epoch(r.get("last_action_at"))
        if t is not None and t >= since:
            out.append(r)
    return out


def audit(rows, since):
    """[(name, linkedin_url, problem)] for each new invitation that breaks the targeting rule."""
    out = []
    non_founder = 0
    for r in new_invitations(rows, since):
        who = (r.get("name") or "?", r.get("linkedin_url") or "")
        ptype = (r.get("prospect_type") or "").strip().lower()
        loc = (r.get("location") or "").strip()
        if ptype not in KNOWN_TYPES:
            out.append((*who, "no valid prospect_type (founder, hiring_lead or recruiter)"))
        elif ptype not in FOUNDER_TYPES:
            non_founder += 1
            if non_founder > MAX_NON_FOUNDER_PER_RUN:
                out.append((*who, f"a second {ptype} in one run (the limit is {MAX_NON_FOUNDER_PER_RUN}; founders come first)"))
        if not loc:
            out.append((*who, "no location recorded, so 'outside the Philippines' is unproven"))
        elif is_philippines(loc):
            out.append((*who, f"based in the Philippines ({loc[:40]})"))
        if not (r.get("hire_signal") or "").strip():
            out.append((*who, "no hire_signal recorded"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tracker", required=True)
    ap.add_argument("--since", type=float, required=True, help="epoch seconds; rows acted on at or after it are audited")
    a = ap.parse_args(argv)
    try:
        with open(a.tracker) as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read tracker: {e}", file=sys.stderr)
        return 2
    rows = d.get("prospects") if isinstance(d, dict) else d
    rows = rows if isinstance(rows, list) else [v for v in d.values() if isinstance(v, list)][0]
    problems = audit(rows, a.since)
    for name, url, why in problems:
        print(f"{name} | {url} | {why}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
