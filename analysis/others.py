#!/usr/bin/env python3
"""
Everyone with a record who is not a sitting member of one of the four elected
chambers: former MPs, former MSPs and Members of the Senedd, and the House of
Lords.

They are in the same open data as sitting members and their records are
worked out by the same code (analysis/record.py). Former members matter
because they stand again; peers because they vote on the same laws, though
nobody votes for them.

A person can appear here and among the sitting members: a former MP who is
now an MSP has a Commons record and a Holyrood one. Each is a separate entry,
labelled with the chamber it comes from.
"""
from __future__ import annotations

from pathlib import Path

from analysis import mysociety, record

# Enough to show what kind of rebel someone was without carrying their whole
# history: the full list is one tap away on TheyWorkForYou.
MAX_RECEIPTS = 6
MAX_TITLE = 110
LORDS = "House of Lords"


def _pct(n, d):
    return round(100 * n / d, 1) if d else None


def _row(person_id: int, name: str, party: str, area: str, parliament: str,
         status: str, since: str, until: str, r: dict) -> dict:
    row = {
        "id": person_id,
        "name": name,
        "party": party,
        "area": area,
        "parliament": parliament,
        "status": status,                 # "former" or "peer"
        "since": since,
        "votesCast": r.get("votes_cast", 0),
        "partyAgreement": _pct(r.get("with_party", 0), r.get("party_line_divisions", 0)),
        "partyLineDivisions": r.get("party_line_divisions", 0),
        "chamberAgreement": _pct(r.get("with_chamber", 0), r.get("chamber_decided_divisions", 0)),
        "rebellions": r.get("rebellions", 0),
        "receipts": [[d, t[:MAX_TITLE], mine, theirs, key]
                     for d, t, mine, theirs, key in r.get("receipts", [])[:MAX_RECEIPTS]],
    }
    if until:
        row["until"] = until
    return row


def _spells(people, person_id: int, chamber: str) -> list:
    return sorted((m for m in people.by_person.get(int(person_id), [])
                   if people.chamber_of(m) == chamber),
                  key=lambda m: m.get("start_date", ""))


def former_members(people, chamber: str, records: dict, sitting: set) -> list:
    """Everyone who has voted in `chamber` and no longer sits there."""
    parliament = mysociety.CHAMBER_PARLIAMENT[chamber]
    out = []
    for person_id, r in records.items():
        if person_id in sitting or not r.get("votes_cast"):
            continue
        spells = _spells(people, person_id, chamber)
        if not spells:
            continue
        last = spells[-1]
        left = last.get("end_date", "")
        if left >= "9999":                 # the register says they still sit
            continue
        post = people.posts.get(last.get("post_id"), {})
        out.append(_row(
            person_id,
            people.name(person_id, on=left),
            people.party_name(last.get("on_behalf_of_id", "") or ""),
            (post.get("area") or {}).get("name", ""),
            parliament, "former",
            spells[0].get("start_date", "")[:4], left[:4], r))
    out.sort(key=lambda m: m["name"])
    return out


def peers(cache_dir: Path, people, parliament_began: str) -> tuple:
    """(sitting peers with their record, the chamber's summary)."""
    import html

    divisions = mysociety.load_table(cache_dir, "divisions")
    divisions = divisions[divisions["chamber_slug"] == "lords"].copy()
    divisions["date"] = divisions["date"].astype(str)
    divisions["division_name"] = divisions["division_name"].map(lambda s: html.unescape(s or ""))
    votes = mysociety.load_table(cache_dir, "votes")
    votes = votes[votes["division_key"].isin(set(divisions["key"]))]
    # The Lords has no elections, so "this term" is the current parliament.
    records = record.compute(votes, divisions, people.party_of_membership, parliament_began)

    out = []
    for m in people.current_members("lords"):
        r = records.get(m["person_id"], {})
        spells = _spells(people, m["person_id"], "lords")
        row = _row(m["person_id"], people.name(m["person_id"], as_peer=True) or m["name"],
                   m["party"], "", LORDS, "peer",
                   (spells[0].get("start_date", "") if spells else "")[:4], "", r)
        row["termVotes"] = r.get("term_votes", 0)
        row["eligible"] = r.get("divisions_eligible", 0)
        row["turnout"] = _pct(row["termVotes"], row["eligible"])
        out.append(row)
    out.sort(key=lambda m: m["name"])

    def median(values):
        v = sorted(x for x in values if x is not None)
        return round(v[len(v) // 2], 1) if v else None

    summary = {
        "slug": "lords", "role": "Peer", "house": LORDS,
        "termStart": parliament_began,
        "members": len(out),
        "votesSource": "mysociety",
        "termDivisions": max((m["eligible"] for m in out), default=0),
        "turnout": median(m["turnout"] for m in out),
        "partyAgreement": median(m["partyAgreement"] for m in out
                                 if m["partyLineDivisions"] >= 20),
        "chamberAgreement": median(m["chamberAgreement"] for m in out),
    }
    return out, summary
