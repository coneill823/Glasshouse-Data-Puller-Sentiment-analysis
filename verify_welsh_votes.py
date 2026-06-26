#!/usr/bin/env python3
"""
Live verification + discovery diagnosis for the Welsh votes fix.

Round 1 showed discovery returns meetings but not the date-filtered ones. This:
  A. dumps what GET vs POST to /XMLExport return for a June-2024 filter (id range,
     and the text/date context around each meetingID link), so we learn whether
     the date filter works and whether the listing carries dates; and
  B. directly parses the known-good meeting 13950 to confirm LIVE vote parsing.

    python verify_welsh_votes.py

Throwaway — deleted once the votes fix is confirmed.
"""
import re
import json

import requests

from scrapers.welsh_parliament import (WelshParliamentScraper, _RECORD,
                                        _PLENARY_COMMITTEE_ID, _BROWSER_UA)

URL = f"{_RECORD}/XMLExport"
PARAMS = {"SelectedCommitteeID": _PLENARY_COMMITTEE_ID,
          "Start": "01/06/2024", "End": "30/06/2024", "submittingButton": ""}

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def dump(label, resp):
    if resp is None:
        print(f"\n[{label}] no response")
        return
    html = resp.text
    ids = sorted(set(re.findall(r"meetingID=(\d+)", html)), key=int)
    print(f"\n[{label}] HTTP {resp.status_code} | {len(html)} chars | "
          f"unique meetingIDs: {len(ids)}"
          + (f" | range {ids[0]}..{ids[-1]}" if ids else ""))
    # context around the first few meetingID links: shows whether a date sits nearby
    ctxs = re.findall(r".{0,70}meetingID=\d+.{0,20}", html)
    for c in ctxs[:6]:
        print(f"    …{c.strip()}…")
    # any dd/mm/yyyy or yyyy-mm-dd dates in the page
    dates = sorted(set(re.findall(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", html)))
    print(f"    dates seen on page: {dates[:10]}")


print("=" * 70)
print("A — GET vs POST to /XMLExport with a June-2024 Plenary filter")
print("=" * 70)
try:
    dump("GET", sess.get(URL, params=PARAMS, timeout=30))
except Exception as e:
    print(f"[GET] ERROR {type(e).__name__}: {e}")
try:
    dump("POST", sess.post(URL, data=PARAMS, timeout=30))
except Exception as e:
    print(f"[POST] ERROR {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("B — live parse of known-good meeting 13950 (2024-06-19)")
print("=" * 70)
s = WelshParliamentScraper()
records = []
try:
    added = s._fetch_votes_xml_export("13950", "2024-06-19", None, records)
    print(f"meeting 13950: +{added} vote records")
    if records:
        dirs = {}
        for r in records:
            d = r["metadata"]["vote_direction"]
            dirs[d] = dirs.get(d, 0) + 1
        print(f"direction breakdown: {dirs}")
        print("sample record:")
        print(json.dumps(records[0], indent=2, default=str)[:850])
except Exception as e:
    print(f"ERROR parsing 13950: {type(e).__name__}: {e}")

print("\n" + "=" * 70 + "\nDONE — paste the whole output.\n" + "=" * 70)
