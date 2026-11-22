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

Two lists of statements come out. The core list is every policy with a scoring
vote in the CURRENT parliament: every sitting MP could have voted on those.
The second list is every other policy that has ever had one — tuition fees,
the Iraq war, identity cards, same-sex marriage. They sharpen a visitor's
place on the compass and bring in MPs' longer records and former MPs, but an
MP elected since simply has no position on them, and is never marked down for
that (see `could_vote` in analysis/quizmath.py).

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


def _statement(p: dict, scoring: list, in_term: int, editorial: dict) -> dict:
    wording = editorial.get("wording", {})
    axes = editorial.get("compass", {}).get(str(p["id"]), {})
    scoring = sorted(scoring, key=lambda l: (str(l["decision"]["date"]),
                                             l["decision"]["division_number"]))
    source_text = _clean(p.get("context_description", "")).rstrip(".")
    fix = wording.get(str(p["id"]), {})
    return {
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
        "termVotes": in_term,
        "divisions": [{
            "key": l["decision"]["key"],
            "date": str(l["decision"]["date"]),
            "number": int(l["decision"]["division_number"]),
            "title": _clean(l["decision"].get("division_name", "")),
            "alignment": l["alignment"],
        } for l in scoring],
    }


def _split(policies: list, term_start: str, editorial: dict):
    """(core, more): statements voted on this parliament, and all the others."""
    excluded = editorial.get("exclude", {})
    core, more = [], []
    for p in policies:
        if p.get("chamber_slug") != CHAMBER or p.get("status") != "active":
            continue
        if str(p["id"]) in excluded:
            continue
        scoring = [l for l in p["division_links"] if l.get("strength") == "strong"]
        if not scoring:
            continue
        in_term = sum(1 for l in scoring if str(l["decision"]["date"]) >= term_start)
        target = core if in_term >= MIN_TERM_SCORING_VOTES else more
        target.append(_statement(p, scoring, in_term, editorial))
    core.sort(key=lambda s: (s["group"], s["name"]))
    # Most recently voted on first: the further back, the fewer people it reaches.
    more.sort(key=lambda s: (s["divisions"][-1]["date"], s["name"]), reverse=True)
    return core, more


def select_statements(policies: list, term_start: str, editorial: dict) -> list:
    """Policies with enough scoring votes this parliament, as quiz statements."""
    return _split(policies, term_start, editorial)[0]


def select_more(policies: list, term_start: str, editorial: dict) -> list:
    """Every other policy that has ever had a scoring vote, newest first."""
    return _split(policies, term_start, editorial)[1]


def _career(people, person_id: int) -> dict:
    """Party, seat and years of someone's time in the Commons, from the register."""
    spells = sorted((m for m in people.by_person.get(int(person_id), [])
                     if people.chamber_of(m) == CHAMBER),
                    key=lambda m: m.get("start_date", ""))
    if not spells:
        return {}
    last = spells[-1]
    post = people.posts.get(last.get("post_id"), {})
    left = last.get("end_date", "")
    return {
        "party": people.party_name(last.get("on_behalf_of_id", "") or ""),
        "area": (post.get("area") or {}).get("name", ""),
        "from": spells[0].get("start_date", "")[:4],
        "to": "" if left >= "9999" else left[:4],
        "last": left,
    }


