#!/usr/bin/env python3
"""
End-to-end verification of the integrated Scottish plenary fix.

Runs the REAL scraper path — fetch_plenary_business — over a historical Session-6
window that definitely had plenary sittings (Jan 2025), exercising browser-driven
discovery -> media-API PDF -> PyMuPDF contribution parsing.

    python verify_scottish_or.py

Throwaway — delete once confirmed.
"""
import json

from scrapers.scottish_parliament import ScottishParliamentScraper

FROM, TO = "2025-01-06", "2025-02-07"


def main():
    s = ScottishParliamentScraper()
    print(f"== fetch_plenary_business({FROM} -> {TO}) ==")
    try:
        records = s.fetch_plenary_business(from_date=FROM, to_date=TO)
    finally:
        s._close_browser()

    print(f"\nplenary records: {len(records)}")
    if records:
        dates = sorted({r["date"] for r in records if r["date"]})
        named = sum(1 for r in records if r["member"]["name"])
        meetings = sorted({r["metadata"].get("meeting_id", "") for r in records})
        print(f"distinct meetings: {len(meetings)} {meetings[:12]}")
        print(f"dates covered: {dates}")
        print(f"records with speaker name: {named}/{len(records)}")
        print("\nsample record:")
        print(json.dumps(records[0], indent=2, default=str)[:700])
        print("\nfirst 6 speakers/snippets:")
        for r in records[:6]:
            print(f"   [{r['member']['name']}] {r['text'][:110]!r}")
    print("\nDONE — paste the whole output.")


if __name__ == "__main__":
    main()
