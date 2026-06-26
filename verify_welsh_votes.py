#!/usr/bin/env python3
"""
Live end-to-end verification of the Welsh votes fix.

A. Discovery — recent plenary meetings (with their date + has_votes flag).
B. Full path — fetch_votes_on_division() over the last 90 days (the real code the
   pipeline runs); the current 7th Senedd is sitting and voting, so this should
   return real division records.
C. Historical sanity — directly parse the 6th Senedd meeting 13950 (2024-06-19).

    python verify_welsh_votes.py

Throwaway — deleted once the votes fix is confirmed.
"""
import json
from datetime import date, timedelta

from scrapers.welsh_parliament import WelshParliamentScraper

RECENT = (date.today() - timedelta(days=90)).isoformat()


def breakdown(recs):
    dirs = {}
    for r in recs:
        d = r["metadata"]["vote_direction"]
        dirs[d] = dirs.get(d, 0) + 1
    return dirs


def main():
    s = WelshParliamentScraper()

    print("=" * 70)
    print(f"A. Discovery — division-bearing plenary meetings since {RECENT}")
    print("=" * 70)
    meetings = s._fetch_meeting_ids_wales(RECENT)
    print(f"meetings with votes: {len(meetings)}")
    for m in meetings[:12]:
        print(f"   id={m['id']}  date={m['date']}  has_votes={m['has_votes']}")

    print("\n" + "=" * 70)
    print("B. Full path — fetch_votes_on_division(last 90 days)")
    print("=" * 70)
    recs = s.fetch_votes_on_division(from_date=RECENT)
    print(f"vote records: {len(recs)}")
    if recs:
        print(f"direction breakdown: {breakdown(recs)}")
        print(f"dates covered: {sorted({r['date'][:10] for r in recs if r['date']})}")
        named = sum(1 for r in recs if r['member']['name'])
        print(f"records with member name: {named}/{len(recs)}")
        print("sample record:")
        print(json.dumps(recs[0], indent=2, default=str)[:750])
    else:
        print("(no recent votes — if discovery in A found meetings, check the log above)")

    print("\n" + "=" * 70)
    print("C. Historical sanity — 6th Senedd meeting 13950 (2024-06-19)")
    print("=" * 70)
    recs2 = []
    s._fetch_votes_xml_export("13950", "2024-06-19", None, recs2)
    print(f"meeting 13950: {len(recs2)} vote records "
          f"({breakdown(recs2) if recs2 else 'none'})")

    print("\n" + "=" * 70)
    print("DONE — paste the whole output.")
    print("=" * 70)


if __name__ == "__main__":
    main()
