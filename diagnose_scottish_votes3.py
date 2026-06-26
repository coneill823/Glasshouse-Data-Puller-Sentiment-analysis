#!/usr/bin/env python3
"""
TEMPORARY Scottish votes deep-dive, round 2 — find the Votes search + roll-call.

Round 1: the votes-and-motions pages are server-side rendered (no XHR API), and
the landing is a *motion* search that points to a separate *Votes search*. This
fetches over plain HTTP: locates the Votes-search URL, lists divisions, and dumps
a division's per-member For/Against/Abstain structure so we can parse it.

    python diagnose_scottish_votes3.py

Throwaway — removed once the votes source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})
BASE = f"{_WEB}/chamber-and-committees/votes-and-motions"


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def get(url, params=None, timeout=25):
    try:
        r = sess.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    return r, f"HTTP {r.status_code} | {len(r.content)} bytes | final={r.url}"


# ── 1. landing: confirm SSR + find the Votes-search link ──
hr("1 — landing page (plain HTTP): SSR + Votes-search link")
r, summ = get(BASE)
print(summ)
votes_search_url = None
if r is not None and r.ok:
    soup = BeautifulSoup(r.text, "lxml")
    txt = soup.get_text(" ", strip=True)
    print(f"  visible text ~{len(txt)} | [class*='vote'] els: {len(soup.select('[class*=vote]'))}")
    # anchors mentioning votes
    for a in soup.select("a[href]"):
        t = a.get_text(" ", strip=True).lower()
        h = a.get("href", "")
        if "vote" in t and "motion" not in t and ("search" in t or "vote" in h.lower()):
            print(f"  vote-search-ish link: text={a.get_text(' ', strip=True)!r} href={h}")
            if not votes_search_url and "/votes-and-motions" in h:
                votes_search_url = h if h.startswith("http") else _WEB + h
    # any query-style hint
    forms = [(f.get("action"), [i.get("name") for i in f.find_all(["input", "select"])]) for f in soup.find_all("form")]
    print(f"  forms: {forms[:4]}")

# ── 2. probe Votes-search URL candidates ──
hr("2 — Votes-search candidates")
candidates = [votes_search_url] if votes_search_url else []
candidates += [f"{BASE}/votes", f"{BASE}?searchType=Votes", f"{BASE}?type=Votes",
               f"{BASE}?tab=votes", f"{_WEB}/chamber-and-committees/votes"]
division_links = []
for url in [c for c in candidates if c]:
    r, summ = get(url)
    print(f"\n[{url}]\n  {summ}")
    if r is None or not r.ok:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    # division detail links (often /votes-and-motions/<...>/vote/<id> or ?vote=)
    links = sorted(set(
        a.get("href", "") for a in soup.select("a[href]")
        if re.search(r"vote", a.get("href", ""), re.I) and "motion" not in a.get("href", "").lower()))
    print(f"  vote-ish links: {len(links)} {links[:6]}")
    # vote/division result rows
    for sel in ["[class*='vote-result']", "[class*='division']", "[class*='result']", "article", "li[class*='vote']"]:
        n = len(soup.select(sel))
        if n:
            print(f"  selector {sel!r}: {n}")
    if links:
        division_links = [l if l.startswith("http") else _WEB + l for l in links]
        break

# ── 3. a division detail: per-member roll-call structure ──
hr("3 — division detail structure (For/Against/Abstain + members)")
target = division_links[0] if division_links else None
print(f"target division: {target}")
if target:
    r, summ = get(target)
    print(f"  {summ}")
    if r is not None and r.ok:
        soup = BeautifulSoup(r.text, "lxml")
        txt = soup.get_text(" ", strip=True)
        print(f"  visible text ~{len(txt)}")
        for sel in [".ayes li", ".noes li", "[class*='for'] li", "[class*='against'] li",
                    "[class*='vote'] li", "[class*='member']", "table tr", "[class*='for']", "[class*='against']"]:
            els = soup.select(sel)
            if els:
                sample = els[0].get_text(' ', strip=True)[:60]
                print(f"  {sel!r}: {len(els)} | first: {sample!r}")
        # look for 'For'/'Against'/'Abstentions' headings with following names
        for kw in ["For", "Against", "Abstentions", "Abstain"]:
            i = txt.find(kw)
            if i != -1:
                print(f"  …{kw}: {txt[i:i+120]!r}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
