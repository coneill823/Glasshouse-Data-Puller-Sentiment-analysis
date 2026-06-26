#!/usr/bin/env python3
"""
TEMPORARY Scottish votes deep-dive, round 3 — crack the SearchVotes API.

Round 2 found /api/sitecore/VotesMotionsSearch/SearchMotions in the page forms,
so there should be a SearchVotes sibling returning divisions with per-member
votes. This probes it (minimal + date-ranged) and dumps the response structure
so the parser can read division results + roll-calls.

    python diagnose_scottish_votes4.py

Throwaway — removed once the votes source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

API = f"{_WEB}/api/sitecore/VotesMotionsSearch"
REFERER = f"{_WEB}/chamber-and-committees/votes-and-motions"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9",
                     "X-Requested-With": "XMLHttpRequest", "Referer": REFERER})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def probe(method, params):
    url = f"{API}/{method}"
    try:
        r = sess.get(url, params=params, timeout=30)
    except Exception as e:
        print(f"[{method} {params}] ERROR {type(e).__name__}: {e}")
        return None
    ct = r.headers.get("Content-Type", "").split(";")[0]
    body = r.text
    # signals
    refs = sorted(set(re.findall(r"S\dM-\d+", body)))
    voted = body.lower().count("voted")
    forn = len(re.findall(r"\bFor\b", body))
    print(f"[{method} {dict(params)}] HTTP {r.status_code} | {ct} | {len(body)} bytes | "
          f"motion refs: {len(refs)} | 'voted' x{voted} | 'For' x{forn}")
    return r


# ── 1. SearchVotes: does it exist? minimal + date-ranged ──
hr("1 — SearchVotes probes")
r = probe("SearchVotes", {"pageNumber": 1})
probe("SearchVotes", {"pageNumber": 1, "dtVotesDateFrom": "2025-01-06", "dtVotesDateTo": "2025-02-07"})
probe("SearchVotes", {"pageNumber": 1, "dtDateFrom": "2025-01-06", "dtDateTo": "2025-02-07"})
probe("SearchVotes", {"pageNumber": 1, "voteDateSelect": "All"})

# ── 2. dump SearchVotes structure ──
hr("2 — SearchVotes response structure")
r = probe("SearchVotes", {"pageNumber": 1})
if r is not None and r.ok and len(r.text) > 200:
    soup = BeautifulSoup(r.text, "lxml")
    print("\nresult-ish containers:")
    for sel in ["[class*='vote']", "[class*='result']", "[class*='division']", "article",
                "[class*='for']", "[class*='against']", "[class*='abstain']",
                "[class*='member']", "li", "table tr"]:
        els = soup.select(sel)
        if els:
            print(f"  {sel!r}: {len(els)} | first: {els[0].get_text(' ', strip=True)[:70]!r}")
    print("\n--- first 2500 chars of response ---")
    print(r.text[:2500])

# ── 3. compare with SearchMotions (known to work) for format reference ──
hr("3 — SearchMotions (reference) first 800 chars")
r = probe("SearchMotions", {"pageNumber": 1, "chkStandard": "True", "chkDebate": "True"})
if r is not None and r.ok:
    print(r.text[:800])

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
