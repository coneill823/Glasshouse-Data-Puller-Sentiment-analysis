#!/usr/bin/env python3
"""
TEMPORARY Scottish-plenary recon, round 2 — find the meetingId / OR content API.

Round 1: OData 404s; OR is behind a search interface; date-slug pages are JS
shells. The media API (CustomMedia/OfficialReport?meetingId=N) is the likely
content source — this hunts for where the real meetingId now lives, and tests a
known HISTORICAL sitting to separate "election gap" from "format changed".

  A. fetch date-slug OR pages (recent + historical Session-6 dates); compare sizes
     and scrape the HTML/JS for meetingId / itemId / reportId / CustomMedia refs
  B. render a date-slug page in a browser — does the transcript populate? extract
     any meetingId from the live DOM
  C. test the CustomMedia OR media API with any meetingId found
  D. hunt the OR search API referenced by the search page's JS

    python diagnose_scottish_plenary2.py

Throwaway — deleted once the plenary fix lands.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import ScottishParliamentScraper, _WEB, _BROWSER_UA

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})
s = ScottishParliamentScraper()

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def slug_url(iso):
    y, mo, d = iso.split("-")
    return (f"{_WEB}/chamber-and-committees/official-report/what-was-said-in-parliament/"
            f"official-report-{int(d)}-{MONTHS[int(mo)-1]}-{y}")


def get(url, params=None, timeout=20):
    try:
        r = sess.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes"


def hunt_ids(html, label):
    pats = {
        "meetingId": r"meetingId['\"=:\s]+([A-Za-z0-9-]{2,40})",
        "itemId/GUID": r"(?:itemId|ItemId|item-id)['\"=:\s]+([{(]?[0-9A-Fa-f-]{8,38}[})]?)",
        "reportId": r"reportId['\"=:\s]+([A-Za-z0-9-]{2,40})",
        "CustomMedia": r"(/api/sitecore/[A-Za-z]+/[A-Za-z]+)",
        "data-*-id": r'data-[\w-]*id="([^"]{2,40})"',
    }
    print(f"  [{label}] id hunt:")
    for name, pat in pats.items():
        hits = sorted(set(re.findall(pat, html)))[:6]
        if hits:
            print(f"     {name}: {hits}")


# ── A. date-slug pages: recent vs historical, sizes + id hunt ──
hr("A — date-slug OR pages (recent + historical) — sizes + embedded ids")
DATES = ["2026-06-24", "2025-03-05", "2024-12-04", "2023-11-08"]
for iso in DATES:
    url = slug_url(iso)
    r, summ = get(url)
    print(f"\n[{iso}] {summ}\n  {url}")
    if r is not None and r.ok:
        hunt_ids(r.text, iso)
        # any visible OR-ish paragraph text?
        txt = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
        print(f"  visible text length: {len(txt)}")

# ── B. render a recent + a historical page; does the transcript populate? ──
hr("B — browser-rendered date-slug pages")
for iso in ["2026-06-24", "2024-12-04"]:
    rendered = s._browser_get(slug_url(iso),
                              wait_selector="[class*='contribution'], [class*='speech'], .or-report, p")
    if not rendered:
        print(f"[{iso}] render failed / Playwright unavailable")
        continue
    txt = rendered.get_text(" ", strip=True)
    paras = rendered.select("p, [class*='contribution'], [class*='speech']")
    print(f"[{iso}] rendered text length: {len(txt)} | candidate paragraphs: {len(paras)}")
    hunt_ids(str(rendered), f"{iso}-rendered")
    if len(txt) > 5000:
        print(f"   sample: {txt[:300]!r}")

# ── C. media API with any meetingId we can scrape from the recent page ──
hr("C — CustomMedia OR media API test")
r, _ = get(slug_url("2026-06-24"))
mids = sorted(set(re.findall(r"meetingId['\"=:\s]+([A-Za-z0-9-]{2,40})", r.text))) if r else []
print(f"meetingIds scraped from recent page: {mids[:8]}")
for mid in mids[:3]:
    r2, summ = get(f"{_WEB}/api/sitecore/CustomMedia/OfficialReport",
                   params={"meetingId": mid}, timeout=25)
    body = len(r2.text.strip()) if (r2 is not None and r2.ok) else 0
    print(f"[meetingId={mid}] {summ} | body chars={body}")

# ── D. hunt the OR search API ──
hr("D — OR search page: referenced API endpoints")
r, summ = get(f"{_WEB}/chamber-and-committees/official-report/"
              f"search-what-was-said-in-parliament")
print(summ)
if r is not None and r.ok:
    eps = sorted(set(re.findall(r'["\'](/[A-Za-z][\w/.-]*(?:[Ss]earch|[Rr]eport|[Aa]pi|sitecore)[\w/.-]*)["\']',
                                r.text)))
    print(f"referenced endpoints: {eps[:20]}")
    scripts = [sc.get("src", "") for sc in BeautifulSoup(r.text, "lxml").select("script[src]")]
    print(f"script srcs (sample): {[x for x in scripts if x][:8]}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
