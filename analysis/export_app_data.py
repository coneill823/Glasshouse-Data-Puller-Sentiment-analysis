#!/usr/bin/env python3
"""
Assemble everything the app shows about each sitting representative.

Two sources, each used for what it is best at:

  mySociety open data (small, daily)   who sits where, for which party; the
                                       voting record for the Commons, Scottish
                                       Parliament and Senedd; motions signed
  Glasshouse scrapers (large, slow)    what members ask and speak about, and
                                       the Northern Ireland Assembly's votes

The member list always comes from mySociety's register, so the app is current
to the day even when the scraped corpus is weeks old. Speech-derived figures
are attached by matching each member on legislature + area + name, and carry
the date they were computed so the app can say how fresh they are.

If the scraped outputs (analysis/output/*.csv) aren't present — a fresh clone,
CI, a laptop without the 2 GB corpus — the speech figures are carried forward
from the previous app/data.json rather than dropped. Run the scrapers and
`python -m analysis.behaviour` to refresh them.

Usage:
    python -m analysis.export_app_data
    python -m analysis.export_app_data --no-fetch
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from analysis import mysociety, record

MAX_TOPICS = 8
MAX_RECEIPTS = 25
# chambers whose voting record comes from mySociety
MYSOCIETY_VOTES = ("commons", "scotland", "senedd")
ROLE = {"commons": "MP", "scotland": "MSP", "senedd": "MS", "ni": "MLA"}
HOUSE = {"commons": "House of Commons", "scotland": "Scottish Parliament",
         "senedd": "Senedd Cymru", "ni": "Northern Ireland Assembly"}
TITLES = {"mr", "mrs", "ms", "miss", "dr", "sir", "dame", "rt", "hon", "the",
          "lord", "lady", "baroness", "professor", "prof"}


# --- matching a register entry to speech-derived data ------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def name_tokens(name: str) -> list:
    name = name or ""
    if "," in name:                       # NI publishes "Surname, Forename"
        surname, _, rest = name.partition(",")
        name = f"{rest} {surname}"
    return [t for t in _norm(name).split() if t not in TITLES]


def same_person(a: str, b: str) -> bool:
    """Same surname, and either the same first initial or two shared names."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb or ta[-1] != tb[-1]:
        return False
    return ta[0][0] == tb[0][0] or len(set(ta) & set(tb)) >= 2


# Places where a source spells an area differently. Listed one by one on
# purpose: a general "close enough" rule would also join Glasgow South to
# Glasgow Southside, and a wrong join puts one person's record on another.
AREA_ALIASES = {
    # the Scottish Parliament's own member pages abbreviate this region
    "central scot and lothians west": "central scotland and lothians west",
}


def _area_keys(area: str):
    """Keys an area can be found under.

    exact      "belfast east"
    unordered  "belfast east" == "east belfast"   (the Assembly's own data
               writes East Belfast; the register writes Belfast East)
    """
    n = _norm(area)
    n = AREA_ALIASES.get(n, n)
    yield n
    yield " ".join(sorted(n.split()))


class LegacyIndex:
    """Speech-derived member records, findable by legislature + area + name."""

    def __init__(self, members: list):
        self.by_area = {}
        for m in members:
            for key in _area_keys(m["area"]):
                self.by_area.setdefault((m["parliament"], key), []).append(m)

    def find(self, parliament: str, area: str, name: str):
        for key in _area_keys(area):
            for cand in self.by_area.get((parliament, key), []):
                if same_person(cand["name"], name):
                    return cand
        return None


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


