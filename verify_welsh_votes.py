#!/usr/bin/env python3
"""
Live verification for the Welsh votes fix — run against a HISTORICAL window.

The test harness uses the last ~90 days, which for the Senedd is empty (the 6th
Senedd wound down before the May 2026 election). So this checks the fix against
June 2024, where meeting 13950 and friends have rich division data.

It exercises the REAL code path (_fetch_meeting_ids_wales -> _fetch_votes_xml_export).
If discovery returns no meetings, it dumps the raw XMLExport form result so the
discovery parsing can be corrected.

    python verify_welsh_votes.py

Throwaway — deleted once the votes fix is confirmed.
"""
from scrapers.welsh_parliament import WelshParliamentScraper, _RECORD, _PLENARY_COMMITTEE_ID

FROM, TO = "2024-06-01", "2024-06-30"


def main():
    s = WelshParliamentScraper()

    print(f"== Discovery: plenary meetings {FROM} -> {TO} ==")
    meetings = s._fetch_meeting_ids_wales(FROM, TO)
    print(f"meetings found: {len(meetings)}")
    print(f"sample ids: {[m['id'] for m in meetings[:12]]}")

    if not meetings:
        print("\n!! No meetings discovered — dumping raw XMLExport form results for diagnosis.\n")
        import re
        params = {"SelectedCommitteeID": _PLENARY_COMMITTEE_ID,
                  "Start": "01/06/2024", "End": "30/06/2024", "submittingButton": ""}
        # GET
        soup = s._html_get(f"{_RECORD}/XMLExport", params=params)
        g = str(soup)[:2500] if soup else "None"
        print(f"--- GET result (first 2500 chars) ---\n{g}\n")
        # POST
        soup = s._form_post(f"{_RECORD}/XMLExport", params)
        if soup:
            html = str(soup)
            mids = sorted(set(re.findall(r'meetingID=(\d+)', html)), key=lambda x: -int(x))
            print(f"--- POST result: {len(html)} chars, meetingIDs seen: {mids[:12]} ---")
            print(html[:2500])
        else:
            print("--- POST result: None ---")
        return

    print(f"\n== Parsing votes for first 4 meetings ==")
    records = []
    for m in meetings[:4]:
        added = s._fetch_votes_xml_export(m["id"], m.get("date", ""), FROM, records, TO)
        print(f"  meeting {m['id']}: +{added} vote records")

    print(f"\nTotal vote records: {len(records)}")
    if records:
        import json
        print("Sample record:")
        print(json.dumps(records[0], indent=2, default=str)[:900])
        dirs = {}
        for r in records:
            d = r["metadata"]["vote_direction"]
            dirs[d] = dirs.get(d, 0) + 1
        print(f"\nDirection breakdown: {dirs}")
        named = sum(1 for r in records if r["member"]["name"])
        dated = sum(1 for r in records if r["date"])
        print(f"records with member name: {named}/{len(records)} | with date: {dated}/{len(records)}")


if __name__ == "__main__":
    main()
