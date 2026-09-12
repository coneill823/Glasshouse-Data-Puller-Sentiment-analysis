#!/usr/bin/env python3
"""
Turn the grading CSVs into one compact JSON file for the app front-end.

Reads:
    analysis/output/member_grades.csv
    analysis/output/member_topic_scores.csv
Writes:
    app/data.json

By default only SITTING members with a constituency are exported — the app is
"show and grade the representatives for my area", so historical members and
unmatched speakers aren't useful there.

Usage:
    python -m analysis.export_app_data
    python -m analysis.export_app_data --in analysis/output --out app/data.json
    python -m analysis.export_app_data --all            # include historical too
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def build(in_dir: Path, out_path: Path, current_only: bool = True) -> dict:
    grades_path = in_dir / "member_grades.csv"
    topics_path = in_dir / "member_topic_scores.csv"
    for p in (grades_path, topics_path):
        if not p.exists():
            raise SystemExit(f"Missing {p} — run `python -m analysis.grade` first.")

    members: dict = {}
    with open(grades_path, encoding="utf-8-sig", newline="") as f:
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
                "activity": _i(r.get("activity_total")),
                "questions": _i(r.get("n_questions")),
                "speeches": _i(r.get("n_speeches")),
                "votes": _i(r.get("n_votes")),
                "tone": _f(r.get("tone_score")),
                "topPro": (r.get("top_pro_topic") or "").replace("Pro-", ""),
                "topCon": (r.get("top_con_topic") or "").replace("Pro-", ""),
                # topic -> [stance, evidence]
                "topics": {},
            }

    with open(topics_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            key = (r["parliament"], r["member"])
            m = members.get(key)
            if m is None:
                continue
            evidence = (_i(r.get("spoken_pro")) + _i(r.get("spoken_con"))
                        + _i(r.get("vote_pro")) + _i(r.get("vote_con")))
            stance = round(_f(r.get("combined_stance")), 3)
            if evidence == 0 and stance == 0:
                continue  # nothing to show for this topic
            m["topics"][r["topic"].replace("Pro-", "")] = [stance, evidence]

    rows = sorted(members.values(),
                  key=lambda m: (m["parliament"], m["area"], m["name"]))
    topic_names = sorted({t for m in rows for t in m["topics"]})
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "topics": topic_names,
        "members": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    areas = {(m["parliament"], m["area"]) for m in rows}
    size_kb = out_path.stat().st_size / 1024
    print(f"Exported {len(rows)} representatives across {len(areas)} areas "
          f"and {len(topic_names)} topics -> {out_path} ({size_kb:,.0f} KB)")
    by_parl: dict = {}
    for m in rows:
        by_parl[m["parliament"]] = by_parl.get(m["parliament"], 0) + 1
    for p, n in sorted(by_parl.items()):
        print(f"  {p}: {n}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export grading CSVs to app JSON.")
    ap.add_argument("--in", dest="in_dir", default="analysis/output")
    ap.add_argument("--out", dest="out_path", default="app/data.json")
    ap.add_argument("--all", action="store_true",
                    help="include historical/non-sitting members too")
    a = ap.parse_args(argv)
    build(Path(a.in_dir), Path(a.out_path), current_only=not a.all)


if __name__ == "__main__":
    main()
