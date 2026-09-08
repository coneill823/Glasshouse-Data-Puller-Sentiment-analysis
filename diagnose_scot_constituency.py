#!/usr/bin/env python3
"""
Recon round 3 (definitive sweep): find the MSP -> Constituency/Region link on
data.parliament.scot. The API has no service doc / $metadata, so we brute-force
a wide list of collection names and fully dump the membership-ish ones (esp.
MemberParties, which may carry a ConstituencyID/RegionID alongside PartyID).

Run on a machine with network access, paste the whole output:

    python diagnose_scot_constituency.py

Throwaway — deleted once the fix is in.
"""
import requests

API = "https://data.parliament.scot/api"
S = requests.Session()
S.headers.update({"Accept": "application/json", "User-Agent": "GlasshouseRecon/1.0"})


def get(path, **params):
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


# 1. FULL dump of MemberParties — does the membership row carry the seat?
hr("1 — MemberParties full fields + samples (look for ConstituencyID / RegionID)")
r = get("MemberParties", **{"$top": 4})
if getattr(r, "status_code", 0) == 200:
    rows = rows_of(r) or []
    print("fields:", list(rows[0].keys()) if rows else "(empty)")
    for row in rows[:4]:
        print("  ", row)
else:
    print("MemberParties ->", getattr(r, "status_code", r))

# 2. Wide brute-force sweep of collection names. Print fields+sample for 200s.
hr("2 — wide collection sweep (200s only shown in full)")
cands = [
    # area
    "Constituencies", "Regions", "ConstituencyRegions", "ConstituencyRegionSeasons",
    "ConstituencyRegionLinks", "ElectionAreas", "ElectoralAreas", "MSPElectionAreas",
    # membership / seat / season
    "MemberSeasons", "Seasons", "ParliamentarySeasons", "SeatMemberships",
    "ParliamentaryMemberships", "MemberSeats", "MemberElectionAreas",
    "MemberConstituencySeasons", "MemberRegionSeasons",
    "MemberElectorate", "MemberTypes", "MembershipTypes", "MemberStatuses",
    # roles / offices / misc member links (to learn the naming convention)
    "MemberRoles", "ParliamentaryRoles", "Roles", "MemberOffices", "Offices",
    "MemberAddresses", "MemberContactDetails", "MemberWebsites", "Websites",
    "MemberCommittees", "Committees", "CommitteeMemberships", "CommitteeMembers",
    # election
    "Elections", "ElectionResults", "MemberElectionResults", "ElectionCandidates",
]
found = []
for c in cands:
    r = get(c, **{"$top": 2})
    code = getattr(r, "status_code", "ERR")
    if code == 200:
        rows = rows_of(r) or []
        fields = list(rows[0].keys()) if rows else []
        found.append(c)
        print(f"  [200] {c}: fields={fields}")
        if rows:
            print(f"        sample={rows[0]}")
    else:
        print(f"  [{code}] {c}")

hr("SUMMARY")
print("collections that returned 200:", found)
print("\nDONE — paste the whole output.")
