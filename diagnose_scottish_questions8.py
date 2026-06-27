#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 8 — result-card structure.

Round 7 settled the mechanism: search is a plain SSR GET with
  ?msp=&qry=&qryref=&dateSelect=<GUID>|<from>|<to>&page=N
date-bounded, paginated 10/page. The page is ~27 KB per result, so each card
very likely holds the full question + answer inline (no detail fetch needed).

This dumps the FIRST result card from a date-bounded search: its container
class, its text lines (so we see the labelled fields), and its raw HTML — so we
can write a direct card parser instead of fetching every detail page.

    python diagnose_scottish_questions8.py

Throwaway — removed once the questions source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

PAGE = f"{_WEB}/chamber-and-committees/questions-and-answers"
GUID = "acfe09e8571447b6ac663f6362a20f42"
REF_RE = re.compile(r"S\dW-\d+|S\dO-\d+|S\dF-\d+")
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


ds = f"{GUID}|Sunday, Jun 1, 2025|Monday, Jun 30, 2025"
r = sess.get(PAGE, params={"msp": "", "qry": "", "qryref": "", "dateSelect": ds},
             timeout=30, headers={"Referer": PAGE})
soup = BeautifulSoup(r.text, "lxml")
print(f"HTTP {r.status_code} | {len(r.text)} bytes")

# ── 1. which repeating container holds the refs? ──
hr("1 — candidate card containers (class -> #elements whose text has a ref)")
counts = {}
for el in soup.find_all(True):
    if not el.get("class"):
        continue
    txt = el.get_text(" ", strip=True)
    if REF_RE.search(txt) and len(txt) < 4000:
        cls = ".".join(el.get("class"))
        counts[cls] = counts.get(cls, 0) + 1
for cls, n in sorted(counts.items(), key=lambda kv: -kv[1])[:25]:
    print(f"  {n:3d}  .{cls}")

# ── 2. locate the FIRST card: smallest ancestor of ref #1 holding a date too ──
hr("2 — first result card: text lines")
first_ref = REF_RE.search(r.text)
card = None
if first_ref:
    ref = first_ref.group(0)
    node = soup.find(string=re.compile(re.escape(ref)))
    el = node.parent if node else None
    # walk up until the block also carries a 'Date'/'Answer'/'Asked' label (full card)
    while el is not None:
        t = el.get_text(" ", strip=True)
        if re.search(r"Date lodged|Answered|Asked by|Current status", t, re.I) and len(t) < 6000:
            card = el
            break
        el = el.parent
    print(f"  first ref: {ref}  | card tag/class: "
          f"{(card.name, card.get('class')) if card else 'NOT FOUND'}")
if card is None:
    # fall back to the largest ref-bearing block under the listing
    card = soup.find(lambda e: e.get("class") and REF_RE.search(e.get_text(" ", strip=True) or ""))
if card is not None:
    lines = [re.sub(r"\s+", " ", ln).strip()
             for ln in card.get_text("\n", strip=True).split("\n")]
    lines = [ln for ln in lines if ln]
    for ln in lines[:40]:
        print(f"    | {ln[:160]}")

# ── 3. raw HTML of the card ──
hr("3 — first card: raw HTML (truncated 3500)")
if card is not None:
    print(card.prettify()[:3500])

# ── 4. the links inside the card (ref/detail anchors) ──
hr("4 — anchors inside the card")
if card is not None:
    for a in card.find_all("a", href=True)[:10]:
        print(f"    href={a['href'][:90]!r}  text={a.get_text(' ', strip=True)[:50]!r}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
