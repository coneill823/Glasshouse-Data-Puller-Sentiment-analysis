#!/usr/bin/env python3
"""
TEMPORARY Welsh members recon, round 2 — dump the ModernGov web service schema.

GetCouncillorsByWard returns all MSs as clean XML. This dumps the element
inventory + a full sample councillor record so the parser uses the right field
names (id / name / party / ward).

    python diagnose_welsh_members2.py

Throwaway — removed once the members fix lands.
"""
import xml.etree.ElementTree as ET
from collections import Counter

import requests

from scrapers.welsh_parliament import _BUSINESS, _BROWSER_UA

URL = f"{_BUSINESS}/mgwebservice.asmx/GetCouncillorsByWard"
r = requests.get(URL, headers={"User-Agent": _BROWSER_UA}, timeout=40)
print(f"HTTP {r.status_code} | {len(r.content)} bytes | ct={r.headers.get('Content-Type')}")

root = ET.fromstring(r.content)
for el in root.iter():
    if "}" in el.tag:
        el.tag = el.tag.split("}", 1)[1]

tags = Counter(el.tag for el in root.iter())
print(f"\nroot tag: {root.tag}")
print(f"distinct tags ({len(tags)}):")
for tag, n in sorted(tags.items(), key=lambda kv: -kv[1]):
    print(f"  {tag}: {n}")

# The repeated member record: an element that has a name-ish + party-ish child.
def _looks_like_member(el):
    kids = {c.tag.lower() for c in el}
    return any("user" in k or "name" in k for k in kids) and any("party" in k for k in kids)

member = next((el for el in root.iter() if _looks_like_member(el)), None)
if member is None:
    # fallback: deepest repeated element
    member = next((el for el in root.iter() if el.tag.lower() in ("councillor", "member")), None)

print("\n--- first member record (full) ---")
if member is not None:
    print(ET.tostring(member, encoding="unicode")[:1500])
    print(f"\nmember record tag: {member.tag}")
    print(f"member count (same tag): {sum(1 for _ in root.iter(member.tag))}")
else:
    print("could not locate a member record; first 1200 chars of body:")
    print(r.text[:1200])

# Also show a ward wrapper so we see how ward title relates to members
ward = next((el for el in root.iter() if el.tag.lower() == "ward"), None)
if ward is not None:
    print("\n--- first <ward> children tags ---")
    print([c.tag for c in ward])

print("\n" + "=" * 70 + "\nDONE — paste the whole output.\n" + "=" * 70)