def build(cache_dir: Path, out_path: Path, fetch: bool = True, chambers: dict = None) -> dict:
    """Write the quiz. `chambers` is the devolved legislatures' own quizzes
    (analysis/devolved.py), carried in the same file."""
    if fetch:
        mysociety.fetch(cache_dir)
    editorial = json.loads(EDITORIAL.read_text(encoding="utf-8")) if EDITORIAL.exists() else {}
    people = mysociety.People(cache_dir)
    term_start = people.term_start(CHAMBER)
    core, more = _split(mysociety.load_policies(cache_dir), term_start, editorial)
    if not core:
        raise SystemExit("No policies with scoring votes in the current parliament.")
    statements = core + more

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
    for s in statements:
        for d in s["divisions"]:
            if d["key"] in present:
                continue
            extra = mysociety.division_votes(cache_dir, d["key"], CHAMBER, d["date"],
                                             d["number"], offline=not fetch)
            rows.extend((d["key"], pid, vote) for pid, vote in extra)
            present.add(d["key"])
            backfilled += bool(extra)

    # One row of vote codes per person, sitting or not. Everyone starts as
    # "not a member at the time" for every division.
    grid = {}
    for key, pid, vote in rows:
        codes = grid.get(int(pid))
        if codes is None:
            codes = grid[int(pid)] = [[NOT_MEMBER] * len(s["divisions"]) for s in statements]
        for si, di, alignment in wanted[key]:
            codes[si][di] = vote_code(vote, alignment)

    n_core = len(core)
    blank = [[NOT_MEMBER] * len(s["divisions"]) for s in statements]

    def record(person_id: int) -> dict:
        """pos/votes for the core list, morePos/moreVotes for the rest. A run
        of divisions someone was never a member for is stored as "" - most of
        the grid, for anyone elected recently or long gone."""
        codes = ["".join(c) for c in grid.get(person_id, blank)]
        codes = ["" if not c.strip(NOT_MEMBER) else c for c in codes]
        pos = [position(c)[0] for c in codes]
        out = {"pos": pos[:n_core], "votes": codes[:n_core]}
        if any(codes[n_core:]):
            out["morePos"] = pos[n_core:]
            out["moreVotes"] = codes[n_core:]
        return out

    members = people.current_members(CHAMBER)
    out_members = []
    for m in members:
        out_members.append({
            "id": m["person_id"],
            "mnis": m["ids"].get("mnis", ""),
            "name": m["name"],
            "party": m["party"],
            "area": m["area"],
            "gss": m["gss"],
            "since": people.first_elected(m["person_id"], CHAMBER),
            **record(m["person_id"]),
        })

    # Former MPs: anyone with a vote on a statement who is not sitting now.
    sitting = {m["person_id"] for m in members}
    former = []
    for person_id in sorted(set(grid) - sitting):
        career = _career(people, person_id)
        rec = record(person_id)
        if not career or not any(p is not None for p in rec["pos"] + rec.get("morePos", [])):
            continue
        former.append({
            "id": person_id,
            "name": people.name(person_id, on=min(career["last"], "9998")),
            "party": career["party"],
            "area": career["area"],
            "from": career["from"],
            "to": career["to"],
            **rec,
        })
    former.sort(key=lambda m: m["name"])

    payload = {
        # 2: adds moreStatements, former and chambers. Everything a version-1
        # reader used is unchanged, so it keeps working and ignores the rest.
        "schema": 2,
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
        "statements": core,
        "members": out_members,
        "moreStatements": more,
        "former": former,
        "chambers": chambers or {},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    covered = sorted(sum(1 for p in m["pos"] if p is not None) for m in out_members)
    none = sum(1 for c in covered if c == 0)
    longer = sum(1 for m in out_members if "morePos" in m)
    print(f"Quiz: {len(core)} statements x {len(out_members)} sitting MPs "
          f"-> {out_path} ({out_path.stat().st_size / 1024:,.0f} KB)")
    print(f"  parliament began {term_start} | votes as of {payload['votesAsOf']}")
    print(f"  statements an MP has a record on: median {covered[len(covered) // 2]}, "
          f"min {covered[0]}, max {covered[-1]} | {none} MPs have no record at all")
    print(f"  {len(more)} more statements from earlier parliaments: {longer} sitting MPs "
          f"and {len(former)} former MPs have a record on them")
    for parliament, quiz in (chambers or {}).items():
        print(f"  {parliament}: {len(quiz['statements'])} questions x {len(quiz['members'])} members")
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
