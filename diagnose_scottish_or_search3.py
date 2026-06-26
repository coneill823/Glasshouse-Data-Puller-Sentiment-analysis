#!/usr/bin/env python3
"""
TEMPORARY Scottish-OR recon, round 3 — discovery mechanics + PDF parse.

Round 2 proved the media API returns the full OR as a PDF. Remaining: (1) how to
list plenary meeting IDs for a date range via the search, and (2) that PyMuPDF
extracts clean contributions from the PDF.

  A. default search page -> dump ALL meeting codes/ids (find the plenary code,
     see what's available without filters)
  B. date-ranged search including committees -> does the date filter work at all?
     (sends only checked checkboxes, several date formats)
  C. date-ranged search, plenary-only -> plenary meeting ids in range
  D. fetch meetingId=20187 PDF and parse with PyMuPDF -> confirm transcript text

    python diagnose_scottish_or_search3.py

Throwaway — deleted once the plenary path is settled.
"""
import re
from collections import Counter
from datetime import date, timedelta

import requests

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9",
                     "X-Requested-With": "XMLHttpRequest", "Referer": SEARCH})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def links(html):
    out = []
    for m in re.finditer(r"search-what-was-said-in-parliament/([A-Z]+)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def fetch(label, params):
    try:
        r = sess.get(SEARCH, params=params, timeout=45)
    except Exception as e:
        print(f"[{label}] ERROR {type(e).__name__}: {e}")
        return []
    ls = links(r.text)
    by_code = Counter(c for c, _, _ in ls)
    uniq = {(c, d, m) for c, d, m in ls}
    print(f"[{label}] HTTP {r.status_code} | {len(r.text)} chars | "
          f"distinct meetings: {len({m for _,_,m in uniq})} | codes: {dict(by_code)}")
    for c, d, m in sorted(uniq)[:6]:
        print(f"      {c}-{d} meeting={m}")
    return sorted(uniq)


# ── A. default page (no filter params) ──
hr("A — default search page: all meeting codes/ids")
default = fetch("default", {})

# ── B. date filter sanity: include everything, several date formats ──
hr("B — date-ranged (committees included) — which date format filters?")
FROM_ISO = (date.today() - timedelta(days=45)).isoformat()
TO_ISO = date.today().isoformat()
F = date.fromisoformat(FROM_ISO); T = date.fromisoformat(TO_ISO)
all_checks = {k: "true" for k in
              ["showPlenary", "ShowDebates", "ShowFMQs", "ShowGeneralQuestions",
               "ShowPortfolioQuestions", "ShowTopicalQuestions", "ShowUrgentQuestions",
               "ShowSPCBQuestions", "showCommittee"]}
for label, df, dt in [
    ("ISO", FROM_ISO, TO_ISO),
    ("DD/MM/YYYY", F.strftime("%d/%m/%Y"), T.strftime("%d/%m/%Y")),
    ("MM/DD/YYYY", F.strftime("%m/%d/%Y"), T.strftime("%m/%d/%Y")),
    ("long", F.strftime("%A, %B %d, %Y"), T.strftime("%A, %B %d, %Y")),
]:
    fetch(f"all/{label}", {**all_checks, "qry": "", "dtDateFrom": df, "dtDateTo": dt,
                           "ResultDisplayType": "Reports"})

# ── C. plenary-only (omit committee checkbox), best date format guess ──
hr("C — plenary-only, last 45 days (ISO + DD/MM/YYYY)")
plen_checks = {k: "true" for k in
               ["showPlenary", "ShowDebates", "ShowFMQs", "ShowGeneralQuestions",
                "ShowPortfolioQuestions", "ShowTopicalQuestions", "ShowUrgentQuestions"]}
for label, df, dt in [("ISO", FROM_ISO, TO_ISO),
                      ("DD/MM/YYYY", F.strftime("%d/%m/%Y"), T.strftime("%d/%m/%Y"))]:
    fetch(f"plenary/{label}", {**plen_checks, "qry": "", "dtDateFrom": df, "dtDateTo": dt,
                               "ResultDisplayType": "Reports"})

# ── D. PDF parse with PyMuPDF ──
hr("D — fetch meetingId=20187 PDF and parse with PyMuPDF")
try:
    import fitz
    r = sess.get(f"{_WEB}/api/sitecore/CustomMedia/OfficialReport",
                 params={"meetingId": "20187"}, timeout=40)
    print(f"media API: HTTP {r.status_code} | {len(r.content)} bytes | ct={r.headers.get('Content-Type')}")
    doc = fitz.open(stream=r.content, filetype="pdf")
    print(f"pages: {doc.page_count}")
    full = "\n".join(doc[i].get_text() for i in range(min(3, doc.page_count)))
    doc.close()
    lines = [ln.strip() for ln in full.splitlines() if ln.strip()]
    print(f"first-3-pages text lines: {len(lines)}")
    print("sample lines:")
    for ln in lines[:25]:
        print(f"   {ln[:90]!r}")
except Exception as e:
    print(f"PDF parse ERROR: {type(e).__name__}: {e}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
