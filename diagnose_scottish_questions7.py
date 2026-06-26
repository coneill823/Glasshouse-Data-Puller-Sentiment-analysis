#!/usr/bin/env python3
"""
TEMPORARY Scottish questions recon, round 7 — pagination + date filter.

Round 6 cracked it: the search is NOT a JSON API. The #wasearch form submits a
plain GET to the page itself with query params, server-side rendered:

    GET .../questions-and-answers?msp=&qry=&qryref=&dateSelect=<GUID>|<from>|<to>

The default range (1999->today) still renders only 10 refs, so the page is
paginated 10-at-a-time. This round, with plain requests:
  1. reads the form's default `dateSelect` value (the GUID + date strings),
  2. runs the search GET and dumps the result count + every pagination control
     (links/hrefs, "next", page numbers) so we learn the page param,
  3. tries &pageNumber=2 / &page=2 / &pageIndex=2 to see if refs change,
  4. runs a CUSTOM narrow date range (GUID + our own dates) to confirm the
     server honours arbitrary from/to so we can bound the fetch by date.

    python diagnose_scottish_questions7.py

Throwaway — removed once the questions source is settled.
"""
import re
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from scrapers.scottish_parliament import _WEB, _BROWSER_UA

PAGE = f"{_WEB}/chamber-and-committees/questions-and-answers"
REF_RE = re.compile(r"S\dW-\d+|S\dO-\d+|S\dF-\d+")
sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def refs_of(html):
    return sorted(set(REF_RE.findall(html)))


# ── 1. read the form's default dateSelect value ──
hr("1 — form fields + default dateSelect")
r = sess.get(PAGE, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
form = soup.find(id="wasearch") or soup.find("form")
date_select = ""
fields = {}
if form:
    for inp in form.find_all(["input", "select", "textarea"]):
        name = inp.get("name")
        if not name:
            continue
        val = inp.get("value", "")
        fields[name] = val
        if name == "dateSelect" and val:
            date_select = val
    print(f"  form id: {form.get('id')}  action: {form.get('action')}")
    print(f"  field names: {sorted(fields)}")
print(f"  default dateSelect (input value): {date_select!r}")
# also try to find any dateSelect carried in JS/hidden anywhere on the page
for m in re.findall(r'dateSelect["\']?\s*[:=]\s*["\']([^"\']+)', r.text)[:3]:
    print(f"  dateSelect in markup: {m!r}")
base_refs = refs_of(r.text)
print(f"  refs on bare page: {len(base_refs)} {base_refs[:6]}")

# Fall back to the range Round 6 captured if the input had no default value.
if not date_select:
    date_select = "acfe09e8571447b6ac663f6362a20f42|Wednesday, May 12, 1999|Friday, Jun 26, 2026"
    print(f"  (using Round-6 captured dateSelect: {date_select!r})")
guid = date_select.split("|", 1)[0]

# ── 2. run the search GET, dump count + pagination controls ──
hr("2 — search GET (full range) + pagination structure")
search_params = {"msp": "", "qry": "", "qryref": "", "dateSelect": date_select}
sr = sess.get(PAGE, params=search_params, timeout=30, headers={"Referer": PAGE})
ssoup = BeautifulSoup(sr.text, "lxml")
srefs = refs_of(sr.text)
print(f"  HTTP {sr.status_code} | {len(sr.text)} bytes | refs: {len(srefs)} {srefs[:10]}")
# total-count hints
for pat in [r'data-count="?\s*(\d+)', r'(\d[\d,]*)\s+results?', r'(\d[\d,]*)\s+questions?',
            r'of\s+(\d[\d,]*)', r'totalResults["\']?\s*[:=]\s*["\']?(\d+)']:
    m = re.search(pat, sr.text, re.I)
    if m:
        print(f"  count hint /{pat}/ -> {m.group(1)}")
# pagination controls: any link/button mentioning page / next
print("  pagination-ish elements:")
seen = set()
for el in ssoup.select(
        "a[href*='page'], a[href*='Page'], [class*='pag'] a, [class*='pag'] button, "
        "a[rel='next'], a[aria-label*='Next'], button[aria-label*='Next'], "
        "[class*='pagination'], nav a"):
    href = el.get("href") or ""
    txt = el.get_text(" ", strip=True)[:30]
    key = (el.name, href, txt)
    if key in seen:
        continue
    seen.add(key)
    cls = " ".join(el.get("class", []))[:40]
    print(f"    <{el.name} class={cls!r} href={href[:90]!r}> {txt!r}")
    if len(seen) >= 25:
        break
if not seen:
    print("    (none found via selectors)")
# raw scan for any pageNumber/pageIndex tokens in the search HTML
toks = sorted(set(re.findall(r"(?:pageNumber|pageIndex|pageNo|page)=\d+", sr.text)))
print(f"  page tokens in HTML: {toks[:12]}")

# ── 3. try paginating the search GET ──
hr("3 — paginate page 2 (param name probe)")
first_set = set(srefs)
for pkey in ["pageNumber", "page", "pageIndex", "pageNo", "p"]:
    pr = sess.get(PAGE, params={**search_params, pkey: 2}, timeout=30, headers={"Referer": PAGE})
    prefs = refs_of(pr.text)
    new = sorted(set(prefs) - first_set)
    same = set(prefs) == first_set
    print(f"  {pkey}=2 -> {len(prefs)} refs | {'SAME as p1' if same else f'NEW: {len(new)} {new[:6]}'}")

# ── 4. custom narrow date range (does the server honour our dates?) ──
hr("4 — custom date range via GUID")
for label, frm, to in [
        ("Jun 2025", "Sunday, Jun 1, 2025", "Monday, Jun 30, 2025"),
        ("2024 full", "Monday, Jan 1, 2024", "Tuesday, Dec 31, 2024")]:
    ds = f"{guid}|{frm}|{to}"
    cr = sess.get(PAGE, params={"msp": "", "qry": "", "qryref": "", "dateSelect": ds},
                  timeout=30, headers={"Referer": PAGE})
    crefs = refs_of(cr.text)
    print(f"  [{label}] dateSelect={ds!r}")
    print(f"           -> {len(crefs)} refs {crefs[:8]}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
