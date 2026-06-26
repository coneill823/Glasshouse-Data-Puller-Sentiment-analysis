#!/usr/bin/env python3
"""
Lock the Scottish OR production mechanism before integrating.

Confirmed so far: browser search returns plenary meetings (code
"meeting-of-parliament"), the media API returns the full OR PDF, PyMuPDF parses
clean (speaker -> text) contributions. This run confirms the exact approach the
scraper will use:

  A. DISCOVERY by direct URL navigation for a custom date range (no fragile form
     driving): build the search URL with dtDateFrom/dtDateTo + showPlenary, load
     it in a browser, and read the rendered plenary meeting IDs + pagination info.
  B. PARSE a real PLENARY OR PDF (not just the committee one).

    python verify_scottish_or.py

Throwaway — folded into the scraper once confirmed.
"""
import re
import time
from urllib.parse import urlencode

import requests

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
MEDIA = f"{_WEB}/api/sitecore/CustomMedia/OfficialReport"

# A historical Session-6 window that definitely had plenary sittings.
FROM, TO = "2025-01-06", "2025-02-07"


def extract(html):
    """Map meeting_id -> (slug, date). Slug 'meeting-of-parliament' == plenary."""
    out = {}
    for m in re.finditer(r"search-what-was-said-in-parliament/([\w-]+?)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
        out[m.group(3)] = (m.group(1), m.group(2))
    return out


def _dismiss_cookies(page):
    for sel in ["#ccc-recommended-settings", "#ccc-notify-accept", ".ccc-accept-button"]:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
    try:
        page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay').forEach(e=>e.remove()); }")
    except Exception:
        pass


def discover(from_date, to_date):
    from playwright.sync_api import sync_playwright
    params = {
        "qry": "", "msp": "", "committeeSelect": "", "dateSelect": "custom",
        "dtDateFrom": from_date, "dtDateTo": to_date,
        "showPlenary": "true", "ShowDebates": "true", "ShowFMQs": "true",
        "ShowGeneralQuestions": "true", "ShowPortfolioQuestions": "true",
        "ShowSPCBQuestions": "true", "ShowTopicalQuestions": "true",
        "ShowUrgentQuestions": "true", "ResultDisplayType": "Reports",
    }
    url = f"{SEARCH}?{urlencode(params)}"
    print(f"navigating browser to custom-range URL ({from_date} -> {to_date})…")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(user_agent=_BROWSER_UA)
        page.set_default_timeout(25000)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        _dismiss_cookies(page)
        # poll until meeting links stabilise
        last, stable = -1, 0
        deadline = time.time() + 35
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            n = len(re.findall(r"meeting=\d+", page.content()))
            if n == last and n > 0:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last = n

        html = page.content()
        rc = ""
        loc = page.locator("#resultCount")
        try:
            if loc.count():
                rc = loc.first.inner_text()
        except Exception:
            pass
        # pagination controls present?
        pag = {}
        for sel in ["a[rel=next]", "[class*=pagination] a", "button:has-text('Load more')",
                    "[class*='load-more']", "a:has-text('Next')", "[class*='pager'] a"]:
            try:
                pag[sel] = page.locator(sel).count()
            except Exception:
                pag[sel] = "err"
        browser.close()

    mtgs = extract(html)
    print(f"  resultCount: {rc!r}")
    print(f"  pagination controls present: { {k:v for k,v in pag.items() if v} }")
    plen = {m: cd for m, cd in mtgs.items() if cd[0] == "meeting-of-parliament"}
    other = {m: cd for m, cd in mtgs.items() if cd[0] != "meeting-of-parliament"}
    print(f"  distinct meetings: {len(mtgs)} | PLENARY: {len(plen)} | other: {len(other)}")
    for m, (slug, d) in list(plen.items())[:10]:
        print(f"     PLENARY {slug}-{d} meeting={m}")
    for m, (slug, d) in list(other.items())[:4]:
        print(f"     other   {slug}-{d} meeting={m}")
    return plen


def parse_or_pdf(content):
    import fitz
    doc = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    doc.close()
    spk = re.compile(
        r"^(The [A-Z][\w’'. -]+"
        r"|[A-Z][\w’'.-]+(?: [A-Z][\w’'.-]+)+(?: \([^)]+\))*"
        r"|[A-Z][\w’'.-]+ \([^)]+\)(?: \([^)]+\))*)"
        r":\s*(.*)$")
    contribs, cur_name, cur_text, started = [], "", [], False
    for ln in text.splitlines():
        s = ln.strip()
        if not started:
            if spk.match(s):
                started = True
            else:
                continue
        m = spk.match(s)
        if m and len(m.group(1)) < 70:
            if cur_name and cur_text:
                contribs.append((cur_name, " ".join(cur_text).strip()))
            cur_name, cur_text = m.group(1), ([m.group(2)] if m.group(2) else [])
        elif cur_name and s:
            cur_text.append(s)
    if cur_name and cur_text:
        contribs.append((cur_name, " ".join(cur_text).strip()))
    return contribs


def main():
    print("=" * 74 + "\nA — discovery by URL navigation (custom date range)\n" + "=" * 74)
    try:
        plenary = discover(FROM, TO)
    except Exception as e:
        print(f"discovery failed: {type(e).__name__}: {e}")
        plenary = {}

    target = next(iter(plenary), None) or "20157"
    print("\n" + "=" * 74 + f"\nB — parse PLENARY OR PDF (meeting {target})\n" + "=" * 74)
    s = requests.Session()
    s.headers.update({"User-Agent": _BROWSER_UA})
    r = s.get(MEDIA, params={"meetingId": target}, timeout=60)
    print(f"media API: HTTP {r.status_code} | {len(r.content)} bytes | ct={r.headers.get('Content-Type')}")
    if r.ok and "pdf" in r.headers.get("Content-Type", "").lower():
        contribs = parse_or_pdf(r.content)
        print(f"parsed contributions: {len(contribs)}")
        for name, txt in contribs[:8]:
            print(f"   [{name}] {txt[:130]!r}")

    print("\n" + "=" * 74 + "\nDONE — paste the whole output.\n" + "=" * 74)


if __name__ == "__main__":
    main()
