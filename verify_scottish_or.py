#!/usr/bin/env python3
"""
Build/verify Scottish OR browser-driven discovery + PDF parse.

The OR search is client-side only, so discovery needs a real browser. This:
  1. drives the search form with Playwright (select Session 6, plenary-only,
     click Search) and extracts the plenary meeting IDs that render
  2. fetches one meeting's Official Report PDF via the media API and both dumps
     its raw debate-body lines AND runs a first-pass contribution parser

Run it and paste the whole output. It prints diagnostics at each step so if the
form interaction or parsing needs adjusting, the output shows exactly where.

    python verify_scottish_or.py

Throwaway — folded into the scraper once the approach is confirmed.
"""
import re

import requests

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
MEDIA = f"{_WEB}/api/sitecore/CustomMedia/OfficialReport"

# Known committee code prefixes (S6-ish) so we can tell plenary (Meeting of the
# Parliament, usually "MOP"/"MtgPa"…) apart from committees in the results.
KNOWN_COMMITTEE_CODES = {
    "CA", "SPPA", "EHRCJ", "PPC", "PAC", "CJC", "SJHLG", "HCS", "FPA", "EFW",
    "CEEAC", "DPLR", "COVID", "FCC", "NZET", "RAI", "SC", "CTEEA", "ECCLR",
}


