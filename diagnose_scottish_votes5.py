#!/usr/bin/env python3
"""
TEMPORARY Scottish votes deep-dive, round 4 — find the per-member roll-call.

SearchVotes gives clean division summaries (motion, date, "93 for, 10 against,
15 abstained, 10 did not vote", Agreed). This hunts the per-member roll-call for
a known division (S7M-00454): is it on the motion page (SSR or rendered), or
behind another API call?

    python diagnose_scottish_votes5.py

Throwaway — removed once the votes source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

MOTION = f"{_WEB}/chamber-and-committees/votes-and-motions/S7M-00454"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def member_struct(soup, label):
    print(f"  [{label}] per-member structure:")
    found = False
    for sel in ["[class*='vote_member']", "[class*='vote-member']", "[class*='member-vote']",
                "[class*='voter']", ".vote__member", "[class*='for'] li", "[class*='against'] li",
                "[class*='abstain'] li", "table tr td", "[class*='msp']"]:
        els = soup.select(sel)
        if els:
            found = True
            print(f"     {sel!r}: {len(els)} | first: {els[0].get_text(' ', strip=True)[:60]!r}")
    if not found:
        print("     (no per-member structure found)")
    txt = soup.get_text(" ", strip=True)
    for kw in ["How MSPs voted", "Voted for", "Voted against", "Abstained", "did not vote"]:
        i = txt.find(kw)
        if i != -1:
            print(f"     …'{kw}': {txt[i:i+140]!r}")


# ── 1. motion page, plain HTTP ──
hr("1 — motion page S7M-00454 (plain HTTP)")
try:
    r = sess.get(MOTION, timeout=30)
    print(f"  HTTP {r.status_code} | {len(r.content)} bytes")
    soup = BeautifulSoup(r.text, "lxml")
    print(f"  visible text ~{len(soup.get_text(' ', strip=True))}")
    member_struct(soup, "plain")
except Exception as e:
    print(f"  ERROR {type(e).__name__}: {e}")

# ── 2. motion page rendered + network capture (find a roll-call API) ──
hr("2 — motion page rendered + network capture")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(user_agent=_BROWSER_UA)
        page.set_default_timeout(25000)
        calls = []
        page.on("response", lambda resp: calls.append((resp.status, resp.url))
                if re.search(r"/api/|vote|division|sitecore", resp.url, re.I)
                and "google" not in resp.url else None)
        page.goto(MOTION, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        try:
            page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay').forEach(e=>e.remove()); }")
        except Exception:
            pass
        # try expanding a "how MSPs voted" toggle if present
        for sel in ["a:has-text('How MSPs voted')", "button:has-text('How MSPs voted')",
                    "a:has-text('voted')", "[class*='toggle']"]:
            loc = page.locator(sel)
            try:
                if loc.count():
                    loc.first.click(timeout=4000)
                    page.wait_for_timeout(1500)
                    print(f"  clicked {sel!r}")
                    break
            except Exception:
                pass
        page.wait_for_timeout(2000)
        print("  network (api/vote/division/sitecore):")
        for status, u in dict.fromkeys(calls):
            print(f"    [{status}] {u[:150]}")
        rendered = BeautifulSoup(page.content(), "lxml")
        member_struct(rendered, "rendered")
        browser.close()
except Exception as e:
    print(f"  ERROR {type(e).__name__}: {e}")

# ── 3. roll-call API guesses ──
hr("3 — roll-call API guesses (motionRef=S7M-00454)")
API = f"{_WEB}/api/sitecore/VotesMotionsSearch"
sess.headers.update({"X-Requested-With": "XMLHttpRequest",
                     "Referer": f"{_WEB}/chamber-and-committees/votes-and-motions"})
for method, params in [
    ("GetVoteDetail", {"motionRef": "S7M-00454"}),
    ("GetVote", {"motionRef": "S7M-00454"}),
    ("VoteDetail", {"motionRef": "S7M-00454"}),
    ("GetVotes", {"motionRef": "S7M-00454"}),
    ("SearchVotes", {"qryMotionRef": "S7M-00454", "pageNumber": 1}),
]:
    try:
        r = sess.get(f"{API}/{method}", params=params, timeout=20)
        names = len(re.findall(r"/msps/current-and-previous-msps/", r.text))
        print(f"  [{method} {params}] HTTP {r.status_code} | {len(r.text)} bytes | msp-links: {names}")
    except Exception as e:
        print(f"  [{method}] ERROR {type(e).__name__}: {e}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
