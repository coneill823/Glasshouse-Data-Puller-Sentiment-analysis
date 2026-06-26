#!/usr/bin/env python3
"""
TEMPORARY reconnaissance for the Scottish plenary (Official Report) fix.

Scottish plenary returns 0: the OR media API needs meeting IDs, but the OData
meeting entities 404, so discovery yields nothing and the fallbacks (broken
since the Session 7 rebuild) find no transcripts. This probes the realistic
current sources so the fix can target a confirmed one:

  1. the scraper's own _fetch_meeting_ids() (does OData yield any sittings?)
  2. the OData service document (which entity sets actually exist?)
  3. the Official Report website (how are current OR sessions linked — meetingId,
     date slug, GUID?) — tried plain and, if empty, browser-rendered
  4. the OR media API + a recent date-slug OR page (do they return transcript text?)

Bounded + short timeouts. Run on a networked machine and paste the whole output.
Throwaway — deleted once the plenary fix lands.

    python diagnose_scottish_plenary.py
"""
import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import ScottishParliamentScraper, _API, _WEB, _BROWSER_UA

RECENT = (date.today() - timedelta(days=120)).isoformat()
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def get(url, params=None, accept=None, timeout=20):
    headers = {"Accept": accept} if accept else {}
    try:
        r = sess.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"


# ── 1. The scraper's own meeting-ID discovery ──
hr("1 — scraper _fetch_meeting_ids(last 120 days)")
s = ScottishParliamentScraper()
try:
    meetings = s._fetch_meeting_ids(RECENT)
    print(f"meetings found: {len(meetings)}")
    for m in meetings[:6]:
        print(f"   {m}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    meetings = []

# ── 2. OData service document — what entity sets exist? ──
hr("2 — OData service document (data.parliament.scot/api)")
r, summ = get(_API + "/", params={"$format": "json"})
print(summ)
if r is not None and r.ok:
    try:
        names = [e.get("name") or e.get("url") for e in r.json().get("value", [])]
        print(f"entity sets ({len(names)}): {sorted(n for n in names if n)}")
    except Exception:
        # XML service doc fallback
        names = re.findall(r'(?:Name|href)="([^"]+)"', r.text)
        print(f"names in service doc: {sorted(set(names))[:40]}")

# ── 3. Official Report website — how are current sessions linked? ──
hr("3 — Official Report website link structure")
or_paths = [
    "/chamber-and-committees/official-report",
    "/chamber-and-committees/official-report/what-was-said-in-parliament",
    "/chamber-and-committees/meeting-of-the-parliament",
]
for path in or_paths:
    url = _WEB + path
    r, summ = get(url, timeout=20)
    print(f"\n[{path}]\n  {summ}")
    if r is None or not r.ok:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    hrefs = [a.get("href", "") for a in soup.select("a[href]")]
    or_links = [h for h in hrefs if re.search(r"official-report-\d|meetingid=|/or-\d|\d{4}-\d{2}-\d{2}", h, re.I)]
    print(f"  OR-session links (plain HTML): {len(or_links)} | sample: {or_links[:5]}")
    mids = sorted(set(re.findall(r"meetingId=(\w[\w-]*)", r.text, re.I)))
    if mids:
        print(f"  meetingId refs: {mids[:8]}")
    if not or_links:
        rendered = s._browser_get(url, wait_selector="a[href*='official-report-'], a[href*='meetingId']")
        if rendered:
            rh = [a.get("href", "") for a in rendered.select("a[href]")]
            rlinks = [h for h in rh if re.search(r"official-report-\d|meetingid=|\d{4}-\d{2}-\d{2}", h, re.I)]
            print(f"  OR-session links (RENDERED): {len(rlinks)} | sample: {rlinks[:5]}")

# ── 4. OR media API + recent date-slug OR page ──
hr("4 — OR media API + date-slug OR page")
sample_ids = [m["id"] for m in meetings[:3]] if meetings else []
for mid in sample_ids:
    r, summ = get(f"{_WEB}/api/sitecore/CustomMedia/OfficialReport",
                  params={"meetingId": mid}, accept="text/html,*/*", timeout=25)
    has_text = (len(r.text.strip()) > 500) if (r is not None and r.ok) else False
    print(f"[mediaAPI meetingId={mid}] {summ} | body>500chars={has_text}")

months = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
shown = 0
for iso in [(date.today() - timedelta(days=k)).isoformat() for k in range(0, 120)]:
    wd = date.fromisoformat(iso).weekday()
    if wd not in (1, 2, 3):   # Tue/Wed/Thu sittings
        continue
    y, mo, d = iso.split("-")
    slug = f"official-report-{int(d)}-{months[int(mo)-1]}-{y}"
    url = f"{_WEB}/chamber-and-committees/official-report/what-was-said-in-parliament/{slug}"
    r, summ = get(url, timeout=15)
    body_len = len(BeautifulSoup(r.text, "lxml").get_text(strip=True)) if (r is not None and r.ok) else 0
    is_shell = body_len < 1500
    print(f"[{iso}] {slug} -> {summ.split(' | final=')[0]} | text~{body_len}{' (shell)' if is_shell else ' <-- CONTENT'}")
    shown += 1
    if shown >= 5:
        break

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
