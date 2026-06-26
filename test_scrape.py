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
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class _Tee:
    """Mirror writes to both the original stdout and a log file simultaneously."""

    def __init__(self, path: Path):
        self._orig = sys.__stdout__
        self._f = open(path, "w", encoding="utf-8")
        sys.stdout = self

    def write(self, data: str) -> None:
        self._orig.write(data)
        self._f.write(data)

    def flush(self) -> None:
        self._orig.flush()
        self._f.flush()

    def isatty(self) -> bool:
        return False

    def close(self) -> None:
        sys.stdout = self._orig
        self._f.close()

# Scraper WARNING/ERROR output will be routed to stdout inside main()
# so it ends up in both terminal and log file.

from config import PARLIAMENTS
from scrapers.ni_assembly import NIAssemblyScraper, _first_list as _ni_list, _extract_ni_speaker
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
        current_name = ""
        current_id = ""
        for item in _ni_list(s._parse_asmx_response(comp_resp, comp_url)):
            text = item.get("ComponentText", item.get("Text", item.get("Speech", "")))
            if not text or len(text.strip()) < 10:
                continue
            comp_header = item.get("ComponentHeader", "")
            # ComponentHeader is often the speaker name for speech contributions;
            # exclude time-of-day strings ("10:30") and very long headers.
            header_is_time = bool(re.match(r"^\d{1,2}:\d{2}", comp_header.strip())) if comp_header else True
            speaker_from_header = comp_header if (comp_header and not header_is_time and len(comp_header) < 80) else ""
            name = (item.get("MemberName") or item.get("Speaker")
                    or speaker_from_header or _extract_ni_speaker(text) or "")
            member_id = str(item.get("PersonId", item.get("MemberId", "")))
            # Carry forward last known speaker for continuation paragraphs
            if name:
                current_name = name
                current_id = member_id
            elif current_name:
                name = current_name
                if not member_id:
                    member_id = current_id
            # Reset on procedural/heading components
            comp_type = item.get("ComponentType", "")
            if comp_type and re.search(r"Head|Agenda|Procedur|Title|Item", comp_type, re.I):
                current_name = ""
                current_id = ""
            records.append(s._make_record(
                data_type="plenary_speech",
                member={
                    "id": member_id,
                    "name": name,
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
         "OData 404 → register published as consolidated PDF, parsed with PyMuPDF", True),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_30),
         "last 30 days; SPA question pages browser-rendered, parsed by field labels (Asked by/Date lodged/Question/Answer)", True),
        ("votes_on_division",
         lambda: s.fetch_votes_on_division(from_date=RECENT_30),
         "OData 404 → motion-page/division scraping, now with headless-browser render for JS-rendered pages", True),
        ("plenary_business",
         lambda: s.fetch_plenary_business(from_date=RECENT_90),
         f"Official Report via browser-driven search (meeting-of-parliament IDs) → media-API PDF → PyMuPDF; recent windows can be sparse around the May 2026 election but historical sittings parse fully", True),
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

    return results


# ── Welsh Parliament ──────────────────────────────────────────────────────────

