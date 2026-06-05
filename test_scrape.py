#!/usr/bin/env python3
"""
Smoke-test all four parliamentary scrapers.

Makes a handful of targeted API calls per data-type per parliament —
enough to verify endpoints, response shapes, and field extraction without
running the full overnight pull.  Typical run time: 5–10 minutes.

Key differences from the full run
----------------------------------
  - Members          : first page only for UK (20 MPs); full list for others
  - Register         : first 5 members only for UK
  - Questions        : last 30 days only (single date chunk)
  - Plenary          : last 30 days; NI capped at first 3 reports; Wales at 5 sessions
  - Votes            : last 30 days; UK/Wales capped at 5–10 divisions

Usage
-----
  python test_scrape.py                       # all parliaments
  python test_scrape.py --parliament uk       # ni / uk / scotland / wales
  python test_scrape.py --verbose             # print first record per test
  python test_scrape.py --save                # write samples to test_data/
"""
import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Silence scraper INFO/DEBUG — we control all output here
logging.basicConfig(level=logging.WARNING, format="%(levelname)-8s %(message)s")

from config import PARLIAMENTS
from scrapers.ni_assembly import NIAssemblyScraper, _first_list as _ni_list
from scrapers.uk_parliament import UKParliamentScraper
from scrapers.scottish_parliament import ScottishParliamentScraper
from scrapers.welsh_parliament import (
    WelshParliamentScraper,
    _RECORD as _WALES_RECORD,
    _DIVISION_PATHS as _WALES_DIV_PATHS,
    _PLENARY_PATHS as _WALES_PLENARY_PATHS,
    _SENEDD_PLENARY_PATHS as _WALES_SENEDD_PLENARY_PATHS,
    _BASE as _WALES_BASE,
)

_NI_BASE = PARLIAMENTS["ni_assembly"]["api_base"]
_UK_CFG  = PARLIAMENTS["uk_parliament"]

RECENT_30 = (date.today() - timedelta(days=30)).isoformat()
RECENT_90 = (date.today() - timedelta(days=90)).isoformat()

# ── Colour helpers ────────────────────────────────────────────────────────────

_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
_RED = "\033[31m" if _USE_COLOR else ""
_YLW = "\033[33m" if _USE_COLOR else ""
_GRN = "\033[32m" if _USE_COLOR else ""
_BLD = "\033[1m"  if _USE_COLOR else ""
_RST = "\033[0m"  if _USE_COLOR else ""


def _col(status: str) -> str:
    return {"PASS": f"{_GRN}PASS{_RST}", "WARN": f"{_YLW}WARN{_RST}",
            "FAIL": f"{_RED}FAIL{_RST}"}.get(status, status)


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class Result:
    parliament: str
    data_type: str
    status: str = "FAIL"
    count: int = 0
    elapsed: float = 0.0
    issues: List[str] = field(default_factory=list)
    sample: Optional[Dict] = None
    note: str = ""


def _assess(records: List[Dict], soft: bool = False) -> Tuple[str, List[str]]:
    """Check field completeness for _make_record() output; soft=True returns WARN instead of FAIL."""
    if not records:
        return ("WARN" if soft else "FAIL"), ["no records returned"]
    n = len(records)
    issues = []
    empty_text = sum(1 for r in records if not str(r.get("text", "")).strip())
    empty_date = sum(1 for r in records if not str(r.get("date", "")).strip())
    empty_name = sum(1 for r in records if not r.get("member", {}).get("name", "").strip())
    if empty_text == n:
        issues.append("ALL text fields empty")
    elif empty_text > n // 2:
        issues.append(f"{empty_text}/{n} text fields empty")
    if empty_date > n // 2:
        issues.append(f"{empty_date}/{n} date fields empty")
    if empty_name > n // 2:
        issues.append(f"{empty_name}/{n} member name fields empty")
    return ("WARN" if issues else "PASS"), issues


