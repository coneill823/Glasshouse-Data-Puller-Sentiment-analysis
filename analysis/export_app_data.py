#!/usr/bin/env python3
"""
Turn the behavioural CSVs into one compact JSON file for the app front-end.

Reads:
    analysis/output/member_record.csv
    analysis/output/member_salience.csv
    analysis/output/member_rebellions.csv   (optional — the receipts)
Writes:
    app/data.json

Only SITTING members with a constituency are exported: the app answers "who
represents my area", so historical members and unmatched speakers aren't useful
in it.

Every member figure ships alongside a per-chamber benchmark (the median for
that legislature), because a lone percentage tells a reader nothing — "73.7%
turnout" only means something next to "chamber median 73.7%". Medians are
arithmetic, so this adds no judgement to the output.

Usage:
    python -m analysis.export_app_data
    python -m analysis.export_app_data --in analysis/output --out app/data.json
    python -m analysis.export_app_data --all          # include historical too
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Cap the receipts carried per member so the payload stays small; the full count
# is always reported, and member_rebellions.csv holds every one of them.
MAX_RECEIPTS = 40
MAX_TOPICS = 8


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _round(v, n=1):
    return round(v, n) if v is not None else None


def build(in_dir: Path, out_path: Path, current_only: bool = True) -> dict:
    record_path = in_dir / "member_record.csv"
    if not record_path.exists():
        raise SystemExit(f"Missing {record_path} — run `python -m analysis.behaviour` first.")

    members: dict = {}
    with open(record_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if current_only and r.get("status") != "current":
                continue
            if not r.get("constituency"):
                continue
            key = (r["parliament"], r["member"])
            members[key] = {
                "name": r["member"],
                "party": r.get("party", ""),
                "area": r["constituency"],
                "parliament": r["parliament"],
                # participation (#10)
                "votesCast": _i(r.get("votes_cast")),
                "eligible": _i(r.get("divisions_eligible")),
                "turnout": _f(r.get("turnout_pct")),
                # agreement (#4) — both baselines
                "partyAgreement": _f(r.get("party_agreement_pct")),
                "partyLineDivisions": _i(r.get("party_line_divisions")),
                "chamberAgreement": _f(r.get("chamber_agreement_pct")),
                # rebellion (#2)
                "rebellions": _i(r.get("rebellions")),
                "rebellionRate": _f(r.get("rebellion_rate_pct")),
                # scaling (#3)
                "dim1": _f(r.get("ideal_dim1")),
                "dim2": _f(r.get("ideal_dim2")),
                # salience (#9)
                "questions": _i(r.get("n_questions")),
                "speeches": _i(r.get("n_speeches")),
                "topics": [],
                "receipts": [],
            }

    # --- salience rows -------------------------------------------------------
    sal_path = in_dir / "member_salience.csv"
    if sal_path.exists():
        with open(sal_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = members.get((r["parliament"], r["member"]))
                if m is None:
                    continue
                n = _i(r.get("statements"))
                if n <= 0:
                    continue
                m["topics"].append([r["topic"], n, _f(r.get("share_of_statements_pct")) or 0.0])

    # --- rebellion receipts --------------------------------------------------
    reb_path = in_dir / "member_rebellions.csv"
    if reb_path.exists():
        with open(reb_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = members.get((r["parliament"], r["member"]))
                if m is None or len(m["receipts"]) >= MAX_RECEIPTS:
                    continue
                m["receipts"].append([
                    r.get("date", ""),
                    (r.get("division", "") or "")[:180],
                    r.get("their_vote", ""),
                    r.get("party_voted", ""),
                ])

    for m in members.values():
        m["topics"].sort(key=lambda t: -t[1])
        m["topics"] = m["topics"][:MAX_TOPICS]
        m["receipts"].sort(key=lambda r: r[0], reverse=True)

    rows = sorted(members.values(),
                  key=lambda m: (m["parliament"], m["area"], m["name"]))

    # --- per-chamber benchmarks ---------------------------------------------
    benchmarks = {}
    by_parl = defaultdict(list)
    for m in rows:
        by_parl[m["parliament"]].append(m)
    for parl, group in by_parl.items():
        def med(field):
            vals = [m[field] for m in group if m.get(field) is not None]
            return _round(st.median(vals)) if vals else None
        benchmarks[parl] = {
            "members": len(group),
            "turnout": med("turnout"),
            "partyAgreement": med("partyAgreement"),
            "chamberAgreement": med("chamberAgreement"),
            "rebellionRate": med("rebellionRate"),
            "rebellions": med("rebellions"),
            "everRebelled": sum(1 for m in group if (m["rebellions"] or 0) > 0),
        }

    topic_names = sorted({t[0] for m in rows for t in m["topics"]})
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "topics": topic_names,
        "benchmarks": benchmarks,
        "members": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    areas = {(m["parliament"], m["area"]) for m in rows}
    size_kb = out_path.stat().st_size / 1024
    print(f"Exported {len(rows)} representatives across {len(areas)} areas "
          f"and {len(topic_names)} topics -> {out_path} ({size_kb:,.0f} KB)")
    for parl, b in sorted(benchmarks.items()):
        print(f"  {parl}: {b['members']} members | median turnout "
              f"{b['turnout']}% | median party agreement {b['partyAgreement']}% | "
              f"{b['everRebelled']} have rebelled at least once")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export behavioural CSVs to app JSON.")
    ap.add_argument("--in", dest="in_dir", default="analysis/output")
    ap.add_argument("--out", dest="out_path", default="app/data.json")
    ap.add_argument("--all", action="store_true",
                    help="include historical/non-sitting members too")
    a = ap.parse_args(argv)
    build(Path(a.in_dir), Path(a.out_path), current_only=not a.all)


if __name__ == "__main__":
    main()
