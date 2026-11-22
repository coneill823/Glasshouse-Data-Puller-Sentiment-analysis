#!/usr/bin/env python3
"""
mySociety open data: the voting record, policy groupings and member register.

Two things come from here that the Glasshouse scrapers cannot supply.

1. A complete, daily-refreshed voting record for the Commons, the Scottish
   Parliament and the Senedd as one small file — including a row for every
   member who was ELIGIBLE to vote in a division and didn't, and the party each
   member belonged to at the time. Both are things the per-division scrape has
   to approximate.

2. TheyWorkForYou's "policies": divisions grouped by subject, each tagged with
   which way a vote counts and whether it is a "scoring" vote (one that uses the
   powers of Parliament) or merely an "informative" one. That grouping is an
   editorial judgement, and it is deliberately somebody else's: a non-partisan
   charity's, published in full, with every vote listed. See docs/METHODS.md.

What is NOT here: Northern Ireland Assembly divisions (mySociety does not parse
them) and policies for any chamber but the Commons. Those gaps are real and are
reported as gaps, not papered over.

Sources and licences
    votes.theyworkforyou.com   bulk tables + policies.json (mySociety)
    mysociety/parlparse        members/people.json  — CC BY 4.0 as "UK
                               Politician data" on pages.mysociety.org
    Parliamentary material within is under the Open Parliament Licence.

Usage:
    python -m analysis.mysociety            # download / refresh the cache
    python -m analysis.mysociety --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

VOTES_BASE = "https://votes.theyworkforyou.com"
PEOPLE_URL = ("https://raw.githubusercontent.com/mysociety/parlparse/"
              "master/members/people.json")
# Only the tables the analysis actually reads; the site publishes more.
TABLES = ("divisions", "votes", "statements", "signatures")
DEFAULT_CACHE = Path("data/_mysociety")
# The bulk files are rebuilt once a day, early morning UK time.
MAX_AGE_HOURS = 20
USER_AGENT = "Glasshouse/1.0 (+https://github.com/coneill823/Glasshouse-Data-Puller-Sentiment-analysis)"

# chamber slug used by TheyWorkForYou Votes -> organisation id in people.json
CHAMBER_ORG = {
    "commons": "house-of-commons",
    "scotland": "scottish-parliament",
    "senedd": "welsh-parliament",
    "ni": "northern-ireland-assembly",
}
# -> the legislature names the Glasshouse scrapers write
CHAMBER_PARLIAMENT = {
    "commons": "UK Parliament",
    "scotland": "Scottish Parliament",
    "senedd": "Welsh Parliament (Senedd)",
    "ni": "NI Assembly",
}
# identifier scheme in people.json -> what it is
ID_SCHEMES = {
    "datadotparl_id": "mnis",          # UK Parliament Members API id
    "scotparl_id": "scotparl",
    "senedd": "senedd",
    "data.niassembly.gov.uk": "niassembly",
    "wikidata": "wikidata",
}
ELECTION_REASONS = {"general_election", "regional_election", "election"}


# --- download ---------------------------------------------------------------
def _sources():
    yield "policies.json", f"{VOTES_BASE}/policies.json"
    yield "people.json", PEOPLE_URL
    for t in TABLES:
        yield f"{t}.parquet", f"{VOTES_BASE}/static/data/{t}.parquet"


def fetch(cache_dir: Path = DEFAULT_CACHE, max_age_hours: float = MAX_AGE_HOURS,
          force: bool = False, quiet: bool = False) -> Path:
    """Download anything missing or stale into the cache. Returns the cache dir.

    A failed refresh of a file we already hold keeps the old copy and says so,
    rather than leaving the pipeline with nothing: yesterday's votes are a
    better answer than a crash.
    """
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for name, url in _sources():
        dest = cache_dir / name
        fresh = dest.exists() and (now - dest.stat().st_mtime) < max_age_hours * 3600
        if fresh and not force:
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with requests.get(url, stream=True, timeout=120,
                              headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            os.replace(tmp, dest)   # atomic: never leave a half-written file
            if not quiet:
                print(f"  fetched {name} ({dest.stat().st_size / 1024:,.0f} KB)")
        except Exception as e:  # network, HTTP, disk
            if tmp.exists():
                tmp.unlink()
            if dest.exists():
                age = (now - dest.stat().st_mtime) / 3600
                print(f"  ! could not refresh {name} ({e}); using the copy "
                      f"from {age:.0f}h ago", file=sys.stderr)
            else:
                raise SystemExit(f"Could not download {name} from {url}: {e}")
    return cache_dir


def cache_date(cache_dir: Path = DEFAULT_CACHE) -> str:
    """ISO date of the vote data in the cache (when it was downloaded)."""
    p = cache_dir / "votes.parquet"
    if not p.exists():
        return ""
    return date.fromtimestamp(p.stat().st_mtime).isoformat()


def load_table(cache_dir: Path, name: str):
    import pandas as pd
    return pd.read_parquet(cache_dir / f"{name}.parquet")


def load_policies(cache_dir: Path) -> list:
    with open(cache_dir / "policies.json", encoding="utf-8") as f:
        return json.load(f)


def division_votes(cache_dir: Path, key: str, chamber: str, day: str,
                   number: int, offline: bool = False) -> list:
    """[(person_id, effective_vote), ...] for one division, from its own page.

    The bulk vote table omits a handful of the very earliest divisions (four of
    the 230 the quiz uses, all 1997-99). The site still has them, so they are
    fetched individually and kept — otherwise a member sitting since the 1990s
    would silently lose votes that TheyWorkForYou itself counts.
    """
    store = cache_dir / "divisions"
    path = store / f"{key}.json"
    if not path.exists():
        if offline:
            return []
        import requests
        url = f"{VOTES_BASE}/decisions/division/{chamber}/{day}/{number}.json"
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            store.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text, encoding="utf-8")
        except Exception as e:
            print(f"  ! could not fetch division {key} ({e}); it will be "
                  f"missing from the record", file=sys.stderr)
            return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(int(v["person"]["id"]), str(v.get("effective_vote", "")).lower())
            for v in data.get("votes", []) if v.get("person")]


# --- the member register ----------------------------------------------------
def _num(pw_id: str) -> int:
    """'uk.org.publicwhip/person/10001' -> 10001 (the id the vote tables use)."""
    tail = str(pw_id).rsplit("/", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return int(digits) if digits else -1


class People:
    """people.json, indexed the ways the analysis needs it."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE):
        with open(cache_dir / "people.json", encoding="utf-8") as f:
            raw = json.load(f)
        self.posts = {p["id"]: p for p in raw["posts"]}
        self.orgs = {o["id"]: o.get("name", o["id"]) for o in raw["organizations"]}
        self.persons = {_num(p["id"]): p for p in raw["persons"]}
        # membership id (as the vote tables carry it) -> membership
        self.memberships = {}
        self.by_person = {}
        for m in raw["memberships"]:
            if "redirect" in m or "person_id" not in m:
                continue
            self.memberships[_num(m["id"])] = m
            self.by_person.setdefault(_num(m["person_id"]), []).append(m)

    # -- lookups --
    def chamber_of(self, membership: dict) -> str:
        org = (self.posts.get(membership.get("post_id"), {}).get("organization_id")
               or membership.get("organization_id") or "")
        for slug, org_id in CHAMBER_ORG.items():
            if org == org_id:
                return slug
        return ""

    def party_name(self, slug: str) -> str:
        return self.orgs.get(slug, slug or "")

    def party_of_membership(self, membership_id: int) -> str:
        """Party slug the member sat for under this membership — i.e. at the
        time of any vote recorded against it."""
        m = self.memberships.get(int(membership_id))
        return (m or {}).get("on_behalf_of_id", "") or ""

    def name(self, person_id: int, on: str = "", as_peer: bool = False) -> str:
        """Display name. A peer who also sits in an elected chamber (several
        MSPs do) is named as a person — "Katy Clark" — unless `as_peer`."""
        p = self.persons.get(int(person_id)) or {}
        on = on or date.today().isoformat()
        best = None
        for n in p.get("other_names", []):
            if n.get("note") != "Main":
                continue
            if n.get("start_date", "0000") <= on <= n.get("end_date", "9999"):
                best = n
        best = best or next((n for n in reversed(p.get("other_names", []))
                             if n.get("note") == "Main"), {})
        if best.get("lordname") and as_peer:
            title = f"{best.get('honorific_prefix', 'Lord')} {best['lordname']}"
            return f"{title} of {best['lordofname']}" if best.get("lordofname") else title
        surname = best.get("family_name") or best.get("lordname")
        return " ".join(x for x in (best.get("given_name"), surname) if x)

    def identifiers(self, person_id: int) -> dict:
        p = self.persons.get(int(person_id)) or {}
        out = {}
        for i in p.get("identifiers", []):
            key = ID_SCHEMES.get(i.get("scheme"))
            if key:
                out[key] = str(i.get("identifier"))
        return out

    def term_start(self, chamber: str, on: str = "") -> str:
        """Date of the most recent general election to this chamber.

        Read off the register rather than hardcoded: it is the latest date on
        which a large cohort began memberships by election.
        """
        on = on or date.today().isoformat()
        counts = {}
        for m in self.memberships.values():
            if (m.get("start_reason") in ELECTION_REASONS
                    and self.chamber_of(m) == chamber
                    and m.get("start_date", "9999") <= on):
                counts[m["start_date"]] = counts.get(m["start_date"], 0) + 1
        big = [d for d, n in counts.items() if n >= 20]   # not a by-election
        return max(big) if big else ""

    def current_members(self, chamber: str, on: str = "") -> list:
        """Everyone sitting in `chamber` on the given date (default today)."""
        on = on or date.today().isoformat()
        out = []
        for mid, m in self.memberships.items():
            if self.chamber_of(m) != chamber:
                continue
            if not (m.get("start_date", "9999") <= on <= m.get("end_date", "9999")):
                continue
            pid = _num(m["person_id"])
            post = self.posts.get(m.get("post_id"), {})
            gss = next((i["identifier"] for i in post.get("identifiers", [])
                        if i.get("scheme") == "gss"), "")
            slug = m.get("on_behalf_of_id", "") or ""
            out.append({
                "person_id": pid,
                "membership_id": mid,
                "name": self.name(pid, on),
                "party_slug": slug,
                "party": self.party_name(slug),
                "area": (post.get("area") or {}).get("name", ""),
                "gss": gss,
                "since": m.get("start_date", ""),
                "ids": self.identifiers(pid),
            })
        out.sort(key=lambda r: (r["area"], r["name"]))
        return out

    def first_elected(self, person_id: int, chamber: str) -> str:
        """Start of the member's current unbroken spell in the chamber.

        A change of party or a restored whip starts a new membership record
        without the member ever leaving, so consecutive records are chained.
        """
        ms = sorted((m for m in self.by_person.get(int(person_id), [])
                     if self.chamber_of(m) == chamber),
                    key=lambda m: m.get("start_date", ""))
        if not ms:
            return ""
        start = ms[-1].get("start_date", "")
        for prev, cur in zip(reversed(ms[:-1]), reversed(ms[1:])):
            gap_ok = prev.get("end_date", "") >= _minus_days(cur.get("start_date", ""), 45)
            if cur.get("start_reason") in ELECTION_REASONS and not gap_ok:
                break
            if not gap_ok:
                break
            start = prev.get("start_date", start)
        return start


def _minus_days(iso: str, days: int) -> str:
    from datetime import timedelta
    try:
        y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10])
        return (date(y, m, d) - timedelta(days=days)).isoformat()
    except (ValueError, IndexError):
        return iso


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download / refresh mySociety open data.")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--force", action="store_true", help="re-download everything")
    a = ap.parse_args(argv)
    cache = fetch(Path(a.cache), force=a.force)
    people = People(cache)
    print(f"Cache: {cache}  (votes as of {cache_date(cache)})")
    for chamber in CHAMBER_ORG:
        cur = people.current_members(chamber)
        print(f"  {CHAMBER_PARLIAMENT[chamber]:28} {len(cur):4} sitting | "
              f"last general election {people.term_start(chamber) or 'unknown'}")


if __name__ == "__main__":
    main()