def _assess_members(records: List[Dict]) -> Tuple[str, List[str]]:
    """Check completeness of raw member dicts (name/party/id fields, not _make_record shape)."""
    if not records:
        return "FAIL", ["no members returned"]
    n = len(records)
    issues = []
    empty_name  = sum(1 for r in records if not str(r.get("name", "")).strip())
    empty_party = sum(1 for r in records if not str(r.get("party", "")).strip())
    empty_id    = sum(1 for r in records if not str(r.get("id", "")).strip())
    if empty_name  > n // 2: issues.append(f"{empty_name}/{n} name fields empty")
    if empty_party == n:     issues.append("ALL party fields empty")
    if empty_id    == n:     issues.append("ALL id fields empty")
    return ("WARN" if issues else "PASS"), issues


# ── NI Assembly ───────────────────────────────────────────────────────────────

def _ni_plenary_sample(s: NIAssemblyScraper) -> Tuple[List[Dict], str]:
    """Fetch report list then first 3 report components — avoids pulling all 644 reports."""
    candidates = list(dict.fromkeys(
        ["GetAllHansardReports_JSON", "GetHansardReports_JSON", "GetAllPlenaryReports_JSON"]
        + [m for m in s._discover_asmx_methods("hansard")
           if "report" in m.lower() and m.endswith("_JSON")]
    ))
    all_reports = []
    used_method = ""
    for method in candidates:
        rows = _ni_list(s._asmx("hansard", method))
        if rows:
            all_reports, used_method = rows, method
            break
    if not all_reports:
        return [], f"report list returned 0 (tried: {', '.join(candidates[:3])})"

    comp_url = f"{_NI_BASE}/hansard.asmx/GetHansardComponentsByReportId_JSON"
    records = []
    for report in all_reports[:3]:
        rep_id = str(report.get("ReportDocId",
                    report.get("HansardReportId",
                    report.get("ReportId",
                    report.get("reportId",
                    report.get("Id", ""))))))
        rep_date = report.get("PlenaryDate", report.get("Date", ""))
        if not rep_id:
            continue
        comp_resp = (
            s._get(comp_url, params={"reportId": rep_id})
            or s._get(comp_url, params={"ReportDocId": rep_id})
            or s._get(comp_url, params={"HansardReportId": rep_id})
        )
        if not comp_resp:
            continue
        for item in _ni_list(s._parse_asmx_response(comp_resp, comp_url)):
            text = item.get("ComponentText", item.get("Text", item.get("Speech", "")))
            if not text or len(text.strip()) < 10:
                continue
            records.append(s._make_record(
                data_type="plenary_speech",
                member={
                    "id": str(item.get("PersonId", item.get("MemberId", ""))),
                    "name": item.get("MemberName", item.get("Speaker", "")),
                    "party": item.get("PartyName", ""),
                    "constituency": item.get("ConstituencyName", ""),
                    "role": "MLA",
                },
                date=rep_date,
                text=text,
                title=item.get("ComponentTitle", ""),
                source_url=comp_url,
            ))
    return records, f"{len(all_reports)} total reports via {used_method}; first 3 tested"


def test_ni(verbose: bool = False, save_dir: Optional[Path] = None) -> List[Result]:
    print(f"\n{_BLD}NI Assembly{_RST}")
    s = NIAssemblyScraper()
    results = []
    members: List[Dict] = []

    for dtype, fn, note, soft in [
        ("members",
         lambda: s.fetch_members(),
         "", False),
        ("register_of_interests",
         lambda: s.fetch_register_of_interests([]),
         "register.asmx — no known method returns data", True),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_90),
         f"last 90 days ({RECENT_90}→today); 1–2 date chunks", False),
        ("votes_on_division",
         lambda: s._fetch_votes_asmx(RECENT_90),
         f"last 90 days ({RECENT_90}→today); 1–2 date chunks", False),
    ]:
        r = Result("NI Assembly", dtype, note=note)
        t0 = time.time()
        try:
            records = fn()
            r.elapsed = time.time() - t0
            if dtype == "members":
                r.status, r.issues = _assess_members(records)
            else:
                r.status, r.issues = _assess(records, soft=soft)
            r.count = len(records)
            r.sample = records[0] if records else None
            if dtype == "members":
                members = records
        except Exception as e:
            r.elapsed = time.time() - t0
            r.status, r.issues = "FAIL", [str(e)]
        _emit(r, verbose)
        _maybe_save(r, save_dir)
        results.append(r)

    # Plenary — custom sample to avoid iterating all 644 reports
    r = Result("NI Assembly", "plenary_business")
    t0 = time.time()
    try:
        records, note = _ni_plenary_sample(s)
        r.elapsed = time.time() - t0
        r.note = note
        r.status, r.issues = _assess(records, soft=True)
        r.count = len(records)
        r.sample = records[0] if records else None
    except Exception as e:
        r.elapsed = time.time() - t0
        r.status, r.issues = "FAIL", [str(e)]
    _emit(r, verbose)
    _maybe_save(r, save_dir)
    results.append(r)

    return results


