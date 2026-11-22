#!/usr/bin/env python3
"""
Councils: a pilot on two of them, to find out what a council's own records
can honestly support.

There is no national record of what councillors do. Each council publishes
its own, most of them through one of two committee systems. This module reads
the commonest of those (ModernGov) for the councils listed in COUNCILS:

  * who the councillors are, their party and their ward: from the system's
    own data service, which is reliable where it is reachable at all;
  * how many of the meetings they were expected at they attended, over the
    twelve months to the day of the build: from each councillor's attendance
    page, where the council publishes one.

What the pilot found (November 2026), and why this stays a pilot:

  * Named votes are not there to collect. Belfast's system answers "There is
    no voting information available" for every councillor; most council votes
    are a show of hands recorded only as carried or lost.
  * Attendance is there for Belfast. Cardiff's data service answers, but its
    pages return nothing to an automated reader, so Cardiff councillors are
    listed without it.
  * Of six other councils tried, four refused automated requests outright.

So what can be shown for a councillor, from their actions, is at most whether
they turned up. That is shown where it exists, with what it covers, and
nothing is made of it beyond that. Attendance is not turnout in votes: a
councillor is "expected" only at committees they sit on.

Usage:
    python -m analysis.councils              # prints what was found
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

from analysis import mysociety

DEFAULT_CACHE = Path("data/_councils")
MAX_AGE_HOURS = 20
# The schedule of the District Electoral Areas (Northern Ireland) Order 2014:
# which wards make up each of the areas Northern Ireland's councillors are
# elected for. A postcode tells you the ward; this tells you the area.
NI_AREAS_URL = "https://www.legislation.gov.uk/uksi/2014/270/schedule/made/data.xht"

COUNCILS = [
    {"name": "Belfast City Council", "gss": "N09000003",
     "base": "https://minutes.belfastcity.gov.uk", "ni_district": "Belfast"},
    {"name": "Cardiff Council", "gss": "W06000015",
     "base": "https://cardiff.moderngov.co.uk"},
]

_TITLE = re.compile(r"^(?:The [^,]+,\s*)?(?:Councillor|Alderman|Cllr|Cynghorydd|Y Cynghorydd)\s+", re.I)


def _get(url: str, cache: Path, offline: bool, max_age_hours: float = MAX_AGE_HOURS) -> str:
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_hours * 3600
    if fresh or offline:
        return cache.read_text(encoding="utf-8") if cache.exists() else ""
    import requests
    try:
        r = requests.get(url, timeout=90, headers={"User-Agent": mysociety.USER_AGENT})
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding="utf-8")
        time.sleep(0.3)                       # one request at a time, unhurried
        return r.text
    except Exception as e:  # network or HTTP
        print(f"  ! could not fetch {url} ({e})", file=sys.stderr)
        return cache.read_text(encoding="utf-8") if cache.exists() else ""


def _text(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def parse_wards(xml: str) -> list:
    """[{name, councillors: [{id, name, party}]}] from GetCouncillorsByWard."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for ward in root.iter("ward"):
        people = []
        for c in ward.iter("councillor"):
            name = (c.findtext("fullusername") or "").strip()
            if not name:
                continue
            people.append({
                "id": (c.findtext("councillorid") or "").strip(),
                "name": _TITLE.sub("", name),
                "party": (c.findtext("politicalpartytitle") or "").strip() or "Independent",
            })
        title = (ward.findtext("wardtitle") or "").strip()
        if title and people:
            out.append({"name": title, "councillors": people})
    return out


def parse_attendance(page: str):
    """(expected, present) from a councillor's attendance page, or None."""
    text = _text(page)
    expected = re.search(r"Total expected attendances:\s*(\d+)", text)
    present = re.search(r"Present as expected:\s*(\d+)", text)
    if not expected or not present:
        return None
    return int(expected.group(1)), int(present.group(1))


def parse_ni_areas(page: str) -> dict:
    """{district: {electoral area: [ward, ...]}} from the 2014 Order's schedule."""
    out, district, area = {}, "", ""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        cells = [_text(c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        cells = [c for c in cells if c]
        if not cells or cells[0].startswith("1."):
            continue
        if len(cells) >= 4:
            district, area, ward = cells[0], cells[1], cells[2]
        elif len(cells) == 3:
            area, ward = cells[0], cells[1]
        elif len(cells) == 1:
            ward = cells[0]
        else:
            continue
        if district and area:
            out.setdefault(district, {}).setdefault(area, []).append(ward)
    return out


def build(cache_dir: Path = DEFAULT_CACHE, today: str = "", fetch: bool = True) -> dict:
    """The `councils` block of app/data.json."""
    day = date.fromisoformat(today) if today else date.today()
    start = day - timedelta(days=365)
    span = f"{start:%d}%2f{start:%m}%2f{start:%Y}-{day:%d}%2f{day:%m}%2f{day:%Y}"
    ni_areas = None
    bodies = []
    for council in COUNCILS:
        slug = re.sub(r"[^a-z]+", "-", council["name"].lower()).strip("-")
        store = cache_dir / slug
        wards = parse_wards(_get(f"{council['base']}/mgWebService.asmx/GetCouncillorsByWard",
                                 store / "wards.xml", offline=not fetch))
        if not wards:
            continue
        counted = tried = 0
        for ward in wards:
            ward["covers"] = [ward["name"]]
            for c in ward["councillors"]:
                # A council that answers nothing for its first few councillors
                # is not going to for the rest: stop asking.
                refused = tried >= 3 and counted == 0
                page = "" if refused else _get(
                    f"{council['base']}/mgAttendance.aspx?UID={c['id']}&DR={span}",
                    store / f"attendance_{c['id']}.html", offline=not fetch)
                tried += 1
                found = parse_attendance(page)
                if found and found[0] > 0:
                    c["expected"], c["present"] = found
                    counted += 1
                c["url"] = f"{council['base']}/mgUserInfo.aspx?UID={c['id']}"
                del c["id"]
        if council.get("ni_district"):
            # Northern Ireland's councillors sit for electoral areas made of
            # several wards; list the wards so a postcode's ward finds its area.
            if ni_areas is None:
                ni_areas = parse_ni_areas(_get(NI_AREAS_URL, cache_dir / "ni_areas.html",
                                               offline=not fetch, max_age_hours=24 * 365))
            mine = ni_areas.get(council["ni_district"], {})
            for ward in wards:
                ward["covers"] = mine.get(ward["name"], [ward["name"]])
        bodies.append({
            "name": council["name"],
            "gss": council["gss"],
            "url": council["base"],
            "attendance": counted > 0,
            "wards": wards,
        })
    return {
        "asOf": day.isoformat(),
        "period": [start.isoformat(), day.isoformat()],
        "bodies": bodies,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Show what the pilot councils publish.")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    out = build(Path(a.cache), fetch=not a.no_fetch)
    for body in out["bodies"]:
        people = [c for w in body["wards"] for c in w["councillors"]]
        with_att = [c for c in people if "expected" in c]
        print(f"{body['name']}: {len(people)} councillors in {len(body['wards'])} wards or areas; "
              f"attendance for {len(with_att)}")
        if with_att:
            rates = sorted(100 * c["present"] / c["expected"] for c in with_att)
            print(f"  attendance {out['period'][0]} to {out['period'][1]}: "
                  f"median {rates[len(rates) // 2]:.0f}%, lowest {rates[0]:.0f}%")
        w = body["wards"][0]
        print(f"  e.g. {w['name']} covers {w['covers'][:6]}: "
              f"{json.dumps(w['councillors'][0], ensure_ascii=False)[:150]}")


if __name__ == "__main__":
    main()
