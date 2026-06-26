#!/usr/bin/env python3
"""
TEMPORARY Welsh-votes recon, round 6 (final) — crack the filter date format.

The listing rows carry meetingID | date | committee | Votes/No Votes, but the
POST filter returns 0 — almost certainly a date-format/culture mismatch. This
POSTs the Plenary filter in several date formats over a known-populated window
and reports which one actually returns meeting rows. The winner lets discovery
pull all plenary meetings (with dates + vote flags) for any range in one request.

    python diagnose_welsh_votes6.py

Throwaway — deleted once the votes fix lands.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.welsh_parliament import _RECORD, _BROWSER_UA, _PLENARY_COMMITTEE_ID

URL = f"{_RECORD}/XMLExport"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def rows_with_meetings(html):
    """Return [(id, row_text)] for listing rows that link a meetingID."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"meetingID=\d+"))
        if a:
            mid = re.search(r"meetingID=(\d+)", a["href"]).group(1)
            out.append((mid, tr.get_text(" ", strip=True)[:80]))
    return out


def attempt(label, start, end, committee=_PLENARY_COMMITTEE_ID):
    payload = {"SelectedCommitteeID": committee, "Start": start, "End": end,
               "submittingButton": "Search"}
    try:
        r = sess.post(URL, data=payload, timeout=45, headers={"Referer": URL, "Origin": _RECORD})
    except Exception as e:
        print(f"[{label:18}] ERROR {type(e).__name__}: {e}")
        return
    ids = sorted(set(re.findall(r"meetingID=(\d+)", r.text)), key=int)
    rows = rows_with_meetings(r.text)
    print(f"[{label:18}] start={start!r} end={end!r} cmte={committee} -> "
          f"HTTP {r.status_code} | {len(r.text)} chars | {len(ids)} ids"
          + (f" | range {ids[0]}..{ids[-1]}" if ids else ""))
    for mid, txt in rows[:4]:
        print(f"        row {mid}: {txt!r}")


print("=" * 74)
print("POST /XMLExport — Plenary (908), various date formats, June 2024")
print("=" * 74)
attempt("dd/MM/yyyy",   "01/06/2024", "30/06/2024")
attempt("MM/dd/yyyy",   "06/01/2024", "06/30/2024")
attempt("ISO",          "2024-06-01", "2024-06-30")
attempt("d/M/yyyy",     "1/6/2024",   "30/6/2024")
attempt("M/d/yyyy",     "6/1/2024",   "6/30/2024")

print("\n" + "-" * 74)
print("Wider windows (1 Jan 2024 -> end 2024) to see how many it returns")
print("-" * 74)
attempt("wide dd/MM",   "01/01/2024", "31/12/2024")
attempt("wide MM/dd",   "01/01/2024", "12/31/2024")

print("\n" + "-" * 74)
print("Committee=All (0) with MM/dd, in case 908 isn't valid historically")
print("-" * 74)
attempt("all MM/dd",    "06/01/2024", "06/30/2024", committee="0")

print("\n" + "=" * 74 + "\nDONE — paste the whole output.\n" + "=" * 74)
