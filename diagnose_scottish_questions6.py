#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 6 — capture ALL requests on search.

Endpoint isn't in forms/JS/data-attrs. The search may post to a non-/api/ URL.
This drives the #wasearch form (clicks each candidate Search button) and captures
EVERY non-asset request, revealing the real search URL + method.

    python diagnose_scottish_questions6.py

Throwaway — removed once the questions source is settled.
"""
import re

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

PAGE = f"{_WEB}/chamber-and-committees/questions-and-answers"
ASSET = re.compile(r"\.(js|css|png|jpe?g|svg|woff2?|gif|ico|map)(\?|$)|google|twitter|unpkg|cdnjs", re.I)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(user_agent=_BROWSER_UA)
    page.set_default_timeout(25000)
    reqs = []
    page.on("request", lambda r: reqs.append((r.method, r.url))
            if not ASSET.search(r.url) else None)

    page.goto(PAGE, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    try:
        page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay').forEach(e=>e.remove()); }")
    except Exception:
        pass

    print("buttons in #wasearch:", page.locator("#wasearch button, #wasearch input[type=submit]").count())
    # try setting a narrow recent date range first (in case empty search is a no-op)
    for fld, val in [("dtDateFrom", "01/06/2025"), ("dtDateTo", "30/06/2025")]:
        try:
            loc = page.locator(f"#wasearch [name='{fld}']")
            if loc.count():
                loc.first.fill(val)
        except Exception as e:
            print(f"  fill {fld} failed: {type(e).__name__}")

    reqs.clear()
    clicked = ""
    for sel in ["#wasearch button.loadButton", "#wasearch button[type=submit]",
                "#wasearch button:has-text('Search')", "#wasearch input[type=submit]",
                "#wasearch button"]:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=8000)
                clicked = sel
                break
            except Exception as e:
                print(f"  click {sel!r} failed: {type(e).__name__}: {str(e)[:70]}")
    print(f"clicked: {clicked!r}")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3500)

    print("\nnon-asset requests after Search:")
    for method, u in dict.fromkeys(reqs):
        print(f"  {method} {u[:180]}")

    refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+", page.content())))
    print(f"\nquestion refs now: {len(refs)} {refs[:10]}")
    print(f"current url: {page.url}")
    browser.close()

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
