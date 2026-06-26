#!/usr/bin/env python3
"""
TEMPORARY Welsh-votes reconnaissance, round 3 (final).

Round 2 found the divisions live in xmlDownloadType=Votes (not the transcript,
not <Division>). This dumps that export's exact schema so the parser can be
written correctly, and probes a few cheap meeting-index sources so discovery
doesn't have to scan thousands of IDs.

    python diagnose_welsh_votes3.py

Throwaway — deleted once the votes fix lands.
"""
import re
import xml.etree.ElementTree as ET
from collections import Counter

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RECORD = "https://record.senedd.wales"
BUSINESS = "https://business.senedd.wales"
EXPORT = f"{RECORD}/XMLExport/Download"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})

VOTES_MID = "13950"   # known plenary day 2024-06-19 with rich vote data


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def get(url, params=None, accept=None, timeout=25):
    headers = {"Accept": accept} if accept else {}
    try:
        r = S.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"


def strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


# ── 1. The Votes export schema (the decisive piece) ──
hr("1 — Votes export schema for meeting 13950")
r, summ = get(EXPORT, params={"meetingID": VOTES_MID, "xmlDownloadType": "Votes"},
              accept="application/xml,text/xml,*/*;q=0.8", timeout=35)
print(summ)
if r is not None and r.ok and "xml" in r.headers.get("Content-Type", ""):
    try:
        root = strip_ns(ET.fromstring(r.content))
        print(f"\nroot tag: {root.tag}")
        tags = Counter(el.tag for el in root.iter())
        print(f"\nAll {len(tags)} distinct tags (tag: count):")
        for tag, n in sorted(tags.items(), key=lambda kv: -kv[1]):
            print(f"  {tag}: {n}")

        # Top-level records are the children of root. Print the first 2 in full.
        children = list(root)
        print(f"\nroot has {len(children)} direct children; first child tag: "
              f"{children[0].tag if children else 'none'}")
        for i, child in enumerate(children[:2]):
            print(f"\n--- full record #{i} ---")
            print(ET.tostring(child, encoding="unicode")[:1600])

        # Show the distinct values of any field that looks like a vote direction,
        # so we know the exact tokens ("For"/"Against"/"Abstain"/"Did not vote"…).
        dir_re = re.compile(r"vote|direction|result|cast|aye|content|for$", re.I)
        dir_tags = [t for t in tags if dir_re.search(t)]
        print(f"\ndirection-ish tags: {dir_tags}")
        for t in dir_tags:
            vals = Counter((el.text or "").strip() for el in root.iter(t))
            sample = dict(list(vals.items())[:12])
            print(f"  <{t}> distinct values (sample): {sample}")
    except ET.ParseError as e:
        print(f"XML parse error: {e}\nFirst 800 chars:\n{r.text[:800]}")

# ── 2. Cheap meeting-index probes (so discovery isn't a brute scan) ──
hr("2 — meeting-index probes")
index_urls = [
    (f"{RECORD}/XMLExport", None),
    (f"{RECORD}/sitemap.xml", None),
    # ModernGov calendar/agenda listings carry meeting links with numeric ids
    (f"{BUSINESS}/mgCalendarMonthView.aspx", {"GL": 1, "bcr": 1}),
    (f"{BUSINESS}/ieDocHome.aspx", {"bcr": 1}),
    (f"{BUSINESS}/mgListPlanning.aspx", None),
]
for url, params in index_urls:
    r, summ = get(url, params=params, timeout=15)
    extra = ""
    if r is not None and r.ok:
        mids = sorted(set(re.findall(r"meeting[Ii][dd]=(\d{3,6})", r.text)
                          + re.findall(r"/[Pp]lenary/(\d{3,6})", r.text)), key=lambda x: -int(x))
        mg = sorted(set(re.findall(r"[?&](?:MId|Id)=(\d{2,6})", r.text)), key=lambda x: -int(x))
        if mids:
            extra += f" | record meetingIds: {mids[:10]}"
        if mg:
            extra += f" | ModernGov MIds: {mg[:10]}"
        if not mids and not mg and "xml" in r.headers.get("Content-Type", ""):
            extra += f" | (xml, first 160 chars: {r.text[:160]!r})"
    print(f"[{url}]\n  {summ}{extra}")

# ── 3. Confirm the Votes export works on the most-recent known meeting (15700) ──
hr("3 — Votes export on most-recent known meeting (15700, ~2025-11-05)")
r, summ = get(EXPORT, params={"meetingID": "15700", "xmlDownloadType": "Votes"},
              accept="application/xml,text/xml,*/*;q=0.8", timeout=30)
print(summ)
if r is not None and r.ok and "xml" in r.headers.get("Content-Type", ""):
    low = r.text.lower()
    print(f"  keyword counts: vote={low.count('vote')} against={low.count('against')} "
          f"abstain={low.count('abstain')} agreed={low.count('agreed')}")
    dm = re.search(r"<MeetingDate>([^<]+)<", r.text)
    print(f"  MeetingDate: {dm.group(1).strip()[:10] if dm else '?'}")

print("\n" + "=" * 78 + "\nDONE — paste this entire output back.\n" + "=" * 78)
