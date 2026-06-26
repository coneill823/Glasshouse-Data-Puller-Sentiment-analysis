#!/usr/bin/env python3
"""
TEMPORARY Scottish-OR recon, round 4 — crack date/plenary discovery.

Content extraction is solved (media API PDF + PyMuPDF). Remaining: list PLENARY
meetings for an arbitrary date range. The default GET ignores the date filter and
shows only recent committees. This dumps the filter dropdowns (committeeSelect
likely holds "Meeting of the Parliament"; dateSelect likely must be set to
activate a custom range) and finds the real search endpoint, then tries a
historical Session-6 plenary search.

    python diagnose_scottish_or_search4.py

Throwaway — deleted once the plenary path is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9",
                     "X-Requested-With": "XMLHttpRequest", "Referer": SEARCH})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def meetings(html):
    out = {}
    for m in re.finditer(r"search-what-was-said-in-parliament/([A-Z]+)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
        out[m.group(3)] = (m.group(1), m.group(2))
    return out


# ── 1. dump the filter dropdowns ──
hr("1 — filter dropdown options (committeeSelect, dateSelect, msp)")
r = sess.get(SEARCH, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
for name in ["committeeSelect", "dateSelect", "msp"]:
    sel = soup.find("select", attrs={"name": name})
    if not sel:
        print(f"\n  <select name={name!r}> not found")
        continue
    opts = [(o.get("value", ""), o.get_text(strip=True)) for o in sel.find_all("option")]
    print(f"\n  {name}: {len(opts)} options")
    for v, t in opts[:30]:
        print(f"     value={v!r}  text={t!r}")

# find a plenary-ish committeeSelect option
plenary_val = None
sel = soup.find("select", attrs={"name": "committeeSelect"})
if sel:
    for o in sel.find_all("option"):
        if re.search(r"meeting of the parliament|plenary", o.get_text(" ", strip=True), re.I):
            plenary_val = o.get("value", "")
            print(f"\n  -> plenary committeeSelect value: {plenary_val!r} ({o.get_text(strip=True)!r})")

# ── 2. find the real search endpoint (inline JS / data attrs) ──
hr("2 — search endpoint hunt")
data_urls = sorted(set(el.get(a) for el in soup.select("[data-ajax-url],[data-url],[data-results-url]")
                       for a in ("data-ajax-url", "data-url", "data-results-url") if el.get(a)))
print(f"data-*-url attrs: {data_urls}")
js_eps = sorted(set(re.findall(r'["\'](/[A-Za-z][\w/.-]*(?:[Ss]earch|[Rr]esults|[Oo]fficial[Rr]eport)[\w/.-]*)["\']', r.text)))
print(f"JS endpoint-ish strings: {js_eps[:20]}")
forms = [(f.get("action"), f.get("method"), f.get("id"), f.get("data-ajax-url")) for f in soup.find_all("form")]
print(f"forms (action,method,id,data-ajax-url): {forms}")


def search(label, params, method="get"):
    try:
        if method == "post":
            rr = sess.post(SEARCH, data=params, timeout=45)
        else:
            rr = sess.get(SEARCH, params=params, timeout=45)
    except Exception as e:
        print(f"[{label}] ERROR {type(e).__name__}: {e}")
        return {}
    mtgs = meetings(rr.text)
    codes = {}
    for c, d in mtgs.values():
        codes[c] = codes.get(c, 0) + 1
    print(f"[{label}] {method.upper()} HTTP {rr.status_code} | {len(rr.text)} chars | "
          f"meetings={len(mtgs)} | codes={codes}")
    for mid, (c, d) in list(mtgs.items())[:6]:
        print(f"      {c}-{d} meeting={mid}")
    return mtgs


# ── 3. try activating the date filter (dateSelect values) for a HISTORICAL plenary range ──
hr("3 — historical plenary search (Session 6: Jan-Mar 2025)")
base = {"qry": "", "showPlenary": "true", "ShowDebates": "true", "ShowFMQs": "true",
        "ShowGeneralQuestions": "true", "ShowPortfolioQuestions": "true",
        "ShowTopicalQuestions": "true", "ShowUrgentQuestions": "true",
        "ResultDisplayType": "Reports",
        "dtDateFrom": "01/01/2025", "dtDateTo": "31/03/2025"}
if plenary_val:
    base["committeeSelect"] = plenary_val
# dateSelect options most likely: a code that means "custom range"
for ds in ["", "0", "1", "custom", "Custom", "5", "6", "range"]:
    search(f"GET dateSelect={ds!r}", {**base, "dateSelect": ds})
# and a POST attempt
search("POST dateSelect=custom", {**base, "dateSelect": "custom"}, method="post")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