# ── UK Parliament ─────────────────────────────────────────────────────────────

def _uk_votes_sample(s: UKParliamentScraper) -> Tuple[List[Dict], str]:
    """Fetch 5 recent divisions + their voter lists."""
    div_url = f"{_UK_CFG['commons_votes_api']}/divisions.json/search"
    resp = s._get(div_url, params={"take": 5, "skip": 0, "startDate": RECENT_30})
    if not resp:
        return [], "divisions.json/search returned no response"
    divisions = resp.json()
    if not isinstance(divisions, list):
        return [], f"unexpected response shape: {type(divisions).__name__}"

    records = []
    for div in divisions:
        div_id    = div.get("DivisionId", div.get("divisionId", ""))
        div_title = div.get("Title",      div.get("title", ""))
        div_date  = div.get("Date",       div.get("date", ""))
        ayes      = div.get("AyeCount",   div.get("ayeCount", 0))
        noes      = div.get("NoeCount",   div.get("noeCount", 0))
        detail_resp = s._get(f"{_UK_CFG['commons_votes_api']}/division/{div_id}.json", timeout=60)
        if not detail_resp:
            continue
        detail = detail_resp.json()
        for vote_key, direction in [("Ayes", "aye"), ("Noes", "no"), ("NoVoteRecorded", "no_vote")]:
            for voter in detail.get(vote_key, []):
                records.append(s._make_record(
                    data_type="vote",
                    member={
                        "id": str(voter.get("MemberId", voter.get("memberId", ""))),
                        "name": voter.get("Name", voter.get("name", voter.get("displayAs", ""))),
                        "party": voter.get("Party", voter.get("party", "")),
                        "constituency": voter.get("SubParty", voter.get("constituency", "")),
                        "role": "MP",
                    },
                    date=div_date,
                    text=f"Voted {direction} on: {div_title}",
                    title=div_title,
                    metadata={
                        "division_id": str(div_id),
                        "vote_direction": direction,
                        "division_result": "passed" if ayes > noes else "failed",
                        "ayes": ayes, "noes": noes,
                    },
                    source_url=f"{_UK_CFG['commons_votes_api']}/division/{div_id}.json",
                ))
    return records, f"{len(divisions)} divisions fetched (capped at 5 for test)"


