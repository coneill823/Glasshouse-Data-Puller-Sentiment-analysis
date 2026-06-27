#!/usr/bin/env python3
"""
TEMPORARY Welsh register recon — what register PDFs does the page actually link?

The register fetch grabs pdf_links[0] (welsh_parliament.py:562), and on the live
site that first link is the "Fifth Senedd, May 2021" archive PDF — whose member
names don't match the current Senedd, so 0 records parse. Scotland already hit
and fixed this (pick the newest-year register PDF, not the first in DOM order).

This dumps every PDF / media link on the register page with its text and any
years, so we can tell whether a *current* register PDF exists to point at (port
Scotland's selector) or whether only the 2021 archive is published (make the
reporting honest instead).

    python diagnose_welsh_register.py

Throwaway — removed once the register source is settled.
"""
import re

from bs4 import BeautifulSoup

from scrapers.welsh_parliament import WelshParliamentScraper, _BASE, _INTEREST_PATHS, _BROWSER_UA

import requests

sess = requests.Session()
sess.headers.update({"User-Agent": _BROWSER_UA,
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})


def hr(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


# ── 1. load the register page (same paths the scraper tries) ──
soup = None
page_url = ""
for path in _INTEREST_PATHS:
    url = _BASE + path
    try:
        r = sess.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        print(f"  {url} -> ERROR {type(e).__name__}: {e}")
        continue
    print(f"  {url} -> HTTP {r.status_code} (final {r.url})")
    if r.ok and "<html" in r.text.lower():
        soup = BeautifulSoup(r.text, "lxml")
        page_url = r.url
        break

if soup is None:
    print("\nCould not load any register page — aborting.")
    raise SystemExit(0)

hr(f"1 — ALL pdf / media links on {page_url}")
links = soup.select("a[href$='.pdf'], a[href*='/media/'], a[href*='.pdf']")
rows = []
seen = set()
for a in links:
    href = a.get("href", "")
    if not href or href in seen:
        continue
    seen.add(href)
    text = a.get_text(" ", strip=True)
    haystack = f"{href} {text}".lower()
    years = sorted({int(y) for y in re.findall(r"20\d{2}", haystack)})
    is_reg = ("register" in haystack and "interest" in haystack)
    rows.append((href, text, years, is_reg))
    print(f"  [{'REG ' if is_reg else '    '}years={years or '-'}] {text[:55]!r}")
    print(f"        href={href}")

# ── 2. what does the current code pick vs. a Scotland-style newest-year pick? ──
hr("2 — current pick vs. newest-year register pick")
all_pdf = [r for r in rows]
print(f"  current code (pdf_links[0]): {all_pdf[0][0] if all_pdf else '(none)'}")

reg = [r for r in rows if r[3]]   # register-of-interests links only
def _newest(rs):
    best, best_year = None, -1
    for href, text, years, _ in rs:
        y = max(years) if years else 0
        if y > best_year:
            best, best_year = href, y
    return best, best_year
nh, ny = _newest(reg or rows)
print(f"  register-tagged links: {len(reg)}")
print(f"  newest-year register pick: year={ny} -> {nh}")

# ── 3. peek at the newest pick's first lines (member names => which Senedd?) ──
hr("3 — first ~25 non-empty lines of the newest-year register PDF")
target = nh or (all_pdf[0][0] if all_pdf else "")
pdf_text = ""
if target:
    full = target if target.startswith("http") else _BASE + target
    try:
        import fitz
        pr = sess.get(full, timeout=90)
        doc = fitz.open(stream=pr.content, filetype="pdf")
        pdf_text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
        doc.close()
        lines = [ln.strip() for ln in pdf_text.splitlines() if ln.strip()]
        print(f"  {full}  ({len(pdf_text)} chars)")
        for ln in lines[:25]:
            print(f"    | {ln[:90]}")
    except ImportError:
        print("  (PyMuPDF not installed — skipping PDF peek)")
    except Exception as e:
        print(f"  PDF peek failed: {type(e).__name__}: {e}")

# ── 4. does any current member name appear in that PDF? ──
hr("4 — current-member-name match test against the picked PDF")
try:
    scraper = WelshParliamentScraper()
    members = scraper.fetch_members()
    names = {m.get("name", "").strip().lower() for m in members if m.get("name")}
    body = pdf_text.lower()
    hits = sorted(n for n in names if n and n in body)
    print(f"  current members: {len(names)} | names found in picked PDF: {len(hits)} {hits[:8]}")
    print("  (0 hits => picked PDF is the wrong/old Senedd; >0 => good candidate)")
except Exception as e:
    print(f"  member-match test failed: {type(e).__name__}: {e}")

print("\n" + "=" * 76 + "\nDONE — paste the whole output.\n" + "=" * 76)