def extract(html):
    out = {}
    for m in re.finditer(r"search-what-was-said-in-parliament/([A-Za-z]+)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
        out[m.group(3)] = (m.group(1).upper(), m.group(2))
    return out


def _dismiss_cookies(page):
    """The Civic Cookie Control banner (#ccc) overlays the form and intercepts
    clicks. Accept it if we can find a button, else strip the DOM nodes."""
    for sel in ["#ccc-recommended-settings", "#ccc-notify-accept",
                ".ccc-accept-button", "#ccc-dismiss-button", "button#ccc-close"]:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                print(f"  dismissed cookie banner via {sel}")
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
    try:
        page.evaluate("() => { for (const id of ['ccc','ccc-overlay','cc-panel']) "
                      "{ const e=document.getElementById(id); if (e) e.remove(); } "
                      "document.querySelectorAll('.ccc-overlay,[id^=ccc]').forEach(e=>e.remove()); }")
        print("  removed cookie overlay via JS")
    except Exception as e:
        print(f"  cookie removal failed: {e}")


def drive_search():
    from playwright.sync_api import sync_playwright
    found = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(user_agent=_BROWSER_UA)
        page.set_default_timeout(25000)
        print("loading search page…")
        page.goto(SEARCH, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        _dismiss_cookies(page)

        for name in ["dateSelect", "committeeSelect", "showPlenary", "showCommittee"]:
            cnt = page.locator(f'[name="{name}"]').count()
            print(f"  control [name={name}]: count={cnt}")
        btn_count = page.locator("#orsearch button, #orsearch input[type=submit], #orsearch a.button, #orsearch a.btn").count()
        print(f"  candidate buttons in #orsearch: {btn_count}")

        default = extract(page.content())
        print(f"  default meetings on load: {len(default)} {list(default.values())[:3]}")

        # --- set filters: Session 6, plenary only ---
        try:
            page.select_option('select[name="dateSelect"]', label="Session 6")
            page.evaluate("() => { const s=document.querySelector('select[name=dateSelect]');"
                          " if (s) s.dispatchEvent(new Event('change',{bubbles:true})); }")
            print("  set dateSelect=Session 6")
        except Exception as e:
            print(f"  !! select dateSelect failed: {type(e).__name__}: {e}")
        try:
            box = page.locator('input[name="showCommittee"]')
            if box.count() and box.is_checked():
                box.uncheck(timeout=8000)
                print("  unchecked showCommittee")
        except Exception as e:
            print(f"  !! uncheck showCommittee failed: {type(e).__name__}: {e}")

        # --- click Search (try several selectors, fail fast) ---
        clicked = False
        for sel in ['#orsearch button.loadButton', '#orsearch button[type="submit"]',
                    '#orsearch input[type="submit"]', 'button.new-button:has-text("Search")',
                    'button:has-text("Search")']:
            loc = page.locator(sel)
            if loc.count():
                try:
                    loc.first.click(timeout=8000)
                    print(f"  clicked search via {sel!r}")
                    clicked = True
                    break
                except Exception as e:
                    print(f"  click {sel!r} failed: {type(e).__name__}: {str(e)[:120]}")
        if not clicked:
            print("  !! no search button clicked — #orsearch inner HTML follows:")
            try:
                print(page.locator("#orsearch").inner_html()[:1800])
            except Exception:
                pass

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3500)

        found = extract(page.content())
        codes = {}
        for c, d in found.values():
            codes[c] = codes.get(c, 0) + 1
        print(f"\n  AFTER search: {len(found)} meetings | codes={codes}")
        for mid, (c, d) in list(found.items())[:12]:
            tag = "PLENARY?" if c not in KNOWN_COMMITTEE_CODES else "committee"
            print(f"     {c}-{d} meeting={mid}  [{tag}]")
        browser.close()
    return found


def parse_or_pdf(content):
    """First-pass: split the OR PDF into (speaker, text) contributions."""
    import fitz
    doc = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    doc.close()
    lines = [ln.rstrip() for ln in text.splitlines()]
    # A Scottish OR speaker attribution is one of:
    #   "The Presiding Officer:" / "The Convener:"      (office, starts with "The")
    #   "Claire Baker:" / "Name Name (Region) (Party):" (two+ name words)
    #   "Surname (Constituency) (Party):"               (single name BUT with parens)
    # A bare single word ("Women:") is rejected to avoid title/heading false matches.
    spk = re.compile(
        r"^(The [A-Z][\w’'. -]+"
        r"|[A-Z][\w’'.-]+(?: [A-Z][\w’'.-]+)+(?: \([^)]+\))*"
        r"|[A-Z][\w’'.-]+ \([^)]+\)(?: \([^)]+\))*)"
        r":\s*(.*)$")
    contribs = []
    cur_name, cur_text = "", []
    started = False
    for ln in lines:
        s = ln.strip()
        if not started:
            # skip front matter until the first real speaker
            if spk.match(s):
                started = True
            else:
                continue
        m = spk.match(s)
        if m and len(m.group(1)) < 70:
            if cur_name and cur_text:
                contribs.append((cur_name, " ".join(cur_text).strip()))
            cur_name = m.group(1)
            cur_text = [m.group(2)] if m.group(2) else []
        elif cur_name:
            if s:
                cur_text.append(s)
    if cur_name and cur_text:
        contribs.append((cur_name, " ".join(cur_text).strip()))
    return lines, contribs


def main():
    print("=" * 74 + "\nPART 1 — browser-driven plenary discovery (Session 6)\n" + "=" * 74)
    try:
        meetings = drive_search()
    except Exception as e:
        print(f"browser drive failed: {type(e).__name__}: {e}")
        meetings = {}

    plenary = {mid: cd for mid, cd in meetings.items() if cd[0] not in KNOWN_COMMITTEE_CODES}
    print(f"\nlikely-plenary meetings: {len(plenary)} | sample: {list(plenary.items())[:5]}")

    target = next(iter(plenary), None) or next(iter(meetings), None) or "20187"
    print("\n" + "=" * 74 + f"\nPART 2 — fetch + parse OR PDF for meeting {target}\n" + "=" * 74)
    s = requests.Session()
    s.headers.update({"User-Agent": _BROWSER_UA})
    r = s.get(MEDIA, params={"meetingId": target}, timeout=60)
    print(f"media API: HTTP {r.status_code} | {len(r.content)} bytes | ct={r.headers.get('Content-Type')}")
    if r.ok and "pdf" in r.headers.get("Content-Type", "").lower():
        lines, contribs = parse_or_pdf(r.content)
        print(f"\nraw text lines: {len(lines)} | parsed contributions: {len(contribs)}")
        print("\n--- raw lines 40–80 (to see the debate-body format) ---")
        for ln in lines[40:80]:
            if ln.strip():
                print(f"   {ln[:95]!r}")
        print("\n--- first 5 parsed contributions ---")
        for name, txt in contribs[:5]:
            print(f"   [{name}] {txt[:140]!r}")

    print("\n" + "=" * 74 + "\nDONE — paste the whole output.\n" + "=" * 74)


if __name__ == "__main__":
    main()
