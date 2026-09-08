#!/usr/bin/env python3
"""
Recon: how does data.parliament.scot link an MSP (PersonID) to their
constituency or region? The /Members entity doesn't carry the area name, so we
need to find the link + name entities (same shape as MemberParties + Parties).

Run on a machine with network access to data.parliament.scot, then paste the
whole output back:

    python diagnose_scot_constituency.py

Throwaway — deleted once the constituency fix is in.
"""
import re
import requests

API = "https://data.parliament.scot/api"
S = requests.Session()
S.headers.update({"Accept": "application/json",
                  "User-Agent": "GlasshouseRecon/1.0 (constituency recon)"})


def get(path, **params):
    params.setdefault("$format", "json")
    try:
        r = S.get(f"{API}/{path}", params=params, timeout=30)
        return r.status_code, r
    except Exception as e:
        return None, e


def rows_of(r):
    try:
        d = r.json()
    except Exception:
        return None
    if isinstance(d, dict):
        return d.get("value", d.get("d", d))
    return d


def hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# 1. Full entity list from $metadata (version-agnostic).
hr("1 — entity sets ($metadata)")
try:
    meta = S.get(f"{API}/$metadata", timeout=30)
    names = sorted(set(re.findall(r'EntitySet Name="([^"]+)"', meta.text)))
    print(f"HTTP {meta.status_code} — {len(names)} entity sets:")
    print(names)
    # highlight the ones that look area-related
    area = [n for n in names if re.search(r"constitu|region|area|seat|member", n, re.I)]
    print("\narea/member-ish entities:", area)
except Exception as e:
    print("metadata failed:", type(e).__name__, e)

# 2. Members fields — is the area (name or FK id) actually on the member row?
hr("2 — Members fields + any area-ish values")
code, r = get("Members", **{"$top": 3})
if code == 200:
    rows = rows_of(r) or []
    if rows:
        print("fields:", list(rows[0].keys()))
        for m in rows[:3]:
            area = {k: v for k, v in m.items()
                    if re.search(r"constitu|region|area|seat", str(k), re.I)}
            print(f"  {m.get('ParliamentaryName') or m.get('PreferredName')!r}: {area}")
else:
    print("Members ->", code)

# 3. Probe candidate area + link entities; show fields + a sample row.
hr("3 — candidate area / link entities")
candidates = [
    "Constituencies", "Regions", "ElectionAreas", "SeatAreas",
    "MemberConstituencies", "MemberRegions", "MemberConstituency", "MemberRegion",
    "MembersConstituencies", "MembersRegions",
    "MembershipConstituency", "MembershipRegion", "Memberships",
    "MemberElectionAreas", "MemberSeatAreas",
]
for c in candidates:
    code, r = get(c, **{"$top": 2})
    if code == 200:
        rows = rows_of(r) or []
        print(f"  [200] {c}: fields={list(rows[0].keys()) if rows else '(empty)'}")
        if rows:
            print(f"        sample={rows[0]}")
    else:
        print(f"  [{code}] {c}")

# 4. If a current MSP's PersonID is known, show what a Members?$expand reveals.
hr("4 — Members?$expand candidates (inline navigation)")
for exp in ("MemberConstituencies", "MemberRegions", "Constituencies", "Regions",
            "ElectionAreas", "Memberships"):
    code, r = get("Members", **{"$top": 1, "$expand": exp})
    ok = "OK" if code == 200 else f"HTTP {code}"
    detail = ""
    if code == 200:
        rows = rows_of(r) or []
        if rows:
            detail = " -> " + str({k: v for k, v in rows[0].items()
                                   if exp.rstrip("s") in k or k == exp})[:300]
    print(f"  $expand={exp}: {ok}{detail}")

print("\n" + "=" * 72 + "\nDONE — paste the whole output.\n" + "=" * 72)