def test_uk(verbose: bool = False, save_dir: Optional[Path] = None) -> List[Result]:
    print(f"\n{_BLD}UK Parliament{_RST}")
    s = UKParliamentScraper()
    results = []
    members: List[Dict] = []

    # Members — first page only (20 MPs); full run fetches all current + historical
    r = Result("UK Parliament", "members",
               note="first page (20 MPs); full run fetches all current + historical MPs")
    t0 = time.time()
    try:
        resp = s._get(
            f"{_UK_CFG['members_api']}/Members/Search",
            params={"House": "Commons", "IsCurrentMember": "true", "skip": 0, "take": 20},
        )
        if resp:
            for item in resp.json().get("items", []):
                v = item.get("value", item)
                members.append({
                    "id": str(v.get("id", "")),
                    "name": v.get("nameDisplayAs", ""),
                    "party": (v.get("latestParty") or {}).get("name", ""),
                    "constituency": (v.get("latestHouseMembership") or {}).get("membershipFrom", ""),
                    "role": "MP", "status": "current",
                })
        r.elapsed = time.time() - t0
        r.status, r.issues = _assess_members(members)
        r.count = len(members)
        r.sample = members[0] if members else None
    except Exception as e:
        r.elapsed = time.time() - t0
        r.status, r.issues = "FAIL", [str(e)]
    _emit(r, verbose)
    _maybe_save(r, save_dir)
    results.append(r)

    for dtype, fn, note, soft in [
        ("register_of_interests",
         lambda: s.fetch_register_of_interests(members[:5]),
         "first 5 members only; full run iterates all MPs", False),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_30),
         f"last 30 days ({RECENT_30}→today); single year chunk", False),
        ("plenary_business",
         lambda: s.fetch_plenary_business(from_date=RECENT_30),
         f"last 30 days ({RECENT_30}→today)", False),
    ]:
        r = Result("UK Parliament", dtype, note=note)
        t0 = time.time()
        try:
            records = fn()
            r.elapsed = time.time() - t0
            r.status, r.issues = _assess(records, soft=soft)
            r.count = len(records)
            r.sample = records[0] if records else None
        except Exception as e:
            r.elapsed = time.time() - t0
            r.status, r.issues = "FAIL", [str(e)]
        _emit(r, verbose)
        _maybe_save(r, save_dir)
        results.append(r)

    # Votes — 5 divisions only
    r = Result("UK Parliament", "votes_on_division")
    t0 = time.time()
    try:
        records, note = _uk_votes_sample(s)
        r.elapsed = time.time() - t0
        r.note = note
        r.status, r.issues = _assess(records)
        r.count = len(records)
        r.sample = records[0] if records else None
    except Exception as e:
        r.elapsed = time.time() - t0
        r.status, r.issues = "FAIL", [str(e)]
    _emit(r, verbose)
    _maybe_save(r, save_dir)
    results.append(r)

    return results


# ── Scottish Parliament ───────────────────────────────────────────────────────

def _scotland_plenary_sample(s: ScottishParliamentScraper) -> Tuple[List[Dict], str]:
    """Probe last 10 weekday date-slug URLs; known to be JS-rendered → expect 0."""
    today = date.today()
    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]
    weekdays = []
    d = today
    while len(weekdays) < 10:
        if d.weekday() < 5:
            weekdays.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)

    records: List[Dict] = []
    for iso_date in weekdays:
        y, mo, day = iso_date.split("-")
        slug = f"official-report-{int(day)}-{month_names[int(mo)-1]}-{y}"
        url = (f"https://www.parliament.scot/chamber-and-committees/official-report/"
               f"what-was-said-in-parliament/{slug}")
        s._scrape_or_detail(url, iso_date, records, None)

    return records, "last 10 weekday OR URLs probed; JS-rendered → 0 expected"


def test_scotland(verbose: bool = False, save_dir: Optional[Path] = None) -> List[Result]:
    print(f"\n{_BLD}Scottish Parliament{_RST}")
    s = ScottishParliamentScraper()
    results = []
    members: List[Dict] = []

    for dtype, fn, note, soft in [
        ("members",
         lambda: s.fetch_members(),
         "OData /Members endpoint", False),
        ("register_of_interests",
         lambda: s.fetch_register_of_interests(members[:5]),
         "OData 404 → HTML fallback; JS-rendered → 0 expected", True),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_30),
         f"last 30 days; question search page is JS-rendered → 0 expected", True),
        ("votes_on_division",
         lambda: s.fetch_votes_on_division(from_date=RECENT_30),
         "all OData vote endpoints 404; web fallback also SPA → 0 expected", True),
    ]:
        r = Result("Scottish Parliament", dtype, note=note)
        t0 = time.time()
        try:
            records = fn()
            r.elapsed = time.time() - t0
            if dtype == "members":
                r.status, r.issues = _assess_members(records)
            else:
                r.status, r.issues = _assess(records, soft=soft)
            r.count = len(records)
            r.sample = records[0] if records else None
            if dtype == "members":
                members = records
        except Exception as e:
            r.elapsed = time.time() - t0
            r.status, r.issues = "FAIL", [str(e)]
        _emit(r, verbose)
        _maybe_save(r, save_dir)
        results.append(r)

    # Plenary — custom 10-date probe
    r = Result("Scottish Parliament", "plenary_business")
    t0 = time.time()
    try:
        records, note = _scotland_plenary_sample(s)
        r.elapsed = time.time() - t0
        r.note = note
        r.status, r.issues = _assess(records, soft=True)
        r.count = len(records)
        r.sample = records[0] if records else None
    except Exception as e:
        r.elapsed = time.time() - t0
        r.status, r.issues = "FAIL", [str(e)]
    _emit(r, verbose)
    _maybe_save(r, save_dir)
    results.append(r)

    return results


