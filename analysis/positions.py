#!/usr/bin/env python3
"""
Build the quiz: statements a user can agree or disagree with, and where every
sitting MP stands on each one — from how they actually voted.

The design rule is that the user and the representative are measured with the
same ruler. Each statement is a mySociety "policy": a set of Commons divisions
on one subject, each tagged with which way a vote counts. A member's position
on the statement is nothing more than their votes on those divisions:

    position = (votes for - votes against) / (votes for + against + abstained)

    +1 = always voted for it      -1 = always voted against      None = never voted

Direct action gets the credit, in three ways:
  * only "scoring" votes count — mySociety's term for votes that USE the powers
    of Parliament (a bill stage, an amendment, an order). Motions that merely
    express a view ("this House regrets…") are excluded from the score;
  * absences count for nothing either way. A member is placed by the votes they
    cast, and the app shows how many that was;
  * decisions taken without a division ("agreements") are left out. mySociety
    includes a few in its own summaries, but nobody individually did anything,
    so they are not evidence about an individual here. This is the one place
    these numbers deliberately differ from TheyWorkForYou's.

What is ours and what is not: the grouping of votes into statements, and which
way each vote counts, is mySociety's published editorial work. Everything WE
decided lives in one file, analysis/quiz_editorial.json — wording fixes and the
compass axis each statement belongs to — so it can be audited in one place.

Usage:
    python -m analysis.positions
    python -m analysis.positions --no-fetch          # use the cache as it is
    python -m analysis.positions --out app/quiz.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analysis import mysociety

EDITORIAL = Path(__file__).with_name("quiz_editorial.json")
CHAMBER = "commons"
# A statement is only asked if it has at least this many scoring votes in the
# CURRENT parliament. Half the House was first elected in 2024; anything older
# would be a question most sitting members have no record on.
MIN_TERM_SCORING_VOTES = 1

# one character per scoring division, in date order
FOR, AGAINST, ABSTAIN, ABSENT, NOT_MEMBER = "f", "a", "b", "x", "."


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)   # md links
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_link(text: str) -> str:
    m = re.search(r"\((https?://[^)\s]+)\)", text or "")
    return m.group(1) if m else ""


def position(codes: str):
    """(position in [-1, 1] or None, votes cast) from a string of vote codes."""
    f, a, b = codes.count(FOR), codes.count(AGAINST), codes.count(ABSTAIN)
    cast = f + a + b
    if not cast:
        return None, 0
    return round((f - a) / cast, 3), cast


def vote_code(effective_vote: str, alignment: str) -> str:
    """Translate an aye/no on a division into for/against the STATEMENT.

    `alignment` is mySociety's tag on the division: "agree" means voting aye
    supports the policy, "against" means voting aye opposes it.
    """
    v = (effective_vote or "").lower()
    if v == "abstain":
        return ABSTAIN
    if v == "absent":
        return ABSENT
    if v not in ("aye", "no"):
        return ABSENT
    supports = (v == "aye") == (alignment == "agree")
    return FOR if supports else AGAINST


def select_statements(policies: list, term_start: str, editorial: dict) -> list:
    """Policies with enough scoring votes this parliament, as quiz statements."""
    wording = editorial.get("wording", {})
    compass = editorial.get("compass", {})
    excluded = editorial.get("exclude", {})
    out = []
    for p in policies:
        if p.get("chamber_slug") != CHAMBER or p.get("status") != "active":
            continue
        if str(p["id"]) in excluded:
            continue
        scoring = [l for l in p["division_links"] if l.get("strength") == "strong"]
        in_term = [l for l in scoring if str(l["decision"]["date"]) >= term_start]
        if len(in_term) < MIN_TERM_SCORING_VOTES:
            continue
        scoring.sort(key=lambda l: (str(l["decision"]["date"]),
                                    l["decision"]["division_number"]))
        source_text = _clean(p.get("context_description", "")).rstrip(".")
        fix = wording.get(str(p["id"]), {})
        axes = compass.get(str(p["id"]), {})
        out.append({
            "id": p["id"],
            "name": _clean(p.get("name", "")),
            "text": fix.get("text", source_text),
            "sourceText": source_text,
            "detail": _clean(p.get("policy_description", "")),
            "link": _first_link(html.unescape(p.get("policy_description", ""))),
            "group": (p.get("groups") or [{}])[0].get("description", ""),
            "freeVote": bool(p.get("free_vote_parties")),
            "econ": axes.get("econ", 0),
            "social": axes.get("social", 0),
            "termVotes": len(in_term),
            "divisions": [{
                "key": l["decision"]["key"],
                "date": str(l["decision"]["date"]),
                "number": int(l["decision"]["division_number"]),
                "title": _clean(l["decision"].get("division_name", "")),
                "alignment": l["alignment"],
            } for l in scoring],
        })
    out.sort(key=lambda s: (s["group"], s["name"]))
    return out


def build(cache_dir: Path, out_path: Path, fetch: bool = True) -> dict:
    import pandas as pd

    if fetch:
        mysociety.fetch(cache_dir)
    editorial = json.loads(EDITORIAL.read_text(encoding="utf-8")) if EDITORIAL.exists() else {}
    people = mysociety.People(cache_dir)
    term_start = people.term_start(CHAMBER)
    statements = select_statements(mysociety.load_policies(cache_dir), term_start, editorial)
    if not statements:
        raise SystemExit("No policies with scoring votes in the current parliament.")

    # division key -> [(statement index, slot in that statement, alignment)]
    wanted = defaultdict(list)
    for si, s in enumerate(statements):
        for di, d in enumerate(s["divisions"]):
            wanted[d["key"]].append((si, di, d["alignment"]))

    votes = mysociety.load_table(cache_dir, "votes")
    votes = votes[votes["division_key"].isin(wanted.keys())][
        ["division_key", "person_id", "effective_vote"]]
    rows = list(votes.itertuples(index=False, name=None))

    # Divisions the bulk table doesn't carry are fetched one by one.
    present = set(votes["division_key"].unique())
    backfilled = 0
    for si, s in enumerate(statements):
        for d in s["divisions"]:
            if d["key"] in present:
                continue
            extra = mysociety.division_votes(cache_dir, d["key"], CHAMBER, d["date"],
                                             d["number"], offline=not fetch)
            rows.extend((d["key"], pid, vote) for pid, vote in extra)
            present.add(d["key"])
            backfilled += bool(extra)

    members = people.current_members(CHAMBER)
    index = {m["person_id"]: i for i, m in enumerate(members)}
    # every member starts as "not a member at the time" for every division
    grid = [[[NOT_MEMBER] * len(s["divisions"]) for s in statements] for _ in members]
    for key, pid, vote in rows:
        mi = index.get(int(pid))
        if mi is None:
            continue
        for si, di, alignment in wanted[key]:
            grid[mi][si][di] = vote_code(vote, alignment)

    out_members = []
    for mi, m in enumerate(members):
        codes = ["".join(c) for c in grid[mi]]
        pos = [position(c)[0] for c in codes]
        out_members.append({
            "id": m["person_id"],
            "mnis": m["ids"].get("mnis", ""),
            "name": m["name"],
            "party": m["party"],
            "area": m["area"],
            "gss": m["gss"],
            "since": people.first_elected(m["person_id"], CHAMBER),
            "pos": pos,
            "votes": codes,
        })

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "votesAsOf": mysociety.cache_date(cache_dir),
        "chamber": mysociety.CHAMBER_PARLIAMENT[CHAMBER],
        "termStart": term_start,
        "source": {
            "name": "TheyWorkForYou Votes (mySociety)",
            "url": mysociety.VOTES_BASE,
            "note": ("Statements, and which way each vote counts, are mySociety's "
                     "published policy groupings. Only scoring votes are used."),
        },
        "codes": {"for": FOR, "against": AGAINST, "abstain": ABSTAIN,
                  "absent": ABSENT, "notMember": NOT_MEMBER},
        "statements": statements,
        "members": out_members,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    covered = [sum(1 for p in m["pos"] if p is not None) for m in out_members]
    none = sum(1 for c in covered if c == 0)
    covered.sort()
    print(f"Quiz: {len(statements)} statements x {len(out_members)} sitting MPs "
          f"-> {out_path} ({out_path.stat().st_size / 1024:,.0f} KB)")
    print(f"  parliament began {term_start} | votes as of {payload['votesAsOf']}")
    print(f"  statements an MP has a record on: median {covered[len(covered) // 2]}, "
          f"min {covered[0]}, max {covered[-1]} | {none} MPs have no record at all")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build quiz statements and MP positions.")
    ap.add_argument("--cache", default=str(mysociety.DEFAULT_CACHE))
    ap.add_argument("--out", default="app/quiz.json")
    ap.add_argument("--no-fetch", action="store_true",
                    help="don't refresh the mySociety cache first")
    a = ap.parse_args(argv)
    build(Path(a.cache), Path(a.out), fetch=not a.no_fetch)


if __name__ == "__main__":
    main()
