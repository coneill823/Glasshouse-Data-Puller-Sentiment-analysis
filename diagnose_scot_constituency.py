#!/usr/bin/env python3
"""
Recon round 2: find how data.parliament.scot links an MSP (PersonID) to a
Constituency/Region. Round 1 found Constituencies + Regions (with names) but the
member->area link entity is still unknown and $metadata is disabled.

Run on a machine with network access, paste the whole output:

    python diagnose_scot_constituency.py

Throwaway — deleted once the constituency fix is in.
"""
import re
import requests

API = "https://data.parliament.scot/api"
S = requests.Session()
S.headers.update({"Accept": "application/json",
                  "User-Agent": "GlasshouseRecon/1.0"})


def get(path, **params):
    if params.get("_raw"):
        params.pop("_raw")
    else:
        params.setdefault("$format", "json")
    try:
        return S.get(f"{API}/{path}", params=params, timeout=30)
    except Exception as e:
        return e


def rows_of(r):
    try:
        d = r.json()
    except Exception:
        return None
    return d.get("value", d.get("d", d)) if isinstance(d, dict) else d


def hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# 1. Service document at the API root — lists every collection.
hr("1 — service document (API root)")
for path in ("", "/"):
    try:
        r = S.get(f"{API}{path}", params={"$format": "json"}, timeout=30)
        print(f"GET {API}{path}?$format=json -> HTTP {r.status_code}, {len(r.text)} bytes")
        txt = r.text.strip()
        # JSON list of collections?
        try:
            d = r.json()
            coll = d.get("value") or (d.get("d") or {}).get("EntitySets") or d
            print("  parsed collections:", coll if isinstance(coll, list) else list(d.keys()))
        except Exception:
            print("  raw head:", txt[:1500])
    except Exception as e:
        print(f"GET {API}{path} failed: {type(e).__name__}: {e}")

# 2. Find a current MSP's PersonID, then inspect member-side navigation.
hr("2 — a current MSP + Members(id) detail / $expand")
r = get("Members", **{"$top": 50})
rows = rows_of(r) or []
cur = next((m for m in rows if m.get("IsCurrent")), rows[0] if rows else {})
pid = cur.get("PersonID")
print("sample current MSP:", cur.get("ParliamentaryName"), "PersonID=", pid)
if pid is not None:
    # entity detail (may expose navigation link names)
    r = get(f"Members({pid})")
    print(f"  Members({pid}) -> HTTP {getattr(r,'status_code','ERR')}; keys="
          f"{list((rows_of(r) or {}).keys()) if hasattr(r,'json') else r}")
    base_keys = set(cur.keys())
    for exp in ("MemberConstituencies", "MemberRegions", "MemberConstituencyRegions",
                "ConstituencyMembers", "RegionMembers", "MemberElections",
                "ElectionResults", "MemberElectionResults", "Memberships",
                "MemberSeats", "MemberMandates", "Mandates", "MemberConstituencyStatuses"):
        r = get("Members", **{"$top": 1, "$filter": f"PersonID eq {pid}", "$expand": exp})
        rr = rows_of(r) or []
        if getattr(r, "status_code", 0) == 200 and rr:
            new = {k: rr[0][k] for k in rr[0] if k not in base_keys}
            if new:
                print(f"  $expand={exp}: NEW KEYS -> {str(new)[:400]}")

# 3. Broader entity sweep, incl. election/seat/mandate + reverse links.
hr("3 — broader entity probe")
cands = [
    "MemberConstituencies", "MemberRegions", "MemberConstituencyRegions",
    "MemberElections", "MemberElectionResults", "ElectionResults", "Elections",
    "MemberSeats", "Seats", "MemberMandates", "Mandates",
    "MembershipConstituencies", "MembershipRegions", "MembershipAreas",
    "MemberConstituencyStatuses", "MemberRegionStatuses",
    "ConstituencyMembers", "RegionMembers", "MemberAreas", "MemberElectoralAreas",
]
for c in cands:
    r = get(c, **{"$top": 2})
    code = getattr(r, "status_code", "ERR")
    if code == 200:
        rr = rows_of(r) or []
        print(f"  [200] {c}: fields={list(rr[0].keys()) if rr else '(empty)'}")
        if rr:
            print(f"        sample={rr[0]}")
    else:
        print(f"  [{code}] {c}")

# 4. Reverse: does Constituencies / Regions expand to members?
hr("4 — reverse expand from Constituencies / Regions")
for ent in ("Constituencies", "Regions"):
    for exp in ("Members", "MemberConstituencies", "MemberRegions", "People"):
        r = get(ent, **{"$top": 1, "$expand": exp})
        code = getattr(r, "status_code", "ERR")
        if code == 200:
            rr = rows_of(r) or []
            extra = {k: v for k, v in (rr[0].items() if rr else [])
                     if k not in ("ID", "Name", "ConstituencyCode", "RegionCode",
                                  "ShortName", "ValidFromDate", "ValidUntilDate",
                                  "StartDate", "EndDate", "RegionID")}
            if extra:
                print(f"  {ent}?$expand={exp}: {str(extra)[:400]}")
            else:
                print(f"  {ent}?$expand={exp}: HTTP 200 (no extra keys)")
        else:
            print(f"  {ent}?$expand={exp}: HTTP {code}")

print("\n" + "=" * 72 + "\nDONE — paste the whole output.\n" + "=" * 72)
