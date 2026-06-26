#!/usr/bin/env python3
"""
TEMPORARY Welsh-votes recon, round 5 — crack the XMLExport filter POST.

The Votes PARSER is confirmed live (meeting 13950 -> 427 records). The only open
item is discovery: GET ignores the date filter; POST returns 0 (likely missing
the ASP.NET anti-forgery token / full field set). This GETs the form, harvests
every field (incl. __RequestVerificationToken), then POSTs a proper June-2024
Plenary filter and reports the meeting IDs returned. It also parses the default
listing's rows to see how dates pair with meeting IDs (a client-side-filter
backup).

    python diagnose_welsh_votes5.py

Throwaway — deleted once the votes fix lands.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.welsh_parliament import _RECORD, _BROWSER_UA, _PLENARY_COMMITTEE_ID

URL = f"{_RECORD}/XMLExport"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


# ── 1. GET the form and harvest all fields ──
hr("1 — harvest form fields from GET /XMLExport")
r = sess.get(URL, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
form = next((f for f in soup.find_all("form")
             if f.find(attrs={"name": "SelectedCommitteeID"})
             or "XMLExport" in (f.get("action") or "")), None)
fields = {}
if form is not None:
    print(f"form action={form.get('action')!r} method={form.get('method')!r}")
    for inp in form.find_all("input"):
        n = inp.get("name")
        if n:
            fields[n] = inp.get("value", "")
    for sel in form.find_all("select"):
        n = sel.get("name")
        if n:
            opt = sel.find("option", selected=True) or sel.find("option")
            fields[n] = opt.get("value", "") if opt else ""
    for n, v in fields.items():
        show = v if len(v) < 60 else v[:57] + "..."
        print(f"  {n} = {show!r}")
    print(f"  has anti-forgery token: {'__RequestVerificationToken' in fields}")
else:
    print("!! could not locate the XMLExport form")

# ── 2. Parse the default listing's rows: how do dates pair with meeting IDs? ──
hr("2 — default listing rows (date <-> meetingID pairing)")
rows = soup.find_all("tr")
shown = 0
for tr in rows:
    a = tr.find("a", href=re.compile(r"meetingID=\d+"))
    if not a:
        continue
    mid = re.search(r"meetingID=(\d+)", a["href"]).group(1)
    row_txt = tr.get_text(" ", strip=True)[:90]
    print(f"  meetingID={mid} | row: {row_txt!r}")
    shown += 1
    if shown >= 8:
        break
if not shown:
    print("  (no <tr> rows contained meetingID links — listing uses a different structure)")


# ── 3. Proper POST with the full field set, two date formats ──
def attempt(label, start, end):
    payload = dict(fields)
    payload["SelectedCommitteeID"] = _PLENARY_COMMITTEE_ID
    payload["Start"] = start
    payload["End"] = end
    if "submittingButton" in payload and not payload["submittingButton"]:
        payload["submittingButton"] = "Download"
    try:
        r2 = sess.post(URL, data=payload, timeout=45,
                       headers={"Referer": URL, "Origin": _RECORD})
    except Exception as e:
        print(f"\n[{label}] ERROR {type(e).__name__}: {e}")
        return
    ids = sorted(set(re.findall(r"meetingID=(\d+)", r2.text)), key=int)
    dates = sorted(set(re.findall(r"\d{2}/\d{2}/\d{4}", r2.text)))
    print(f"\n[{label}] start={start} end={end} -> HTTP {r2.status_code} | "
          f"{len(r2.text)} chars | {len(ids)} meetingIDs"
          + (f" | range {ids[0]}..{ids[-1]} | sample {ids[:12]}" if ids else "")
          + f"\n   dd/mm/yyyy dates on page: {dates[:10]}")


hr("3 — proper POST (token + full fields), Plenary, June 2024")
attempt("DD/MM/YYYY", "01/06/2024", "30/06/2024")
attempt("YYYY-MM-DD", "2024-06-01", "2024-06-30")

print("\n" + "=" * 74 + "\nDONE — paste the whole output.\n" + "=" * 74)
