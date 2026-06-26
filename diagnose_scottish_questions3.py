#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 3 — capture the search API on submit.

The questions page is SSR with only 10 questions; the search API only fires when
you submit the #wasearch form / paginate. This drives the form in a browser
(click Search, then a pagination control) and captures the /api/ call + URL, then
dumps a question card's structure for parsing.

    python diagnose_scottish_questions3.py

Throwaway — removed once the questions source is settled.
"""
import re

from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

PAGE = f"{_WEB}/chamber-and-committees/questions-and-answers"


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(user_agent=_BROWSER_UA)
    page.set_default_timeout(25000)
    api_calls = []
    page.on("response", lambda r: api_calls.append((r.status, r.url))
            if re.search(r"/api/", r.url, re.I) and "google" not in r.url else None)

    page.goto(PAGE, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    try:
        page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay').forEach(e=>e.remove()); }")
    except Exception:
        pass

    hr("buttons in #wasearch form")
    btns = page.locator("#wasearch button, #wasearch input[type=submit], #wasearch a.new-button")
    print(f"  candidate buttons: {btns.count()}")

    hr("click Search and capture the API call")
    api_calls.clear()
    clicked = False
    for sel in ["#wasearch button.loadButton", "#wasearch button[type=submit]",
                "#wasearch button:has-text('Search')", "button:has-text('Search')",
                "#wasearch input[type=submit]"]:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=8000)
                print(f"  clicked {sel!r}")
                clicked = True
                break
            except Exception as e:
                print(f"  click {sel!r} failed: {type(e).__name__}: {str(e)[:80]}")
    if not clicked:
        print("  no search button clicked")
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    print("  captured /api/ calls after Search:")
    for status, u in dict.fromkeys(api_calls):
        print(f"    [{status}] {u[:180]}")

    hr("question card structure (rendered)")
    soup = BeautifulSoup(page.content(), "lxml")
    refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+", page.content())))
    print(f"  question refs now: {len(refs)} {refs[:8]}")
    for sel in [".vm-list", "[class*='question']", "[class*='result']", "article", "[class*='qa']"]:
        els = soup.select(sel)
        if els:
            print(f"  {sel!r}: {len(els)} | first: {els[0].get_text(' ', strip=True)[:90]!r}")

    browser.close()

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
