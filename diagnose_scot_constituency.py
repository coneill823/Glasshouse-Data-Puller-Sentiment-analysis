#!/usr/bin/env python3
"""
Recon round 4 (final): the data.parliament.scot API has no member->constituency
link, but `Websites` gives each MSP's parliament.scot profile URL, which states
their Region/Constituency. This inspects a few current MSPs' profile pages so we
can write the parser.

Run on a machine with network access, paste the whole output:

    python diagnose_scot_constituency.py

Throwaway — deleted once the fix is in.
"""
import re
import requests
from bs4 import BeautifulSoup

API = "https://data.parliament.scot/api"
S = requests.Session()
S.headers.update({
    "Accept": "text/html,application/json",
    "User-Agent": "Mozilla/5.0 (GlasshouseRecon)",
})


def api(path, **params):
    params.setdefault("$format", "json")
    r = S.get(f"{API}/{path}", params=params, timeout=30)
    d = r.json()
    return d.get("value", d) if isinstance(d, dict) else d


def hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# Current MSPs + their profile URLs from Websites.
members = api("Members", **{"$top": 1000})
current = [m for m in members if m.get("IsCurrent")]
websites = api("Websites", **{"$top": 5000})
url_by_person = {}
for w in websites:
    pid = w.get("PersonID")
    if pid is None:
        continue
    # prefer the default / first parliament.scot profile link
    if pid not in url_by_person or w.get("IsDefault"):
        url_by_person[pid] = w.get("WebURL", "")

print(f"current MSPs: {len(current)} | website rows: {len(websites)} | "
      f"profile URLs mapped: {len(url_by_person)}")

# Inspect up to 4 current MSP profile pages.
sample = [m for m in current if url_by_person.get(m.get("PersonID"))][:4]
for m in sample:
    pid = m.get("PersonID")
    url = url_by_person[pid]
    hr(f"{m.get('ParliamentaryName')}  (PersonID {pid})\n{url}")
    try:
        r = S.get(url, timeout=30)
    except Exception as e:
        print("  fetch failed:", type(e).__name__, e)
        continue
    html = r.text
    print(f"  HTTP {r.status_code}, {len(html)} bytes")
    low = html.lower()
    print("  mentions: Region=%s Constituency=%s 'regional member'=%s 'constituency member'=%s"
          % ("Region" in html, "Constituency" in html,
             "regional member" in low, "constituency member" in low))
    soup = BeautifulSoup(html, "lxml")
    # 1) any <dt>/<dd>, <th>/<td>, or label:value lines near Region/Constituency
    for label in ("Region", "Constituency"):
        for tag in soup.find_all(string=re.compile(rf"\b{label}\b")):
            ctx = " ".join(tag.parent.get_text(" ", strip=True).split())[:160]
            nxt = tag.parent.find_next(["dd", "td", "span", "a", "p"])
            nxt_txt = " ".join(nxt.get_text(" ", strip=True).split())[:80] if nxt else ""
            print(f"    [{label}] ctx={ctx!r}  next={nxt_txt!r}")
            break
    # 2) title / meta
    if soup.title:
        print("    <title>:", soup.title.get_text(strip=True)[:120])
    # 3) raw snippets around the words
    for label in ("Region", "Constituency"):
        i = html.find(label)
        if i != -1:
            print(f"    raw around {label!r}: {re.sub(r'\\s+',' ', html[i-40:i+120])!r}")

print("\n" + "=" * 72 + "\nDONE — paste the whole output.\n" + "=" * 72)
