#!/usr/bin/env python3
"""
TEMPORARY Welsh-votes reconnaissance, round 2.

Round 1 confirmed the record.senedd.wales XMLExport is alive and serves current
6th-Senedd plenary transcripts (meeting IDs ~13000+), but the EnglishTranscript
export shows zero <Division> elements — so the existing parser looks for the
wrong thing. This round answers the three questions needed to write the parser:

  A. Is there a dedicated votes/minutes export type that contains divisions?
     (probes several xmlDownloadType values on a known plenary day)
  B. What does the vote/division data actually look like in the XML?
     (dumps all element tag names + any vote-ish element's structure)
  C. Where do the CURRENT (2026) plenary meeting IDs sit?
     (samples IDs upward and reads each XML's date to map id -> date)

Bounded + short timeouts. Run on a networked machine and paste the whole output.
Throwaway — deleted once the votes fix lands.

    python diagnose_welsh_votes2.py
"""
import re
import xml.etree.ElementTree as ET
from collections import Counter

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RECORD = "https://record.senedd.wales"
EXPORT = f"{RECORD}/XMLExport/Download"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/xml,text/xml,*/*;q=0.8",
                  "Accept-Language": "en-GB,en;q=0.9"})

# A known, sizeable 2024 plenary day from round 1 (700KB transcript).
PLENARY_MID = "13950"   # date 2024-06-19


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def fetch(mid, dl_type="EnglishTranscript", timeout=25):
    try:
        r = S.get(EXPORT, params={"meetingID": str(mid), "xmlDownloadType": dl_type},
                  timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"


def strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


# ── A. Which xmlDownloadType holds divisions? ──
hr("A — xmlDownloadType variants on plenary meeting 13950 (2024-06-19)")
for dl in ["EnglishTranscript", "WelshTranscript", "EnglishMinutes", "Minutes",
           "EnglishVotesAndProceedings", "VotesAndProceedings", "Votes",
           "EnglishVotes", "Division", "Divisions", "EnglishAgenda"]:
    r, summ = fetch(PLENARY_MID, dl, timeout=20)
    sig = ""
    if r is not None and r.ok and "xml" in r.headers.get("Content-Type", ""):
        low = r.text.lower()
        hits = {k: low.count(k) for k in ("division", "vote", "aye", "noe", "abstain",
                                          "against", "ballot", "agreed")
                if low.count(k)}
        sig = f" | keyword counts: {hits}" if hits else " | (no vote keywords)"
    print(f"[{dl}] {summ}{sig}")

# ── B. Dump the transcript schema + any vote-ish element structure ──
hr("B — element tag inventory of EnglishTranscript (meeting 13950)")
r, summ = fetch(PLENARY_MID, "EnglishTranscript", timeout=30)
print(summ)
if r is not None and r.ok and "xml" in r.headers.get("Content-Type", ""):
    try:
        root = strip_ns(ET.fromstring(r.content))
        tags = Counter(el.tag for el in root.iter())
        print(f"\nAll {len(tags)} distinct tags (tag: count):")
        for tag, n in sorted(tags.items(), key=lambda kv: -kv[1]):
            print(f"  {tag}: {n}")

        vote_re = re.compile(r"div|vot|aye|noe|abst|against|\bfor\b|ballot|result|"
                             r"motion|agreed|carried|decision", re.I)
        vote_tags = [t for t in tags if vote_re.search(t)]
        print(f"\nVote-ish tags: {vote_tags}")
        for t in vote_tags[:6]:
            el = next((e for e in root.iter(t)), None)
            if el is not None:
                snippet = ET.tostring(el, encoding="unicode")[:1200]
                print(f"\n--- first <{t}> element ---\n{snippet}")
    except ET.ParseError as e:
        print(f"XML parse error: {e}")
        print("First 800 chars of body:")
        print(r.text[:800])

# ── C. Map meeting-ID -> date to locate the current (2026) plenary band ──
hr("C — id -> date sampling to find the 2026 plenary range")
for mid in [13970, 14100, 14300, 14500, 14700, 14900, 15100, 15300,
            15500, 15700, 15900, 16100, 16300]:
    r, summ = fetch(mid, "EnglishTranscript", timeout=18)
    info = ""
    if r is not None and r.ok and "xml" in r.headers.get("Content-Type", ""):
        dm = re.search(r"<(?:SittingDate|MeetingDate|Date|PlnryDate)>([^<]+)<", r.text)
        d = dm.group(1).strip()[:10] if dm else "?"
        # is it plenary? transcripts include a body/committee name somewhere
        title = re.search(r"<(?:MeetingName|CommitteeName|Title|BodyName)>([^<]{0,60})", r.text)
        tt = f" | name={title.group(1)!r}" if title else ""
        info = f" | date={d}{tt}"
    else:
        info = " | (not XML / error)"
    print(f"[meetingID={mid}] {summ.split(' | final=')[0]}{info}")

print("\n" + "=" * 78 + "\nDONE — paste this entire output back.\n" + "=" * 78)
