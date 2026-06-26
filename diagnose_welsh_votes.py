#!/usr/bin/env python3
"""
TEMPORARY reconnaissance for the Welsh (Senedd) votes-on-division fix.

The Senedd vote path currently returns 0 because the XMLExport probe is bounded
to old 5th-Senedd committee meeting IDs (6450-6650). This script probes the
realistic *current* sources for Senedd plenary divisions and reports exactly
what each returns, so the real fix can target a confirmed endpoint instead of
guessing.

It makes a small number of bounded requests (short timeouts) and prints a
labelled report. Run it on a machine with network access and paste me the whole
output:

    python diagnose_welsh_votes.py

This file is throwaway — it'll be deleted once the votes fix lands.
"""
import re
import sys
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RECORD = "https://record.senedd.wales"
BUSINESS = "https://business.senedd.wales"
TWFY = "https://www.theyworkforyou.com"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})

PLENARY_LINK_RE = re.compile(r"/[Pp]lenary/(\d{3,6})\b")
MEETINGID_RE = re.compile(r"meeting[Ii][dd]=(\d{3,6})", re.I)


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def get(url, params=None, accept=None, timeout=15):
    """Fetch and return (response or None, one-line summary)."""
    headers = {"Accept": accept} if accept else {}
    try:
        r = S.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    summary = f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"
    return r, summary


def find_plenary_ids(text):
    """Return {id: True} for /Plenary/{id} links and meetingId= refs in text."""
    ids = set(PLENARY_LINK_RE.findall(text or ""))
    ids |= set(MEETINGID_RE.findall(text or ""))
    return sorted(ids, key=lambda x: -int(x))


def recent_sitting_dates(n=8):
    """Last n Senedd sitting-ish days (Tue=1 / Wed=2), newest first."""
    out, d = [], date.today()
    while len(out) < n:
        if d.weekday() in (1, 2):
            out.append(d)
        d -= timedelta(days=1)
    return out


# ── Phase 1: discover current plenary meeting IDs from the Record of Proceedings ──
hr("PHASE 1 — discover current plenary meeting IDs (Record of Proceedings)")
discovered_ids = set()
for url in [f"{RECORD}/", f"{RECORD}/Plenary/", f"{RECORD}/en/Plenary/",
            f"{RECORD}/Search?type=Plenary"]:
    r, summ = get(url)
    print(f"\n[{url}]\n  {summ}")
    if r is not None and r.ok and "html" in r.headers.get("Content-Type", ""):
        ids = find_plenary_ids(r.text)
        if ids:
            print(f"  /Plenary/{{id}} links found: {ids[:15]}")
            discovered_ids.update(ids[:15])
        else:
            # show a few hrefs so we can see the real link shape
            soup = BeautifulSoup(r.text, "lxml")
            hrefs = [a.get("href", "") for a in soup.select("a[href]")]
            plen = [h for h in hrefs if "lenary" in h or "eeting" in h][:12]
            print(f"  no /Plenary/<id> links; plenary-ish hrefs: {plen}")

# ── Phase 2: date → meeting lookups (order paper + meeting-by-date) ──
hr("PHASE 2 — date-based plenary lookups (recent sitting days)")
for d in recent_sitting_dates(6):
    dd = d.strftime("%d-%m-%Y")
    for url in [f"{RECORD}/OrderPaper/Plenary/{dd}/",
                f"{RECORD}/Plenary/?meetingDate={d.isoformat()}"]:
        r, summ = get(url, timeout=12)
        ids = find_plenary_ids(r.text) if (r is not None and r.ok) else []
        note = f" | plenary ids: {ids[:8]}" if ids else ""
        print(f"[{d.isoformat()}] {url}\n   {summ}{note}")
        if ids:
            discovered_ids.update(ids[:8])

# ── Phase 3: test XMLExport on discovered + probed IDs ──
hr("PHASE 3 — XMLExport divisions test")
test_ids = sorted(discovered_ids, key=lambda x: -int(x))[:6]
if not test_ids:
    # Nothing discovered — probe a high band to see where XMLExport still serves data,
    # since the code's empirical 6650 cap predates the current Senedd.
    print("(no IDs discovered in phases 1-2; probing a high band to locate the live range)")
    test_ids = [str(x) for x in range(13900, 13980, 10)] + ["7000", "8000", "9000", "11000", "13000"]
for mid in test_ids:
    url = f"{RECORD}/XMLExport/Download"
    r, summ = get(url, params={"meetingID": mid, "xmlDownloadType": "EnglishTranscript"},
                  accept="application/xml,text/xml,*/*;q=0.8", timeout=20)
    div_count = motion = ""
    if r is not None and r.ok and "html" not in r.headers.get("Content-Type", ""):
        body = r.text
        n_div = body.count("<Division")
        n_div2 = len(re.findall(r"<Division\b", body))
        div_count = f" | <Division> count: {max(n_div, n_div2)}"
        mt = re.search(r"<MotionText>([^<]{0,80})", body)
        if mt:
            motion = f" | sample motion: {mt.group(1)!r}"
        # also surface the date tag so we can confirm which Senedd it's from
        dm = re.search(r"<(?:SittingDate|MeetingDate|Date|PlnryDate)>([^<]+)<", body)
        if dm:
            motion += f" | date: {dm.group(1).strip()[:10]!r}"
    print(f"[meetingID={mid}] {summ}{div_count}{motion}")

# ── Phase 4: business.senedd.wales (ModernGov?) ──
hr("PHASE 4 — business.senedd.wales (ModernGov check)")
for url in [f"{BUSINESS}/", f"{BUSINESS}/mgManageBusiness.aspx"]:
    r, summ = get(url, timeout=12)
    sig = ""
    if r is not None and r.ok:
        low = r.text.lower()
        markers = [m for m in ("moderngov", "mgmanage", "ielistmeetings", "mgvote",
                               "ieissue", "democracy") if m in low]
        sig = f" | ModernGov markers: {markers}"
    print(f"[{url}]\n  {summ}{sig}")

# ── Phase 5: TheyWorkForYou ParlParse (independent machine-readable source) ──
hr("PHASE 5 — TheyWorkForYou / ParlParse Senedd data")
for url in [f"{TWFY}/pwdata/scrapedxml/senedd/",
            f"{TWFY}/pwdata/scrapedxml/senedd-votes/",
            "https://www.theyworkforyou.com/senedd/"]:
    r, summ = get(url, timeout=15)
    extra = ""
    if r is not None and r.ok:
        files = re.findall(r'href="(senedd[\w./-]*\.xml)"', r.text)
        if files:
            extra = f" | newest xml files: {sorted(files)[-5:]}"
        elif "division" in r.text.lower():
            extra = " | page mentions 'division'"
    print(f"[{url}]\n  {summ}{extra}")

print("\n" + "=" * 78)
print("DONE — paste this entire output back.")
print("=" * 78)
