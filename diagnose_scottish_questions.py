#!/usr/bin/env python3
"""
TEMPORARY reconnaissance for the Scottish questions fix.

fetch_questions scrapes a sparse SPA listing and only gets ~10. Like votes
(which had a SearchVotes API in the page forms), the questions-and-answers page
should expose a SearchQuestions-style API. This dumps the landing-page forms to
find it, probes it, and dumps the result structure.

    python diagnose_scottish_questions.py

Throwaway — removed once the questions source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def get(url, params=None, timeout=25):
    try:
        r = sess.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    return r, f"HTTP {r.status_code} | {len(r.content)} bytes | final={r.url}"


# ── 1. landing pages: find the search API in the forms ──
hr("1 — questions landing-page forms (find the search API)")
api_endpoints = set()
for path in ["/chamber-and-committees/questions-and-answers",
             "/chamber-and-committees/written-questions-and-answers",
             "/chamber-and-committees/questions"]:
    r, summ = get(_WEB + path)
    print(f"\n[{path}] {summ}")
    if r is None or not r.ok:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    for f in soup.find_all("form"):
        action = f.get("action", "")
        fields = [i.get("name") for i in f.find_all(["input", "select"]) if i.get("name")]
        if "/api/" in action or "search" in action.lower():
            print(f"  form action={action!r}\n    fields={fields[:20]}")
            if "/api/" in action:
                api_endpoints.add(action if action.startswith("http") else _WEB + action)
    # also any /api/sitecore reference in the HTML
    for m in set(re.findall(r"/api/sitecore/[A-Za-z]+/[A-Za-z]+", r.text)):
        print(f"  /api/sitecore ref in HTML: {m}")
        api_endpoints.add(_WEB + m.split("?")[0])

# ── 2. probe the question-search API ──
hr("2 — probe SearchQuestions-style endpoints")
candidates = sorted(api_endpoints) + [
    f"{_WEB}/api/sitecore/QuestionAnswerSearch/SearchQuestions",
    f"{_WEB}/api/sitecore/QuestionsSearch/SearchQuestions",
    f"{_WEB}/api/sitecore/QuestionAnswerSearch/Search",
    f"{_WEB}/api/sitecore/QuestionSearch/SearchQuestions",
]
working = None
for url in dict.fromkeys(candidates):
    r, summ = get(url, params={"pageNumber": 1}, timeout=25)
    refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+", r.text))) if (r is not None and r.ok) else []
    cnt = re.search(r'data-count="?(\d+)', r.text) if (r is not None and r.ok) else None
    print(f"[{url}] {summ} | question refs: {len(refs)} {refs[:4]} | count={cnt.group(1) if cnt else '?'}")
    if refs and working is None:
        working = url

# ── 3. dump the working endpoint's structure ──
hr("3 — result structure")
if working:
    r, _ = get(working, params={"pageNumber": 1})
    soup = BeautifulSoup(r.text, "lxml")
    for sel in ["[class*='question']", "[class*='result']", "[class*='qa']", "article", "li", ".vm-list"]:
        els = soup.select(sel)
        if els:
            print(f"  {sel!r}: {len(els)} | first: {els[0].get_text(' ', strip=True)[:80]!r}")
    print("\n--- first 2000 chars ---")
    print(r.text[:2000])
else:
    print("no working SearchQuestions endpoint found in probes")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
