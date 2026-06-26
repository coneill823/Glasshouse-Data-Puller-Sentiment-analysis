#!/usr/bin/env python3
"""
TEMPORARY Scottish votes deep-dive, round 1 — find the SPA's data API.

The votes-and-motions section is a client-side SPA. This loads it in a headless
browser and captures the XHR/fetch requests it makes, which should reveal the
underlying data API (as network-capture revealed the OR media API). It also
dumps how divisions/motions are linked so we can find a real division page.

    python diagnose_scottish_votes2.py

Throwaway — removed once the votes source is settled.
"""
import re

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

LANDING = f"{_WEB}/chamber-and-committees/votes-and-motions"
MOTION = f"{_WEB}/chamber-and-committees/votes-and-motions/S7M-00511"


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def dismiss_cookies(page):
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


from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(user_agent=_BROWSER_UA)
    page.set_default_timeout(25000)

    calls = []
    INTEREST = re.compile(r"/api/|sitecore|vote|division|motion|\.json|graphql|/data/", re.I)

    def on_response(resp):
        u = resp.url
        if INTEREST.search(u) and "official-report/search" not in u:
            ct = resp.headers.get("content-type", "")
            calls.append((resp.status, ct.split(";")[0], u))

    page.on("response", on_response)

    for label, url in [("LANDING", LANDING), ("MOTION S7M-00511", MOTION)]:
        hr(f"{label} — {url}")
        calls.clear()
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            dismiss_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"  load error: {type(e).__name__}: {e}")
            continue

        # captured data-ish responses
        seen = set()
        print("  data-ish network responses:")
        for status, ct, u in calls:
            key = u.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            print(f"    [{status} {ct}] {u[:160]}")
        if not calls:
            print("    (none captured)")

        # how are divisions/motions linked on the page?
        html = page.content()
        motion_links = sorted(set(re.findall(r"/votes-and-motions/([A-Za-z0-9-]+)", html)))[:12]
        print(f"  votes-and-motions slugs on page: {motion_links}")
        # visible vote/division words + any voter-list-ish containers
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for sel in [".ayes", ".noes", "[class*='division']", "[class*='vote']",
                    "[class*='for']", "[class*='against']", "table"]:
            n = len(soup.select(sel))
            if n:
                print(f"    selector {sel!r}: {n}")
        txt = soup.get_text(' ', strip=True)
        vi = txt.lower().find("voted")
        if vi == -1:
            vi = txt.lower().find("for")
        print(f"    visible text ~{len(txt)} chars; sample @vote-word: {txt[max(0,vi-40):vi+160]!r}")

    browser.close()

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
