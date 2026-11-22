#!/usr/bin/env python3
"""
Who can I vote for: the elections coming up and the people standing in them.

Everything here is Democracy Club's open data (CC BY 4.0):

  * which elections are coming, and for which ward, division or constituency:
    their Every Election register;
  * who is standing: their candidate register, which volunteers compile from
    each council's official notices. Close to an election it is complete; a
    few months out it holds only the candidates announced so far.

Nothing is graded here, because nothing can be: standing for election is not
an act in office. A candidate who HAS held office is linked to that record by
the TheyWorkForYou id Democracy Club holds for them; everyone else is shown
as having no record yet, which is simply true.

Only what a candidate has put on a ballot paper is kept: their name, the
party they stand for, and where. The register also carries email addresses,
dates of birth and social-media accounts; none of that is read.

Each ballot is keyed by the official code of its area. Those are the codes
postcodes.io returns for a postcode, which is how the apps find the right
ballots without sending anyone's postcode anywhere else.

Usage:
    python -m analysis.candidates              # prints what is coming up
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from datetime import date
from pathlib import Path

from analysis import mysociety

ELECTIONS_API = "https://elections.democracyclub.org.uk/api/elections/"
CANDIDATES_CSV = "https://candidates.democracyclub.org.uk/data/export_csv/"
WHO_CAN_I_VOTE_FOR = "https://whocanivotefor.co.uk/elections/"
DEFAULT_CACHE = Path("data/_democracyclub")
MAX_AGE_HOURS = 20

# The first part of an election id -> what is being elected.
KINDS = {
    "parl": "UK Parliament",
    "sp": "Scottish Parliament",
    "senedd": "Senedd",
    "nia": "Northern Ireland Assembly",
    "local": "Council",
    "mayor": "Mayor",
    "pcc": "Police and Crime Commissioner",
    "gla": "London Assembly",
    "europarl": "European Parliament",
}


def _get(url: str, params: dict, cache: Path, offline: bool) -> str:
    """Fetch through a day-long cache, falling back to an older copy."""
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    if fresh or offline:
        return cache.read_text(encoding="utf-8") if cache.exists() else ""
    import requests
    try:
        r = requests.get(url, params=params, timeout=120,
                         headers={"User-Agent": mysociety.USER_AGENT})
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding="utf-8")
        return r.text
    except Exception as e:  # network or HTTP
        print(f"  ! could not fetch {url} ({e})"
              f"{'; using the copy already here' if cache.exists() else ''}", file=sys.stderr)
        return cache.read_text(encoding="utf-8") if cache.exists() else ""


def _gss(identifier: str) -> str:
    """'gss:E05011843' -> 'E05011843'. Other schemes are not postcode codes."""
    scheme, _, code = (identifier or "").partition(":")
    return code if scheme == "gss" else ""


def upcoming_ballots(cache_dir: Path, today: str, offline: bool = False) -> list:
    """Every ballot from today on, soonest first."""
    out, page = [], 0
    params = {"future": 1, "limit": 100}
    while True:
        text = _get(ELECTIONS_API, {**params, "offset": page * 100},
                    cache_dir / f"elections_{page}.json", offline)
        if not text:
            break
        data = json.loads(text)
        for e in data.get("results", []):
            if e.get("group_type") is not None:        # a grouping, not a ballot paper
                continue
            day = e.get("poll_open_date") or ""
            if day < today:
                continue
            division = e.get("division") or {}
            organisation = e.get("organisation") or {}
            out.append({
                "id": e["election_id"],
                "date": day,
                "kind": KINDS.get(e["election_id"].split(".")[0], "Election"),
                "title": e.get("election_title") or "",
                "body": organisation.get("common_name") or organisation.get("official_name") or "",
                "area": division.get("name") or organisation.get("common_name") or "",
                # the area's own code, or for a whole-council or mayoral vote the council's
                "gss": _gss(division.get("official_identifier"))
                       or _gss(organisation.get("official_identifier")),
                "seats": int(e.get("seats_contested") or 1),
                "byElection": ".by." in e["election_id"],
                "cancelled": bool(e.get("cancelled")),
            })
        page += 1
        if not data.get("next") or page > 200:
            break
    out.sort(key=lambda b: (b["date"], b["id"]))
    return out


def candidates_on(cache_dir: Path, day: str, offline: bool = False) -> dict:
    """{ballot id: [candidate, ...]} for everything voted on that day."""
    text = _get(CANDIDATES_CSV,
                {"election_date": day, "format": "csv", "extra_fields": ["twfy_id"]},
                cache_dir / f"candidates_{day}.csv", offline)
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        ballot = row.get("ballot_paper_id") or ""
        name = (row.get("person_name") or "").strip()
        if not ballot or not name:
            continue
        twfy = (row.get("twfy_id") or "").strip()
        out.setdefault(ballot, []).append({
            "name": name,
            "party": (row.get("party_name") or "").strip() or "Independent",
            # TheyWorkForYou's id for them, if they have ever sat somewhere it covers
            "record": int(twfy) if twfy.isdigit() else None,
        })
    for people in out.values():
        people.sort(key=lambda c: c["name"].split()[-1].lower())
    return out


def build(cache_dir: Path = DEFAULT_CACHE, today: str = "", fetch: bool = True,
          known_ids=None) -> dict:
    """The `elections` block of app/data.json.

    `known_ids` is the set of person ids the app holds a record for; a link is
    only kept where it leads somewhere.
    """
    today = today or date.today().isoformat()
    ballots = upcoming_ballots(cache_dir, today, offline=not fetch)
    by_day = {}
    for b in ballots:
        if b["date"] not in by_day:
            by_day[b["date"]] = candidates_on(cache_dir, b["date"], offline=not fetch)
            if fetch:
                time.sleep(0.2)
        people = by_day[b["date"]].get(b["id"], [])
        for c in people:
            if known_ids is not None and c["record"] not in known_ids:
                c["record"] = None
        b["candidates"] = people
        b["url"] = WHO_CAN_I_VOTE_FOR + b["id"] + "/"
    return {
        "asOf": today,
        "source": "Democracy Club (CC BY 4.0)",
        "ballots": ballots,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Show the elections and candidates coming up.")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    e = build(Path(a.cache), fetch=not a.no_fetch)
    known = sum(1 for b in e["ballots"] for c in b["candidates"] if c["record"])
    print(f"{len(e['ballots'])} ballots coming up, "
          f"{sum(len(b['candidates']) for b in e['ballots'])} candidates so far "
          f"({known} with a TheyWorkForYou id)")
    for b in e["ballots"]:
        print(f"  {b['date']} {b['kind']:8} {b['body'][:26]:26} {b['area'][:28]:28} "
              f"{b['gss']:10} {len(b['candidates']):2} standing"
              f"{' CANCELLED' if b['cancelled'] else ''}")


if __name__ == "__main__":
    main()
