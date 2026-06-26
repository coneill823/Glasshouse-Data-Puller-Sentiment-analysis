#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 4 — find the search endpoint in JS.

The endpoint isn't in the page forms (action=#wasearch) and an empty Search is a
no-op. The #wasearch handler's API URL must live in the JS bundles. This greps
the page HTML + referenced scripts for the question/answer search endpoint, and
also checks SSR pagination via a page param.

    python diagnose_scottish_questions4.py

Throwaway — removed once the questions source is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

PAGE = f"{_WEB}/chamber-and-committees/questions-and-answers"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def hunt(text, label):
    eps = set()
    for m in re.findall(r"/api/sitecore/[A-Za-z][\w]*/[A-Za-z][\w]*", text):
        eps.add(m)
    # search/question/answer endpoints in any /api path
    for m in re.findall(r"/api/[\w/]*(?:[Ss]earch|[Qq]uestion|[Aa]nswer|[Ww]a)[\w/]*", text):
        eps.add(m)
    # also bare controller/method names near 'wasearch'
    wa = re.findall(r"wasearch[\s\S]{0,200}", text, re.I)
    if eps:
        print(f"  [{label}] endpoints: {sorted(eps)[:20]}")
    if wa:
        # show a short window around the first wasearch mention
        print(f"  [{label}] near 'wasearch': {wa[0][:160]!r}")
    return eps


hr("1 — page HTML")
r = sess.get(PAGE, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
all_eps = hunt(r.text, "html")
scripts = [s.get("src") for s in soup.select("script[src]") if s.get("src")]
print(f"  script srcs: {scripts[:12]}")

hr("2 — JS bundles")
for src in scripts:
    if not src or src.startswith("http") and "parliament.scot" not in src:
        continue  # skip third-party (twitter etc.)
    url = src if src.startswith("http") else _WEB + src
    if not re.search(r"\.js(\?|$)", url):
        continue
    try:
        jr = sess.get(url, timeout=30)
    except Exception as e:
        print(f"  [{url}] ERROR {type(e).__name__}: {e}")
        continue
    if not jr.ok:
        continue
    eps = hunt(jr.text, url.split("/")[-1][:40])
    all_eps |= eps

hr("3 — probe found endpoints")
for ep in sorted(all_eps):
    if "search" not in ep.lower() and "question" not in ep.lower() and "answer" not in ep.lower():
        continue
    url = _WEB + ep if ep.startswith("/") else ep
    try:
        pr = sess.get(url, params={"pageNumber": 1}, timeout=20,
                      headers={"X-Requested-With": "XMLHttpRequest", "Referer": PAGE})
        refs = sorted(set(re.findall(r"S\\dW-\\d+|S\\dO-\\d+", pr.text)))
        err = "500.html" in pr.url or "error" in pr.url.lower()
        print(f"  [{ep}] HTTP {pr.status_code} | {len(pr.text)} bytes | {'ERR' if err else 'OK'} | refs:{len(refs)} {refs[:4]}")
    except Exception as e:
        print(f"  [{ep}] ERROR {type(e).__name__}: {e}")

hr("4 — SSR pagination check (page param)")
for params in [{"pageNumber": 2}, {"page": 2}, {"p": 2}]:
    pr = sess.get(PAGE, params=params, timeout=25)
    refs = sorted(set(re.findall(r"S\\dW-\\d+|S\\dO-\\d+", pr.text)))
    print(f"  {params} -> {len(refs)} refs {refs[:6]}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
