#!/usr/bin/env python3
"""
TEMPORARY Scottish votes deep-dive, round 5 (final) — dump roll-call markup.

The motion page (SSR) contains the per-member roll-call (member links to
/msps/current-and-previous-msps/, grouped by party then For/Against/Abstained/
Did-not-vote). This dumps the exact markup around the headings + member links so
the parser can map each member to a direction.

    python diagnose_scottish_votes6.py

Throwaway — removed once the votes parser is built.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

MOTION = f"{_WEB}/chamber-and-committees/votes-and-motions/S7M-00454"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA})

r = sess.get(MOTION, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
print(f"HTTP {r.status_code} | {len(r.content)} bytes")

# member vote links
links = soup.select("a[href*='/msps/current-and-previous-msps/']")
# exclude the 'Submitted by' link at top — keep those inside the votes area
print(f"\nmember (msps) links total: {len(links)}")

# Find the container that holds the roll-call (has many member links + 'For'/'Against')
def density(el):
    return len(el.select("a[href*='/msps/current-and-previous-msps/']"))

container = None
for el in soup.find_all(["div", "section"]):
    if density(el) >= 10 and ("For" in el.get_text() or "against" in el.get_text().lower()):
        container = el
if container is not None:
    # find a deeper but still dense wrapper
    for child in container.find_all(["div", "section"]):
        if density(child) >= 10 and density(child) < density(container):
            container = child
            break

print("\n=== classes on roll-call elements ===")
# headings/labels near the For/Against groupings
for el in (container or soup).find_all(True):
    t = el.get_text(" ", strip=True)
    if t in ("For", "Against", "Abstained", "Did not vote") or re.match(r"^(For|Against|Abstained|Did not vote)$", t):
        print(f"  heading <{el.name} class={el.get('class')}> text={t!r}")

print("\n=== first 3 member links + their ancestry (class chain) ===")
for a in (container or soup).select("a[href*='/msps/current-and-previous-msps/']")[:3]:
    chain = []
    p = a
    for _ in range(5):
        p = p.parent
        if p is None:
            break
        chain.append(f"{p.name}.{'.'.join(p.get('class', []) or [])}")
    print(f"  name={a.get_text(strip=True)!r} href={a.get('href')}")
    print(f"    ancestry: {' > '.join(chain)}")

print("\n=== HTML of the roll-call container (first 2600 chars) ===")
if container is not None:
    print(container.decode()[:2600])
else:
    # fall back: dump around the first 'For ' heading
    i = r.text.find(">For<")
    print(r.text[max(0, i-400): i+2200] if i != -1 else "container not found")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
