#!/usr/bin/env python3
"""
TEMPORARY Scottish-OR search recon, round 2 — filtered search + content fetch.

Round 1 found the OR search form's fields (date range + showPlenary + display
type) and that result links carry ?meeting=<id>&iob=<item>. This:
  A. submits the search via GET-with-params for a recent range, Plenary-only,
     ResultDisplayType=Reports — does SSR return filtered plenary meeting links?
  B. same but ResultDisplayType=Contributions — does it return contribution text?
  C. tests the CustomMedia OR media API with a real meeting id from round 1 (20187)
  D. fetches a report page (CODE-date?meeting=id) and inspects its structure
so we can choose the cleanest extraction path.

    python diagnose_scottish_or_search2.py

Throwaway — deleted once the plenary path is settled.
"""
import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9",
                     "X-Requested-With": "XMLHttpRequest", "Referer": SEARCH})

FROM = (date.today() - timedelta(days=30)).isoformat()
TO = date.today().isoformat()


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def meeting_links(html):
    """Return [(code, meeting_id, iob)] from report links in the result HTML."""
    out, seen = [], set()
    for m in re.finditer(r"search-what-was-said-in-parliament/([A-Z]+)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)(?:&(?:amp;)?iob=(\d+))?", html):
        code, d, mid, iob = m.group(1), m.group(2), m.group(3), m.group(4)
        key = (mid, iob)
        if key not in seen:
            seen.add(key)
            out.append((code, d, mid, iob))
    return out


def search(label, display_type):
    params = {
        "qry": "",
        "dtDateFrom": FROM, "dtDateTo": TO, "dateSelect": "0",
        "showPlenary": "true",
        "ShowDebates": "true", "ShowFMQs": "true", "ShowGeneralQuestions": "true",
        "ShowPortfolioQuestions": "true", "ShowTopicalQuestions": "true",
        "ShowUrgentQuestions": "true",
        "showCommittee": "false",
        "ResultDisplayType": display_type,
    }
    print(f"\n[{label}] GET {SEARCH}\n   range {FROM}->{TO}, Plenary-only, display={display_type}")
    try:
        r = sess.get(SEARCH, params=params, timeout=45)
    except Exception as e:
        print(f"   ERROR {type(e).__name__}: {e}")
        return []
    links = meeting_links(r.text)
    codes = sorted({c for c, *_ in links})
    rc = re.search(r'id="resultCount"[^>]*>([^<]+)', r.text)
    print(f"   HTTP {r.status_code} | {len(r.text)} chars | resultCount={rc.group(1).strip() if rc else '?'} | "
          f"distinct meetings: {len({m for _,_,m,_ in links})} | report-code prefixes: {codes}")
    for c, d, mid, iob in links[:8]:
        print(f"      {c}-{d} meeting={mid} iob={iob}")
    return links


hr("A — Reports view (Plenary only, last 30 days)")
rep_links = search("Reports", "Reports")

hr("B — Contributions view (Plenary only, last 30 days)")
con_links = search("Contributions", "Contributions")

hr("C — CustomMedia OR media API with a real meeting id (20187) + a plenary id")
ids_to_try = ["20187"] + [m for _, _, m, _ in (rep_links or con_links)][:2]
for mid in dict.fromkeys(ids_to_try):
    try:
        r = sess.get(f"{_WEB}/api/sitecore/CustomMedia/OfficialReport",
                     params={"meetingId": mid}, timeout=30)
        txt = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True) if r.ok else ""
        print(f"[meetingId={mid}] HTTP {r.status_code} | {len(r.content)} bytes | text~{len(txt)}"
              + (f" | sample: {txt[:160]!r}" if txt else ""))
    except Exception as e:
        print(f"[meetingId={mid}] ERROR {type(e).__name__}: {e}")

hr("D — fetch one report page and inspect structure")
if rep_links or con_links:
    code, d, mid, iob = (rep_links or con_links)[0]
    url = f"{SEARCH}/{code}-{d}?meeting={mid}"
    try:
        r = sess.get(url, timeout=40)
        soup = BeautifulSoup(r.text, "lxml")
        txt = soup.get_text(" ", strip=True)
        print(f"[{url}]\n   HTTP {r.status_code} | text~{len(txt)}")
        # likely contribution containers
        for sel in ["[class*='contribution']", "[class*='speech']", ".report-content p",
                    "article p", "[id*='iob']", "[class*='speaker']"]:
            els = soup.select(sel)
            if els:
                print(f"   selector {sel!r}: {len(els)} | sample: {els[0].get_text(' ', strip=True)[:160]!r}")
    except Exception as e:
        print(f"   ERROR {type(e).__name__}: {e}")
else:
    print("no report links found in A/B — cannot fetch a report page")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