def _wales_votes_sample(s: WelshParliamentScraper) -> Tuple[List[Dict], str]:
    """Prefer the production XML-export path (reliable dates+names); fall back to
    Search-page vote scraping."""
    # 1. Production path: meeting IDs → XML transcript export
    meeting_ids = s._fetch_meeting_ids_wales(RECENT_90)
    if meeting_ids:
        records: List[Dict] = []
        hits = 0
        for m in meeting_ids[:10]:
            added = s._fetch_votes_xml_export(m["id"], m.get("date", ""), None, records)
            if added > 0:
                hits += 1
        if records:
            return records, f"{len(meeting_ids)} meetings found; XML export for first 10 ({hits} had votes)"
        if meeting_ids:
            # Meetings found but XML returned 0 — log for diagnosis
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"[Wales votes] {len(meeting_ids)} meetings found but XML export returned 0 votes "
                f"— sample meetings: {meeting_ids[:3]}"
            )

    # 2. Try Search page with division-type filter
    search_records = s._fetch_votes_search(RECENT_90)
    if search_records:
        return search_records, f"record.assembly.wales/Search division filter ({len(search_records)} records)"

    # 3. Fallback: HTML division-index scraping (all known paths now broken)
    soup = s._try_paths(_WALES_RECORD, _WALES_DIV_PATHS) if _WALES_DIV_PATHS else None
    if not soup:
        return [], ("XMLExport serves only 5th-Senedd committee meetings (no divisions); "
                    "Search/record pages are JS-rendered → 0 expected")

    rows = []
    for sel in ["table tr", ".division-row", "li.division", "article.division", "li"]:
        rows = soup.select(sel)
        if rows:
            break
    if not rows:
        return [], "no division rows found on index page"

    records = []
    # A real division link points at a vote/division/meeting detail page — not the
    # site nav (glossary, help, contact, senedd-business, etc.).
    _NAV_RE = re.compile(r"/(glossary|help|contact|search|senedd-business|committees|"
                         r"legislation|about|cookie|privacy|accessibility)", re.I)
    _DIV_RE = re.compile(r"vot|division|meeting|plenary|cofnod|record", re.I)

    def _division_link(r):
        for a in r.select("a[href]"):
            href = a.get("href", "")
            if not href.startswith(("/", "http")):
                continue
            if _NAV_RE.search(href):
                continue
            if _DIV_RE.search(href):
                return a
        return None

    division_rows = [(r, _division_link(r)) for r in rows]
    division_rows = [(r, a) for r, a in division_rows if a is not None]
    for row, link_el in division_rows[:20]:
        if not link_el:
            continue
        title  = (row.select_one("td:first-child, .title, h2, h3") or link_el).get_text(strip=True)
        date_el = row.select_one("time[datetime], td:nth-child(2), time, .date, [class*='date'], li:nth-child(2)")
        div_date = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
        if not div_date:
            row_text = row.get_text(separator=" ", strip=True)
            dm = re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{1,2}\s+\w+\s+\d{4}", row_text)
            div_date = dm.group(0) if dm else ""
        href = link_el["href"]
        if not href or not (href.startswith("/") or href.startswith("http")):
            continue
        detail_url = href if href.startswith("http") else f"{_WALES_RECORD}{href}"
        detail_soup = s._html_get(detail_url)
        if not detail_soup:
            continue
        # Try to extract date from the detail page if not found in index row
        if not div_date:
            for sel in ["time[datetime]", "time", ".date", "[class*='date']", "h1", "h2"]:
                el = detail_soup.select_one(sel)
                if el:
                    candidate = el.get("datetime", el.get_text(strip=True))
                    dm = re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{1,2}\s+\w+\s+\d{4}", candidate)
                    if dm:
                        div_date = dm.group(0)
                        break
        for direction, sels in [
            ("aye",     [".ayes li", ".for li", "[class*='aye'] li", "[class*='For'] li",
                         ".vote-aye li", ".vote-for li", "ul.for li", "ul.ayes li"]),
            ("no",      [".noes li", ".against li", "[class*='no'] li", "[class*='Against'] li",
                         ".vote-no li", ".vote-against li", "ul.against li", "ul.noes li"]),
            ("abstain", [".abstentions li", ".abstain li", "[class*='abstain'] li",
                         ".vote-abstain li"]),
        ]:
            voters = next((detail_soup.select(sel) for sel in sels if detail_soup.select(sel)), [])
            if not voters:
                # Log CSS classes once so we know what's on the page
                if not hasattr(s, "_wales_vote_detail_logged"):
                    s._wales_vote_detail_logged = True
                    all_cls = sorted({c for el in detail_soup.select("[class]") for c in el.get("class", [])})
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        f"[Wales votes detail] {detail_url} CSS classes: {all_cls[:30]}"
                    )
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
    return records, f"{len(rows)} rows on index page; {len(division_rows)} division rows; first 20 fetched"


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
         "register PDF parsed with PyMuPDF; ~200 ongoing-role entries carry no inline date → date WARN expected", True),
        ("questions",
         lambda: s.fetch_questions(from_date=RECENT_30),
         f"last 30 days ({RECENT_30}→today); record.assembly.wales/Search (SSR)", True),
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

    # ── Log file setup ────────────────────────────────────────────────────
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    run_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    parl_label = args.parliament or "all"
    log_path = logs_dir / f"test_{parl_label}_{run_ts}.log"
    tee = _Tee(log_path)

    # Route scraper WARNING/ERROR logs to stdout (captured by tee → log file)
    _log_root = logging.getLogger()
    _log_root.handlers.clear()
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setLevel(logging.WARNING)
    _sh.setFormatter(logging.Formatter("%(levelname)-8s %(name)s  %(message)s"))
    _log_root.addHandler(_sh)
    _log_root.setLevel(logging.WARNING)

    print(f"Log: {log_path.resolve()}")

    # ── Runtime diagnostics ───────────────────────────────────────────────
    # The scrapers report Playwright/PyMuPDF as unimportable even though
    # `python -c "import fitz, playwright"` succeeds from the same shell.
    # Print exactly which interpreter/site-packages this run is using and
    # whether it can see the optional deps, so a mismatch (e.g. a different
    # interpreter than the one `python` resolves to interactively, or a
    # site-packages dir that isn't on this process's sys.path) is visible
    # directly in the log instead of being inferred.
    print(f"Interpreter: {sys.executable}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"sys.path[:5]: {sys.path[:5]}")
    for _mod in ("fitz", "playwright"):
        try:
            _m = __import__(_mod)
            print(f"  import {_mod}: OK — {getattr(_m, '__file__', '?')}")
        except Exception as _e:
            print(f"  import {_mod}: FAILED — {type(_e).__name__}: {_e}")
    # ─────────────────────────────────────────────────────────────────────

    keys = [args.parliament] if args.parliament else list(_RUNNERS)
    t0 = time.time()
    all_results: List[Result] = []
    try:
        for key in keys:
            all_results.extend(_RUNNERS[key](verbose=args.verbose, save_dir=Path("test_data") if args.save else None))
        _summary(all_results, time.time() - t0)
    finally:
        tee.close()


if __name__ == "__main__":
    main()
