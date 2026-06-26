#!/usr/bin/env python3
"""
TEMPORARY Welsh-votes reconnaissance, round 4 (final — the meeting index).

The Votes-export PARSER is solved (round 3 gave the full schema). The only open
question is DISCOVERY: how to enumerate plenary meeting IDs without scanning
thousands. The /XMLExport page is a 185KB HTML form — almost certainly a meeting
picker listing every meeting's id + date + type. This dissects it.

    python diagnose_welsh_votes4.py

Throwaway — deleted once the votes fix lands.
"""
import json
import re

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RECORD = "https://record.senedd.wales"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def get(url, params=None, timeout=25):
    try:
        r = S.get(url, params=params, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {e}"
    ct = r.headers.get("Content-Type", "").split(";")[0]
    return r, f"HTTP {r.status_code} | {ct} | {len(r.content)} bytes | final={r.url}"


hr("XMLExport form page dissection")
r, summ = get(f"{RECORD}/XMLExport", timeout=30)
print(summ)
if r is not None and r.ok:
    soup = BeautifulSoup(r.text, "lxml")

    # 1. <select> / <option> meeting pickers
    selects = soup.find_all("select")
    print(f"\n<select> elements: {len(selects)}")
    for sel in selects:
        opts = sel.find_all("option")
        name = sel.get("id") or sel.get("name") or "?"
        print(f"\n  select id/name={name!r}  options={len(opts)}")
        for o in opts[:6]:
            print(f"    value={o.get('value')!r}  text={o.get_text(strip=True)[:70]!r}")
        if len(opts) > 6:
            print(f"    ... ({len(opts)-6} more)")

    # 2. Any <option value="<digits>"> anywhere (in case select parsing missed them)
    num_opts = re.findall(r'<option[^>]*value="(\d{3,6})"[^>]*>([^<]{0,80})', r.text)
    if num_opts:
        print(f"\nNumeric <option> values found: {len(num_opts)}")
        print(f"  id range: {min(int(v) for v,_ in num_opts)}..{max(int(v) for v,_ in num_opts)}")
        print("  samples:")
        for v, t in num_opts[:8]:
            print(f"    {v} -> {t.strip()!r}")
        for v, t in num_opts[-4:]:
            print(f"    {v} -> {t.strip()!r}")

    # 3. JS/JSON arrays of meetings embedded in <script>
    print("\nScanning <script> blocks for meeting data...")
    for sc in soup.find_all("script"):
        txt = sc.string or sc.get_text() or ""
        if re.search(r"meeting", txt, re.I) and re.search(r"\d{3,6}", txt):
            # find JSON-ish array/object assignments mentioning meeting/date
            for m in re.finditer(r"(\[[^\[\]]{0,4000}?\])", txt):
                blob = m.group(1)
                if re.search(r"\d{3,6}", blob) and re.search(r"date|meeting|plenary", blob, re.I):
                    print(f"  candidate JS array (first 500 chars): {blob[:500]!r}")
                    break
            ids = re.findall(r'"?[Mm]eeting[_]?[Ii][dd]"?\s*[:=]\s*"?(\d{3,6})', txt)
            if ids:
                print(f"  meeting ids in script: {sorted(set(ids), key=int)[:10]} "
                      f"... total {len(set(ids))}")

    # 4. Forms + their fields (maybe the list is fetched by POSTing this form)
    print("\nForms on page:")
    for f in soup.find_all("form"):
        action = f.get("action", "")
        inputs = [(i.get("name"), i.get("type") or i.name) for i in f.find_all(["input", "select"])][:12]
        print(f"  action={action!r}  fields={inputs}")

    # 5. Any AJAX endpoints referenced
    endpoints = sorted(set(re.findall(r'["\'](/[A-Za-z][\w/.-]*(?:[Mm]eeting|[Ll]ist|[Pp]lenary)[\w/.-]*)["\']', r.text)))
    if endpoints:
        print(f"\nReferenced meeting/list endpoints: {endpoints[:15]}")

print("\n" + "=" * 78 + "\nDONE — paste this entire output back.\n" + "=" * 78)
