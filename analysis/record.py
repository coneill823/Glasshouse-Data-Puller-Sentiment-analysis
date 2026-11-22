#!/usr/bin/env python3
"""
The voting record, computed from mySociety's complete vote tables.

Same definitions as analysis/behaviour.py — turnout, voting with the party,
breaking with it, being on the winning side — but on better inputs, for the
three chambers mySociety covers (Commons, Scottish Parliament, Senedd):

  * ELIGIBILITY IS KNOWN, not inferred. The table has a row for every member
    entitled to vote in a division, marked "absent" when they didn't. The
    scraped data only records who voted, so behaviour.py has to reconstruct
    spells of service from gaps; here there is nothing to reconstruct.
  * PARTY IS THE PARTY AT THE TIME, for every chamber. Each vote points at the
    membership it was cast under, so a member who has since defected, lost the
    whip or regained it is judged against the line they were actually under.

Nothing here is a judgement. A party's "line" on a division is simply what
most of its members who took part chose to do.

The Northern Ireland Assembly is not covered — mySociety does not parse its
divisions — so its record still comes from behaviour.py over the scraped data.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from analysis import mysociety

# A party's line only exists if enough of its members took part and most of
# them did the same thing — otherwise there is nothing to break with.
MIN_PARTY_VOTERS = 3
MAX_RECEIPTS = 25

# Sitting without a whip: there is no line for these to defy.
UNWHIPPED = {"", "independent", "speaker", "deputy-speaker", "crossbench",
             "bishop", "judge", "non-affiliated", "none", "unknown"}
# Separate labels that take one whip. Labour/Co-operative MPs are Labour MPs
# for every voting purpose; treating them as a party of their own would
# measure them against each other instead of against Labour.
WHIP_ALIAS = {"labourco-operative": "labour"}


def whip_group(party_slug: str) -> str:
    """The group whose line a member is expected to follow ('' if none)."""
    p = (party_slug or "").strip().lower()
    p = WHIP_ALIAS.get(p, p)
    if p in UNWHIPPED or p.startswith("independent"):
        return ""
    return p


def party_lines(cast):
    """Series indexed by (division_key, group) -> 'aye' / 'no' / 'abstain'.

    `cast` holds one row per member who took part (absences removed) with
    columns division_key, group, choice. A line exists where at least
    MIN_PARTY_VOTERS of the group took part and more than half chose one option.
    """
    whipped = cast[cast["group"] != ""]
    counts = (whipped.groupby(["division_key", "group", "choice"]).size()
              .unstack(fill_value=0))
    total = counts.sum(axis=1)
    top = counts.max(axis=1)
    line = counts.idxmax(axis=1)
    return line[(total >= MIN_PARTY_VOTERS) & (top * 2 > total)]


def compute(votes, divisions, party_of_membership, term_start: str) -> dict:
    """{person_id: record} from a chamber's votes.

    votes      DataFrame: division_key, person_id, membership_id, effective_vote
               (aye / no / abstain / absent), one row per ELIGIBLE member
    divisions  DataFrame: key, date (ISO str), division_name
    party_of_membership  callable: membership_id -> party slug at that time
    term_start ISO date; turnout is measured from here
    """
    import pandas as pd

    v = votes[["division_key", "person_id", "membership_id", "effective_vote"]].copy()
    v = v.merge(divisions[["key", "date", "division_name"]],
                left_on="division_key", right_on="key", how="inner")
    v["choice"] = v["effective_vote"].astype(str).str.lower()
    parties = {m: whip_group(party_of_membership(m)) for m in v["membership_id"].unique()}
    v["group"] = v["membership_id"].map(parties)
    took_part = v["choice"].isin(["aye", "no", "abstain"])
    cast = v[took_part]

    # --- the party's line, and the chamber's decision, on each division ---
    lines = party_lines(cast).rename("line").reset_index()
    cast = cast.merge(lines, on=["division_key", "group"], how="left")
    sides = (cast[cast["choice"].isin(["aye", "no"])]
             .groupby(["division_key", "choice"]).size().unstack(fill_value=0))
    for col in ("aye", "no"):
        if col not in sides:
            sides[col] = 0
    result = pd.Series("", index=sides.index)
    result[sides["aye"] > sides["no"]] = "aye"
    result[sides["no"] > sides["aye"]] = "no"
    cast = cast.merge(result.rename("result"), left_on="division_key",
                      right_index=True, how="left")

    has_line = cast["line"].notna()
    cast["with_party"] = has_line & (cast["choice"] == cast["line"])
    cast["broke"] = has_line & (cast["choice"] != cast["line"])
    decided = cast["choice"].isin(["aye", "no"]) & cast["result"].isin(["aye", "no"])
    cast["decided"] = decided
    cast["with_result"] = decided & (cast["choice"] == cast["result"])

    out = {}
    agg = cast.groupby("person_id").agg(
        votes_cast=("choice", "size"),
        party_line_divisions=("line", "count"),
        with_party=("with_party", "sum"),
        rebellions=("broke", "sum"),
        decided=("decided", "sum"),
        with_result=("with_result", "sum"),
        first_vote=("date", "min"),
        last_vote=("date", "max"),
    )
    for pid, r in agg.iterrows():
        out[int(pid)] = {
            "votes_cast": int(r.votes_cast),
            "party_line_divisions": int(r.party_line_divisions),
            "with_party": int(r.with_party),
            "rebellions": int(r.rebellions),
            "chamber_decided_divisions": int(r.decided),
            "with_chamber": int(r.with_result),
            "first_vote": r.first_vote, "last_vote": r.last_vote,
            "term_votes": 0, "divisions_eligible": 0, "receipts": [],
        }

    # --- turnout over the current term: every row is a division they could
    #     have voted in, so this is a true rate, not an estimate ---
    term = v[v["date"] >= term_start]
    eligible = term.groupby("person_id").size()
    turned_out = term[term["choice"].isin(["aye", "no", "abstain"])].groupby("person_id").size()
    for pid, n in eligible.items():
        rec = out.setdefault(int(pid), {
            "votes_cast": 0, "party_line_divisions": 0, "with_party": 0,
            "rebellions": 0, "chamber_decided_divisions": 0, "with_chamber": 0,
            "first_vote": "", "last_vote": "", "term_votes": 0,
            "divisions_eligible": 0, "receipts": []})
        rec["divisions_eligible"] = int(n)
        rec["term_votes"] = int(turned_out.get(pid, 0))

    # --- receipts: every break with the party, newest first ---
    broke = cast[cast["broke"]].sort_values(["person_id", "date"], ascending=[True, False])
    for pid, grp in broke.groupby("person_id", sort=False):
        out[int(pid)]["receipts"] = [
            [row.date, row.division_name[:160], row.choice, row.line, row.division_key]
            for row in grp.head(MAX_RECEIPTS).itertuples()]
    return out


def plain_title(text: str) -> str:
    """A division's title as words. The Lords' titles arrive with markup in
    them ("Bill - <i>Motion to Agree</i>") and some with entities."""
    text = re.sub(r"<[^>]*>", "", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def chamber_record(cache_dir: Path, chamber: str, people=None) -> dict:
    """Voting record for everyone who has voted in `chamber`."""
    people = people or mysociety.People(cache_dir)
    divisions = mysociety.load_table(cache_dir, "divisions")
    divisions = divisions[divisions["chamber_slug"] == chamber].copy()
    divisions["date"] = divisions["date"].astype(str)
    divisions["division_name"] = divisions["division_name"].map(plain_title)
    votes = mysociety.load_table(cache_dir, "votes")
    votes = votes[votes["division_key"].isin(set(divisions["key"]))]
    return compute(votes, divisions, people.party_of_membership,
                   people.term_start(chamber))


def signatures(cache_dir: Path, chamber: str, since: str) -> dict:
    """{person_id: {"proposed": n, "signed": n}} for motions since a date.

    Early Day Motions (and prayers against statutory instruments) are the one
    recorded act that is entirely the member's own choice: unwhipped, public,
    and attributable. They are also cheap — signing changes no law — so they
    are reported as activity and never fed into a position.
    """
    st = mysociety.load_table(cache_dir, "statements")
    sg = mysociety.load_table(cache_dir, "signatures")
    st = st[(st["chamber_slug"] == chamber) & (st["type"] != "letter")
            & (st["date"].astype(str) >= since)]
    sg = sg[sg["statement_id"].isin(set(st["id"])) & ~sg["withdrawn"]
            & sg["person_id"].notna()]
    out = {}
    primary = sg["extra_info"].map(
        lambda e: bool(e.get("is_primary")) if isinstance(e, dict) else False)
    for pid, is_primary in zip(sg["person_id"].astype(int), primary):
        rec = out.setdefault(pid, {"proposed": 0, "signed": 0})
        rec["proposed" if is_primary else "signed"] += 1
    return out
