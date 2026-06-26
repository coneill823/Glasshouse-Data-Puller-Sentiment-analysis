#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 2 — pin the SearchQuestions endpoint.

The #wasearch form has fields (msp/qry/dateSelect/dt.../chkChamber/chkFmq/...) but
a JS action. My bare API guesses 500'd (route exists, errored on missing params).
This retries with the full param set + method-name variants, and captures the
network the page actually calls.

    python diagnose_scottish_questions2.py

Throwaway — removed once the questions source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

REFERER = f"{_WEB}/chamber-and-committees/questions-and-answers"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "X-Requested-With": "XMLHttpRequest",
                     "Referer": REFERER})

FULL = {
    "pageNumber": 1, "msp": "", "qry": "", "qryref": "",
    "chkAnswered": "True", "chkUnAnswered": "True", "chkHolding": "True",
    "chkChamber": "True", "chkFmq": "True", "chkGeneral": "True", "chkPortfolio": "True",
}


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def probe(path, params):
    url = _WEB + path
    try:
        r = sess.get(url, params=params, timeout=30)
    except Exception as e:
        print(f"[{path}] ERROR {type(e).__name__}: {e}")
        return None
    final = r.url.split("?")[0]
    refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+|S\dF-\d+", r.text)))
    cnt = re.search(r'data-count="?\s*(\d+)', r.text)
    err = "500.html" in r.url
    print(f"[{path}] HTTP {r.status_code} | {len(r.text)} bytes | "
          f"{'ERROR(500)' if err else 'OK'} | refs:{len(refs)} {refs[:4]} | count={cnt.group(1) if cnt else '?'}")
    return r if (not err and refs) else None


# ── 1. retry candidate endpoints with FULL params ──
hr("1 — SearchQuestions endpoints with full params")
working = None
for path in [
    "/api/sitecore/QuestionAnswerSearch/SearchQuestions",
    "/api/sitecore/QuestionAnswerSearch/Search",
    "/api/sitecore/QuestionAnswerSearch/SearchWrittenAnswers",
    "/api/sitecore/QuestionAnswerSearch/SearchQuestionAnswers",
    "/api/sitecore/WrittenAnswerSearch/SearchQuestions",
    "/api/sitecore/QuestionsAnswersSearch/SearchQuestions",
]:
    r = probe(path, FULL)
    if r is not None and working is None:
        working = (path, r)

# ── 2. capture what the page actually calls ──
hr("2 — browser network capture on the questions page")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(user_agent=_BROWSER_UA)
        page.set_default_timeout(25000)
        calls = []
        page.on("response", lambda resp: calls.append(resp.url)
                if re.search(r"/api/", resp.url, re.I) and "google" not in resp.url else None)
        page.goto(REFERER, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        try:
            page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay').forEach(e=>e.remove()); }")
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        for u in dict.fromkeys(calls):
            print(f"  api call: {u[:170]}")
        if not calls:
            print("  (no /api/ calls captured — data likely SSR in the page)")
        # are question refs in the SSR page?
        refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+", page.content())))
        print(f"  question refs in page HTML: {len(refs)} {refs[:6]}")
        browser.close()
except Exception as e:
    print(f"  ERROR {type(e).__name__}: {e}")

# ── 3. dump working endpoint structure ──
hr("3 — working endpoint structure")
if working:
    path, r = working
    print(f"endpoint: {path}")
    soup = BeautifulSoup(r.text, "lxml")
    for sel in ["[class*='question']", "[class*='result']", "[class*='qa']", ".vm-list", "article", "li"]:
        els = soup.select(sel)
        if els:
            print(f"  {sel!r}: {len(els)} | first: {els[0].get_text(' ', strip=True)[:80]!r}")
    print("\n--- first 2200 chars ---")
    print(r.text[:2200])
else:
    print("no working endpoint yet — see network capture above for the real URL")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
