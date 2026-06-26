#!/usr/bin/env python3
"""
TEMPORARY reconnaissance for the Scottish votes fix.

Current votes scraping grabs nav junk ("Home", "Chamber and committees") from
SPA-shell motion pages via loose `table tr td` selectors. Since we already fetch
the Official Report PDF per plenary meeting, the cleanest fix may be to extract
divisions from that same PDF. This checks whether the OR PDF carries the full
member-by-member division roll-call and in what format.

  A. OR PDF (meeting 16249, 6 Feb 2025) — find division sections + dump the
     roll-call format (FOR / AGAINST / ABSTENTIONS + member lists)
  B. a current votes-and-motions page (S7M-00511) — confirm it's an SPA shell and
     show what the loose table selector is matching

    python diagnose_scottish_votes.py

Throwaway — removed once the votes fix lands.
"""
import re

import requests

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


# ── A. OR PDF division roll-call ──
hr("A — division content in the OR PDF (meeting 16249)")
try:
    import fitz
    r = sess.get(f"{_WEB}/api/sitecore/CustomMedia/OfficialReport",
                 params={"meetingId": "16249"}, timeout=60)
    doc = fitz.open(stream=r.content, filetype="pdf")
    text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    doc.close()
    print(f"PDF text length: {len(text)}")

    markers = {
        "result of the division": len(re.findall(r"result of the division", text, re.I)),
        "For N, Against": len(re.findall(r"For \d+, Against \d+", text)),
        "FOR (header)": len(re.findall(r"^\s*FOR\s*$", text, re.M)),
        "AGAINST (header)": len(re.findall(r"^\s*AGAINST\s*$", text, re.M)),
        "ABSTENTIONS (header)": len(re.findall(r"^\s*ABSTENTIONS\s*$", text, re.M)),
        "Division (heading)": len(re.findall(r"\bDivision\b", text)),
    }
    print(f"markers: {markers}")

    # Dump context around the first division result + the first FOR header
    m = re.search(r"result of the division", text, re.I)
    if m:
        print("\n--- context around first 'result of the division' (±400 chars) ---")
        print(text[max(0, m.start() - 200): m.start() + 400])

    fm = re.search(r"^\s*FOR\s*$", text, re.M)
    if fm:
        print("\n--- 25 lines from first 'FOR' header (roll-call format) ---")
        tail = text[fm.start():].splitlines()
        for ln in tail[:25]:
            if ln.strip():
                print(f"   {ln.strip()[:80]!r}")
    else:
        print("\nNo standalone 'FOR' header found — roll-call may not be in the OR PDF.")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

# ── B. votes-and-motions page (the current garbage source) ──
hr("B — votes-and-motions page S7M-00511 (is it an SPA shell?)")
r = sess.get(f"{_WEB}/chamber-and-committees/votes-and-motions/S7M-00511", timeout=30)
from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, "lxml")
body_text = soup.get_text(" ", strip=True)
print(f"HTTP {r.status_code} | {len(r.content)} bytes | visible text ~{len(body_text)}")
# what does the loose 'table tr td:nth-child(1)' selector grab?
cells = [td.get_text(strip=True) for td in soup.select("table tr td:nth-child(1)")][:8]
print(f"table tr td:nth-child(1) sample (current 'voters'): {cells}")
# any real voter/division structure?
for sel in [".ayes li", ".noes li", "[class*='division']", "[class*='vote']", "[class*='member']"]:
    n = len(soup.select(sel))
    if n:
        print(f"  selector {sel!r}: {n} elements")
# meeting/OR link on the page?
ids = sorted(set(re.findall(r"meeting=(\d+)", r.text)))
print(f"  meeting ids referenced: {ids[:6]}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