# ── Welsh Parliament ──────────────────────────────────────────────────────────

def _wales_votes_sample(s: WelshParliamentScraper) -> Tuple[List[Dict], str]:
    """Fetch division index then detail for first 10 rows only."""
    soup = s._try_paths(_WALES_RECORD, _WALES_DIV_PATHS)
    if not soup:
        return [], "could not load divisions index from record.senedd.wales"

    rows = []
    for sel in ["table tr", ".division-row", "li.division", "article.division", "li"]:
        rows = soup.select(sel)
        if rows:
            break
    if not rows:
        return [], "no division rows found on index page"

    records = []
    for row in rows[:10]:
        link_el = row.select_one("a[href]")
        if not link_el:
            continue
        title  = (row.select_one("td:first-child, .title, h2, h3") or link_el).get_text(strip=True)
        date_el = row.select_one("td:nth-child(2), time, .date, [class*='date']")
        div_date = date_el.get_text(strip=True) if date_el else ""
        href = link_el["href"]
        if not href or not (href.startswith("/") or href.startswith("http")):
            continue
        detail_url = href if href.startswith("http") else f"{_WALES_RECORD}{href}"
        detail_soup = s._html_get(detail_url)
        if not detail_soup:
            continue
        for direction, sels in [
            ("aye",     [".ayes li", ".for li", "[class*='aye'] li", "[class*='For'] li"]),
            ("no",      [".noes li", ".against li", "[class*='no'] li", "[class*='Against'] li"]),
            ("abstain", [".abstentions li", ".abstain li", "[class*='abstain'] li"]),
        ]:
            voters = next((detail_soup.select(sel) for sel in sels if detail_soup.select(sel)), [])
            for voter_el in voters:
                name = voter_el.get_text(strip=True)
                if name:
                    records.append(s._make_record(
                        data_type="vote",
                        member={"id": "", "name": name, "party": "",
                                "constituency": "", "role": "MS"},
                        date=div_date,
                        text=f"Voted {direction} on: {title}",
                        title=title,
                        metadata={"vote_direction": direction},
                        source_url=detail_url,
                    ))
    return records, f"{len(rows)} rows on index page; first 10 division details fetched"


def test_wales(verbose: bool = False, save_dir: Optional[Path] = None) -> List[Result]:
    print(f"\n{_BLD}Welsh Parliament (Senedd){_RST}")
    s = WelshParliamentScraper()
    results = []
    members: List[Dict] = []

    for dtype, fn, note, soft in [
        ("members",
         lambda: s.fetch_members(),
         "scraped from senedd.wales WordPress member listing", False),
        ("register_of_interests",
         lambda: s.fetch_register_of_interests(members),
         "PDF document → HTML parsing skipped (PDF parsing deferred)", True),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_30),
         "all paths return SPA nav shells → 0 expected", True),
        ("plenary_business",
         lambda: s.fetch_plenary_business(from_date=RECENT_30),
         f"last 30 days; senedd.wales sub-page following; sessions capped at 50", True),
    ]:
        r = Result("Welsh Parliament", dtype, note=note)
        t0 = time.time()
        try:
            records = fn()
            r.elapsed = time.time() - t0
            if dtype == "members":
                r.status, r.issues = _assess_members(records)
            else:
                r.status, r.issues = _assess(records, soft=soft)
            r.count = len(records)
            r.sample = records[0] if records else None
            if dtype == "members":
                members = records
        except Exception as e:
            r.elapsed = time.time() - t0
            r.status, r.issues = "FAIL", [str(e)]
        _emit(r, verbose)
        _maybe_save(r, save_dir)
        results.append(r)

    # Votes — 10 divisions only
    r = Result("Welsh Parliament", "votes_on_division")
    t0 = time.time()
    try:
        records, note = _wales_votes_sample(s)
        r.elapsed = time.time() - t0
        r.note = note
        r.status, r.issues = _assess(records, soft=True)
        r.count = len(records)
        r.sample = records[0] if records else None
    except Exception as e:
        r.elapsed = time.time() - t0
        r.status, r.issues = "FAIL", [str(e)]
    _emit(r, verbose)
    _maybe_save(r, save_dir)
    results.append(r)

    return results


