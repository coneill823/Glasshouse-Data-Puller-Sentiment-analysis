#!/usr/bin/env python3
"""
TEMPORARY Scottish-OR search recon, round 1 — dissect the search form.

The Official Report now lives behind /search-what-was-said-in-parliament (an
ASP.NET unobtrusive-AJAX form). To scrape it we need: the form's endpoint +
method, its fields (esp. any date-range / type filters), and how each result
links to the actual transcript. This dumps all that, then runs a sample search
and inspects the result structure.

    python diagnose_scottish_or_search.py

Throwaway — deleted once the plenary path is settled.
"""
import re

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def get(url, params=None, timeout=30):
    try:
        r = sess.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    return r, f"HTTP {r.status_code} | {r.headers.get('Content-Type','').split(';')[0]} | {len(r.content)} bytes | {r.url}"


# ── 1. Dump every form + AJAX widget on the search page ──
hr("1 — search form(s), fields, and AJAX endpoints")
r, summ = get(SEARCH)
print(summ)
soup = BeautifulSoup(r.text, "lxml") if r is not None and r.ok else None
forms = soup.find_all("form") if soup else []
print(f"\nforms on page: {len(forms)}")
search_form = None
for i, f in enumerate(forms):
    ajax = {k: f.get(k) for k in f.attrs if k.startswith("data-ajax")}
    fields = []
    for inp in f.find_all(["input", "select", "textarea"]):
        fields.append((inp.name, inp.get("name"), inp.get("type") or "", (inp.get("value") or "")[:30]))
    print(f"\n  form#{i}: action={f.get('action')!r} method={f.get('method')!r}")
    if ajax:
        print(f"    AJAX attrs: {ajax}")
    print(f"    fields: {fields}")
    if any("search" in (fn[1] or "").lower() or fn[1] in ("q", "query", "keyword", "term")
           for fn in fields) or "search" in (f.get("action") or "").lower():
        search_form = f

# Elements anywhere carrying a data-ajax-url (the result endpoint)
if soup:
    ajax_urls = sorted(set(el.get("data-ajax-url") for el in soup.select("[data-ajax-url]") if el.get("data-ajax-url")))
    print(f"\ndata-ajax-url endpoints on page: {ajax_urls}")
    # result container hints
    containers = sorted(set(c for el in soup.select("[id*='result'],[class*='result']")
                            for c in ([el.get('id')] + (el.get('class') or [])) if c))
    print(f"result-ish container ids/classes: {containers[:20]}")


# ── 2. Run a sample search and inspect results ──
def run_search(label, params, endpoint=None, method="get"):
    url = endpoint or SEARCH
    print(f"\n[{label}] {method.upper()} {url}\n   params={params}")
    try:
        if method == "post":
            r = sess.post(url, data=params, timeout=40,
                          headers={"X-Requested-With": "XMLHttpRequest", "Referer": SEARCH})
        else:
            r = sess.get(url, params=params, timeout=40,
                         headers={"X-Requested-With": "XMLHttpRequest", "Referer": SEARCH})
    except Exception as e:
        print(f"   ERROR {type(e).__name__}: {e}")
        return
    rs = BeautifulSoup(r.text, "lxml")
    # links that look like a transcript / report / dated OR
    report_links = sorted(set(
        a.get("href", "") for a in rs.select("a[href]")
        if re.search(r"official-report|meetingid=|/report/|what-was-said.*/official-report-\d", a.get("href", ""), re.I)
    ))
    # result item count via common patterns
    items = rs.select("[class*='result'], li.search-result, article, .search-results li")
    print(f"   HTTP {r.status_code} | {len(r.text)} chars | result-ish items: {len(items)} | "
          f"report links: {len(report_links)}")
    for h in report_links[:8]:
        print(f"      link: {h}")
    # show one result item's text
    if items:
        print(f"   sample item text: {items[0].get_text(' ', strip=True)[:200]!r}")


hr("2 — sample searches")
# Build a base payload from the discovered form fields, then vary the search term.
base = {}
if search_form is not None:
    for inp in search_form.find_all(["input", "select", "textarea"]):
        n = inp.get("name")
        if n:
            base[n] = inp.get("value") or ""
    action = search_form.get("action") or SEARCH
    method = (search_form.get("method") or "get").lower()
    print(f"using discovered form: action={action} method={method} base_fields={list(base)}")
else:
    action, method = SEARCH, "get"
    print("no obvious search form found; trying generic param names")

# Try setting each plausible search-term field name to a common word
for term_field in ["SearchTerm", "searchTerm", "search", "q", "query", "keyword", "Keywords", "term"]:
    if search_form is not None and term_field not in base:
        continue
    p = dict(base)
    p[term_field] = "health"
    run_search(f"term={term_field}=health", p, endpoint=(action if search_form is not None else SEARCH),
               method=(method if search_form is not None else "get"))
    break
else:
    # no field matched; just try q= on the page URL
    run_search("q=health (fallback)", {"q": "health"})

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
