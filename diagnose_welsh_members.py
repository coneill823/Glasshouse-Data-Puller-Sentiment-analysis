#!/usr/bin/env python3
"""
TEMPORARY reconnaissance for the Welsh members fix.

fetch_members currently returns nav junk (the WP REST API 404s, profile-link
scraping finds 0, and card extraction scrapes the menu). This probes the
realistic clean sources, prioritising the ModernGov member index on
business.senedd.wales (we already use mgUserInfo.aspx?UID= for questions):

  A. business.senedd.wales/mgMemberIndex.aspx — ModernGov member list (UID, name,
     party, ward/region) in a few view modes
  B. senedd.wales member listing — SSR vs JS, and what selectors yield members
  C. a couple of members-API guesses

Run on a networked machine and paste the whole output.
Throwaway — removed once the members fix lands.

    python diagnose_welsh_members.py
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.welsh_parliament import _BASE, _BUSINESS, _BROWSER_UA, WelshParliamentScraper

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def get(url, params=None, timeout=20):
    try:
        r = sess.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"


# ── A. ModernGov member index ──
hr("A — business.senedd.wales ModernGov member index")
for path, params in [
    ("/mgMemberIndex.aspx", {"bcr": 1}),
    ("/mgMemberIndex.aspx", {"VW": "LIST", "bcr": 1}),
    ("/mgMemberIndex.aspx", {"VW": "TABLE", "bcr": 1}),
    ("/mgwebservice.asmx", None),  # ModernGov SOAP/REST web service (member data)
]:
    url = _BUSINESS + path
    r, summ = get(url, params=params)
    print(f"\n[{path} {params}]\n  {summ}")
    if r is None or not r.ok:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    # member profile links carry mgUserInfo.aspx?UID=N
    rows = []
    seen = set()
    for a in soup.select("a[href*='mgUserInfo']"):
        m = re.search(r"UID=(\d+)", a.get("href", ""), re.I)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        name = a.get_text(" ", strip=True)
        # row context often carries party + ward
        row = a.find_parent("tr") or a.find_parent("li") or a.find_parent("p")
        ctx = row.get_text(" ", strip=True)[:90] if row else ""
        rows.append((m.group(1), name, ctx))
    print(f"  member (mgUserInfo) links: {len(rows)}")
    for uid, name, ctx in rows[:6]:
        print(f"     UID={uid} name={name!r} ctx={ctx!r}")
    if rows:
        break

# ── B. senedd.wales member listing — SSR vs JS ──
hr("B — senedd.wales member listing structure")
s = WelshParliamentScraper()
for path in ["/find-a-member-of-the-senedd/", "/en/find-a-member-of-the-senedd/",
             "/visit/contact-a-member-of-the-senedd/"]:
    url = _BASE + path
    r, summ = get(url)
    print(f"\n[{path}] {summ}")
    if r is None or not r.ok:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    # any links that look like a member profile slug?
    prof = [a.get("href", "") for a in soup.select("a[href]")
            if re.search(r"/(find-a-member|senedd-members|members|aelod)[\w/-]*/[a-z][a-z-]{3,}/?$", a.get("href", ""), re.I)]
    print(f"  SSR member-profile-ish links: {len(prof)} {prof[:4]}")
    # browser-render and recount
    rendered = s._browser_get(url, wait_selector="a[href*='member'], article, .member, [class*='member']")
    if rendered:
        rprof = [a.get("href", "") for a in rendered.select("a[href]")
                 if re.search(r"/(find-a-member|senedd-members|members|aelod)[\w/-]*/[a-z][a-z-]{3,}/?$", a.get("href", ""), re.I)]
        cards = rendered.select("[class*='member'], article, li.card, .card")
        print(f"  RENDERED member-profile links: {len(rprof)} {rprof[:4]} | candidate cards: {len(cards)}")
    break

# ── C. members-API guesses ──
hr("C — members API guesses")
for url in [f"{_BASE}/api/members", f"{_BASE}/umbraco/api/members/getall",
            "https://business.senedd.wales/mgwebservice.asmx/GetCouncillorsByWard"]:
    r, summ = get(url, timeout=12)
    extra = ""
    if r is not None and r.ok and r.text.strip()[:1] in "[{<":
        extra = f" | starts: {r.text.strip()[:120]!r}"
    print(f"[{url}]\n  {summ}{extra}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