# ── Output helpers ────────────────────────────────────────────────────────────

def _emit(r: Result, verbose: bool):
    issues_str = " | ".join(r.issues) if r.issues else ""
    line = (
        f"  {r.data_type:<25} {_col(r.status):<20} "
        f"{r.count:>6} records  {r.elapsed:>5.1f}s"
    )
    if issues_str:
        line += f"  [{issues_str}]"
    print(line)
    if r.note:
        print(f"  {'':25} {r.note}")
    if verbose and r.sample:
        print(f"  {'':25} Sample:")
        snippet = json.dumps(r.sample, indent=6, default=str)
        for ln in snippet.splitlines()[:20]:
            print(f"  {'':25}   {ln}")


def _maybe_save(r: Result, save_dir: Optional[Path]):
    if not save_dir or not r.sample:
        return
    save_dir.mkdir(parents=True, exist_ok=True)
    slug = r.parliament.lower().replace(" ", "_").replace("(", "").replace(")", "").strip("_")
    path = save_dir / f"{slug}_{r.data_type}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r.sample, f, indent=2, default=str)


# ── Summary table ─────────────────────────────────────────────────────────────

def _summary(all_results: List[Result], total_elapsed: float):
    passed = sum(1 for r in all_results if r.status == "PASS")
    warned = sum(1 for r in all_results if r.status == "WARN")
    failed = sum(1 for r in all_results if r.status == "FAIL")
    total  = sum(r.count for r in all_results)

    print(f"\n{'─' * 72}")
    print(
        f"{_BLD}Summary{_RST}  "
        f"{_col('PASS')} {passed}   {_col('WARN')} {warned}   {_col('FAIL')} {failed}"
        f"  |  {total:,} records across all tests  |  {total_elapsed:.0f}s"
    )
    print(f"{'─' * 72}")
    print(f"\n{'Parliament':<30} {'Data Type':<25} {'Status':<8} {'Records':>8}")
    print(f"{'─' * 75}")
    for r in all_results:
        issues_str = " | ".join(r.issues) if r.issues else ""
        row = f"{r.parliament:<30} {r.data_type:<25} {_col(r.status):<20} {r.count:>8}"
        if issues_str:
            row += f"  [{issues_str}]"
        print(row)
    print()

    # Highlight any unexpected failures
    unexpected = [r for r in all_results if r.status == "FAIL"]
    if unexpected:
        print(f"{_RED}Failures that need attention:{_RST}")
        for r in unexpected:
            print(f"  {r.parliament} / {r.data_type}: {' | '.join(r.issues)}")
        print()

    # Known limitations reminder
    known_warn = [r for r in all_results if r.status == "WARN" and "expected" in r.note.lower()]
    if known_warn:
        print("Known structural limitations (WARN is expected):")
        for r in known_warn:
            print(f"  {r.parliament} / {r.data_type}: {r.note}")
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

_RUNNERS = {
    "ni":       test_ni,
    "uk":       test_uk,
    "scotland": test_scotland,
    "wales":    test_wales,
}


def main():
    parser = argparse.ArgumentParser(
        description="Quick smoke-test for all four parliamentary scrapers (~5–10 min)"
    )
    parser.add_argument("--parliament", "-p", choices=list(_RUNNERS),
                        help="Test a single parliament: ni | uk | scotland | wales")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print a sample record for each test")
    parser.add_argument("--save", action="store_true",
                        help="Write one sample record per test to test_data/")
    args = parser.parse_args()

    keys = [args.parliament] if args.parliament else list(_RUNNERS)
    t0 = time.time()
    all_results: List[Result] = []
    for key in keys:
        all_results.extend(_RUNNERS[key](verbose=args.verbose, save_dir=Path("test_data") if args.save else None))
    _summary(all_results, time.time() - t0)


if __name__ == "__main__":
    main()
