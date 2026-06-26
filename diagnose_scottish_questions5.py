#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 5 — the data-ajax-url endpoint.

The page uses jquery.unobtrusive-ajax, so the search endpoint is in a
data-ajax-url attribute on the search form (not the JS, not the action). This
dumps every form's full attributes + all data-ajax-* attributes, then probes the
endpoint with the form params.

    python diagnose_scottish_questions5.py

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


r = sess.get(PAGE, timeout=30)
soup = BeautifulSoup(r.text, "lxml")

hr("1 — all forms: full attributes")
endpoints = set()
for f in soup.find_all("form"):
    attrs = {k: v for k, v in f.attrs.items() if k != "class"}
    print(f"  form attrs: {attrs}")
    for k, v in attrs.items():
        if "ajax" in k and isinstance(v, str) and "/" in v:
            endpoints.add(v)
    fields = [(i.get("name"), i.get("value", "")[:20]) for i in f.find_all(["input", "select"]) if i.get("name")]
    print(f"    fields: {fields[:24]}")

hr("2 — any data-ajax-* attributes on the page")
for el in soup.select("[data-ajax-url], [data-ajax], [data-url], [data-results-url]"):
    da = {k: v for k, v in el.attrs.items() if k.startswith("data-")}
    print(f"  <{el.name}> {da}")
    for k, v in da.items():
        if "url" in k and isinstance(v, str) and "/" in v:
            endpoints.add(v)

# regex fallback straight on the raw HTML
for m in re.findall(r'data-ajax-url="([^"]+)"', r.text):
    endpoints.add(m)

hr("3 — probe the endpoint(s)")
FULL = {"pageNumber": 1, "msp": "", "qry": "", "qryref": "",
        "chkAnswered": "True", "chkUnAnswered": "True", "chkHolding": "True",
        "chkChamber": "True", "chkFmq": "True", "chkGeneral": "True", "chkPortfolio": "True"}
print(f"endpoints found: {sorted(endpoints)}")
for ep in sorted(endpoints):
    url = ep if ep.startswith("http") else _WEB + ep
    for label, params in [("bare", {"pageNumber": 1}), ("full", FULL)]:
        try:
            pr = sess.get(url, params=params, timeout=25,
                          headers={"X-Requested-With": "XMLHttpRequest", "Referer": PAGE})
            refs = sorted(set(re.findall(r"S\dW-\d+|S\dO-\d+", pr.text)))
            cnt = re.search(r'data-count="?\s*(\d+)', pr.text)
            err = "500.html" in pr.url or "error" in pr.url.lower()
            print(f"  [{ep} | {label}] HTTP {pr.status_code} | {len(pr.text)} bytes | "
                  f"{'ERR' if err else 'OK'} | refs:{len(refs)} {refs[:4]} | count={cnt.group(1) if cnt else '?'}")
            if refs and not err and label == "bare":
                print("    --- first 1500 chars ---")
                print(pr.text[:1500])
        except Exception as e:
            print(f"  [{ep} | {label}] ERROR {type(e).__name__}: {e}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