def load_scraped(out_dir: Path):
    """(members, as_of) from behaviour.py's CSV outputs, or ([], '') if absent."""
    rec_path = out_dir / "member_record.csv"
    if not rec_path.exists():
        return [], ""
    members = {}
    with open(rec_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "current":
                continue
            members[(r["parliament"], r["member"])] = {
                "parliament": r["parliament"], "name": r["member"],
                "area": r.get("constituency", ""),
                "questions": _i(r.get("n_questions")),
                "speeches": _i(r.get("n_speeches")),
                "topics": [], "receipts": [],
                "votesCast": _i(r.get("votes_cast")),
                "termVotes": _i(r.get("term_votes")),
                "eligible": _i(r.get("divisions_eligible")),
                "turnout": _f(r.get("turnout_pct")),
                "partyAgreement": _f(r.get("party_agreement_pct")),
                "partyLineDivisions": _i(r.get("party_line_divisions")),
                "chamberAgreement": _f(r.get("chamber_agreement_pct")),
                "rebellions": _i(r.get("rebellions")),
            }
    sal = out_dir / "member_salience.csv"
    if sal.exists():
        with open(sal, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = members.get((r["parliament"], r["member"]))
                if m and _i(r.get("statements")) > 0:
                    m["topics"].append([r["topic"], _i(r["statements"]),
                                        _f(r.get("share_of_statements_pct")) or 0.0])
    reb = out_dir / "member_rebellions.csv"
    if reb.exists():
        with open(reb, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                m = members.get((r["parliament"], r["member"]))
                if m:
                    m["receipts"].append([r.get("date", ""), (r.get("division") or "")[:180],
                                          r.get("their_vote", ""), r.get("party_voted", "")])
    for m in members.values():
        m["topics"].sort(key=lambda t: -t[1])
        m["receipts"].sort(key=lambda r: r[0], reverse=True)
    as_of = datetime.fromtimestamp(rec_path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
    return list(members.values()), as_of


def load_previous(path: Path):
    """(members, as_of) from an earlier app/data.json, for carrying forward."""
    if not path.exists():
        return [], ""
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return [], ""
    members = old.get("members", [])
    # an export that itself carried figures forward records their true date
    as_of = (old.get("sources", {}).get("speech", {}).get("asOf")
             or old.get("generated", ""))
    return members, as_of


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _median(values):
    vals = [v for v in values if v is not None]
    return round(st.median(vals), 1) if vals else None


def build(cache_dir: Path, scraped_dir: Path, out_path: Path, fetch: bool = True) -> dict:
    if fetch:
        mysociety.fetch(cache_dir)
    people = mysociety.People(cache_dir)

    legacy, speech_as_of = load_scraped(scraped_dir)
    carried = False
    if not legacy:
        legacy, speech_as_of = load_previous(out_path)
        carried = bool(legacy)
    index = LegacyIndex(legacy)

    rows, chambers = [], {}
    for chamber, parliament in mysociety.CHAMBER_PARLIAMENT.items():
        members = people.current_members(chamber)
        term_start = people.term_start(chamber)
        from_mysociety = chamber in MYSOCIETY_VOTES
        rec = record.chamber_record(cache_dir, chamber, people) if from_mysociety else {}
        sigs = record.signatures(cache_dir, chamber, term_start) if chamber == "commons" else {}
        matched = 0
        group = []
        for m in members:
            old = index.find(parliament, m["area"], m["name"])
            matched += old is not None
            row = {
                "id": m["person_id"],
                "name": m["name"],
                "party": m["party"],
                "area": m["area"],
                "parliament": parliament,
                "since": people.first_elected(m["person_id"], chamber)[:4],
            }
            if m["ids"].get("mnis") and chamber == "commons":
                row["mnis"] = m["ids"]["mnis"]
            if m["gss"]:
                row["gss"] = m["gss"]

            r = rec.get(m["person_id"])
            if from_mysociety:
                r = r or {}
                row.update({
                    "votesCast": r.get("votes_cast", 0),
                    "termVotes": r.get("term_votes", 0),
                    "eligible": r.get("divisions_eligible", 0),
                    "turnout": _pct(r.get("term_votes", 0), r.get("divisions_eligible", 0)),
                    "partyAgreement": _pct(r.get("with_party", 0), r.get("party_line_divisions", 0)),
                    "partyLineDivisions": r.get("party_line_divisions", 0),
                    "chamberAgreement": _pct(r.get("with_chamber", 0),
                                             r.get("chamber_decided_divisions", 0)),
                    "rebellions": r.get("rebellions", 0),
                    "receipts": r.get("receipts", [])[:MAX_RECEIPTS],
                })
            elif old:
                # no mySociety votes for this chamber: use the scraped record
                for k in ("votesCast", "termVotes", "eligible", "turnout", "partyAgreement",
                          "partyLineDivisions", "chamberAgreement", "rebellions"):
                    if old.get(k) is not None:
                        row[k] = old[k]
                row["receipts"] = (old.get("receipts") or [])[:MAX_RECEIPTS]
                row["recordAsOf"] = speech_as_of

            if old:
                row["questions"] = old.get("questions", 0)
                row["speeches"] = old.get("speeches", 0)
                row["topics"] = (old.get("topics") or [])[:MAX_TOPICS]
            if m["person_id"] in sigs:
                row["motions"] = sigs[m["person_id"]]
            group.append(row)

        chambers[parliament] = {
            "slug": chamber, "role": ROLE[chamber], "house": HOUSE[chamber],
            "termStart": term_start,
            "members": len(group),
            "votesSource": "mysociety" if from_mysociety else "scraped",
            "termDivisions": max((g.get("eligible") or 0 for g in group), default=0),
            "turnout": _median(g.get("turnout") for g in group),
            "partyAgreement": _median(g.get("partyAgreement") for g in group
                                      if (g.get("partyLineDivisions") or 0) >= 20),
            "chamberAgreement": _median(g.get("chamberAgreement") for g in group),
            "everRebelled": sum(1 for g in group if (g.get("rebellions") or 0) > 0),
            "withSpeech": matched,
        }
        rows.extend(group)

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sources": {
            "votes": {"name": "TheyWorkForYou Votes (mySociety)",
                      "asOf": mysociety.cache_date(cache_dir)},
            "speech": {"name": "Glasshouse scrapers", "asOf": speech_as_of,
                       "carried": carried},
        },
        "topics": sorted({t[0] for m in rows for t in m.get("topics", [])}),
        "chambers": chambers,
        "members": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    areas = {(m["parliament"], m["area"]) for m in rows}
    print(f"Exported {len(rows)} sitting representatives across {len(areas)} areas "
          f"-> {out_path} ({out_path.stat().st_size / 1024:,.0f} KB)")
    print(f"  votes as of {payload['sources']['votes']['asOf']} | speech figures as of "
          f"{speech_as_of or 'n/a'}{' (carried forward from the previous export)' if carried else ''}")
    for parliament, c in chambers.items():
        print(f"  {parliament:28} {c['members']:4} members | {c['withSpeech']:4} matched to "
              f"speech data | median turnout {c['turnout']}% | votes: {c['votesSource']}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble app/data.json.")
    ap.add_argument("--cache", default=str(mysociety.DEFAULT_CACHE))
    ap.add_argument("--in", dest="in_dir", default="analysis/output",
                    help="behaviour.py outputs (speech figures, NI votes)")
    ap.add_argument("--out", dest="out_path", default="app/data.json")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    build(Path(a.cache), Path(a.in_dir), Path(a.out_path), fetch=not a.no_fetch)


if __name__ == "__main__":
    main()
