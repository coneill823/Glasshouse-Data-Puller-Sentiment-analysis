#!/usr/bin/env python3
"""
TEMPORARY Scottish-OR recon, round 5 (decisive) — does the GUID date-preset work?

The search POST returns the 8 most-recent committee meetings and ignores custom
dates. dateSelect uses opaque GUID|from|to preset tokens. This POSTs those preset
tokens (Session 6, Last 12 months, All Sessions) with a plenary-only filter:
  - if the returned meeting set CHANGES by period -> HTTP-only filtering works,
    and we can discover historical plenary meeting IDs.
  - if every preset returns the SAME recent 8 -> the real search is client-side
    only; HTTP can't drive it and we'd need a headless browser.

    python diagnose_scottish_or_search5.py

Throwaway — deleted once the plenary path is settled.
"""
import re

import requests

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9",
                     "X-Requested-With": "XMLHttpRequest", "Referer": SEARCH,
                     "Origin": _WEB})

PRESETS = {
    "Current session": "5ee561fa0db44fda8c6d5b19ddd24465|Thursday, May 14, 2026|Friday, June 26, 2026",
    "Last 12 months":  "310ccf912b014d73a7c96120d2af1904|Thursday, June 26, 2025|Friday, June 26, 2026",
    "Session 6":       "a8519a01651e4218925061a95394279f|Thursday, May 13, 2021|Wednesday, May 13, 2026",
    "All Sessions":    "acfe09e8571447b6ac663f6362a20f42|Wednesday, May 12, 1999|Friday, June 26, 2026",
}


def meetings(html):
    out = {}
    for m in re.finditer(r"search-what-was-said-in-parliament/([A-Z]+)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
        out[m.group(3)] = (m.group(1), m.group(2))
    return out


def post(label, dateselect, plenary_only):
    payload = {
        "msp": "", "committeeSelect": "", "qry": "",
        "dateSelect": dateselect, "dtDateFrom": "", "dtDateTo": "",
        "showPlenary": "true", "ShowDebates": "true", "ShowFMQs": "true",
        "ShowGeneralQuestions": "true", "ShowPortfolioQuestions": "true",
        "ShowSPCBQuestions": "true", "ShowTopicalQuestions": "true",
        "ShowUrgentQuestions": "true", "ResultDisplayType": "Reports",
    }
    if not plenary_only:
        payload["showCommittee"] = "true"
    try:
        r = sess.post(SEARCH, data=payload, timeout=50)
    except Exception as e:
        print(f"[{label}] ERROR {type(e).__name__}: {e}")
        return
    mtgs = meetings(r.text)
    codes = {}
    dates = set()
    for c, d in mtgs.values():
        codes[c] = codes.get(c, 0) + 1
        dates.add(d)
    yrs = sorted({d[-4:] for d in dates})
    print(f"[{label}] HTTP {r.status_code} | {len(r.text)} chars | meetings={len(mtgs)} | "
          f"years={yrs} | codes={codes}")
    for mid, (c, d) in list(mtgs.items())[:6]:
        print(f"      {c}-{d} meeting={mid}")


print("=" * 76)
print("A — each preset, committees + plenary (does the set change by period?)")
print("=" * 76)
for name, val in PRESETS.items():
    post(f"all/{name}", val, plenary_only=False)

print("\n" + "=" * 76)
print("B — each preset, PLENARY ONLY (committee box unchecked)")
print("=" * 76)
for name, val in PRESETS.items():
    post(f"plenary/{name}", val, plenary_only=True)

print("\n" + "=" * 76)
print("Read: if 'Session 6' / 'All Sessions' return DIFFERENT meetings (2021-2025,")
print("non-committee codes) -> HTTP filtering works. If all show the same recent 8")
print("June-2026 committees -> the search is client-side only (browser needed).")
print("=" * 76)
