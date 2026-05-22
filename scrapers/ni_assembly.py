"""
NI Assembly scraper using the official Open Data web services.
Service root: http://data.niassembly.gov.uk/

Available services:
  members.asmx   — MLAs
  register.asmx  — Register of Interests
  questions.asmx — Oral & Written Questions
  hansard.asmx   — Official Report (plenary speeches)
  plenary.asmx   — Divisions / Votes
"""
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Generator, List, Optional, Tuple

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["ni_assembly"]
_BASE = _CFG["api_base"]   # http://data.niassembly.gov.uk
_HISTORY_START = date(2007, 1, 1)   # AIMS data begins ~2007


def _date_chunks(from_date: Optional[str] = None,
                 chunk_months: int = 6) -> Generator[Tuple[str, str], None, None]:
    """Yield (start, end) pairs in DD/MM/YYYY format covering from_date to today."""
    start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else _HISTORY_START
    end = date.today()
    current = start
    delta = timedelta(days=chunk_months * 30)
    while current < end:
        chunk_end = min(current + delta, end)
        yield current.strftime("%d/%m/%Y"), chunk_end.strftime("%d/%m/%Y")
        current = chunk_end + timedelta(days=1)


def _first_list(data) -> List:
    """Dig out the first list value from an arbitrarily nested JSON response."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            result = _first_list(v)
            if result is not None:
                return result
    return []


class NIAssemblyScraper(BaseScraper):
    def __init__(self):
        super().__init__("NI Assembly")

    def _asmx(self, service: str, method: str, params: Optional[Dict] = None):
        """Call an ASMX JSON method and return parsed data."""
        url = f"{_BASE}/{service}.asmx/{method}"
        resp = self._get(url, params=params)
        if not resp:
            return None
        try:
            return resp.json()
        except Exception:
            # Some ASMX endpoints return a JSON string wrapped in XML or double-encoded
            try:
                return json.loads(resp.text)
            except Exception:
                logger.warning(f"[NI Assembly] Could not parse response from {url}")
                return None

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        data = self._asmx("members", "GetAllCurrentMembers_JSON")
        rows = _first_list(data)
        members = []
        for m in rows:
            members.append({
                "id": str(m.get("PersonId", m.get("MemberId", ""))),
                "name": m.get("MemberName", m.get("FullDisplayName", "")),
                "party": m.get("PartyName", m.get("Party", "")),
                "constituency": m.get("ConstituencyName", m.get("Constituency", "")),
                "role": "MLA",
                "status": "current",
            })
        logger.info(f"[NI Assembly] {len(members)} MLAs fetched")
        return members

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        data = self._asmx("register", "GetAllRegisteredInterests_JSON")
        rows = _first_list(data)
        lookup = self._member_lookup(members)
        records = []
        for item in rows:
            pid = str(item.get("PersonId", item.get("MemberId", "")))
            member = lookup.get(pid, {
                "id": pid,
                "name": item.get("MemberName", ""),
                "party": item.get("PartyName", ""),
                "constituency": "",
                "role": "MLA",
            })
            desc = item.get("InterestDescription", item.get("Description", item.get("Interest", "")))
            if not desc:
                continue
            records.append(self._make_record(
                data_type="register_of_interests",
                member=member,
                date=item.get("RegisteredDate", item.get("Date", "")),
                text=desc,
                title=item.get("CategoryName", item.get("Category", "")),
                metadata={
                    "category": item.get("CategoryName", item.get("Category", "")),
                    "interest_id": str(item.get("InterestId", item.get("Id", ""))),
                },
                source_url=f"{_BASE}/register.asmx",
            ))
        logger.info(f"[NI Assembly] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions (oral + written, fetched in date chunks)
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        endpoints = {
            "oral": "GetQuestionsForOralAnswer_TabledInRange_JSON",
            "written": "GetQuestionsForWrittenAnswer_TabledInRange_JSON",
        }
        for q_type, method in endpoints.items():
            for start, end in _date_chunks(from_date):
                data = self._asmx("questions", method,
                                  params={"startDate": start, "endDate": end})
                rows = _first_list(data)
                for q in rows:
                    q_text = q.get("QuestionText", q.get("Text", ""))
                    answer = q.get("AnswerText", q.get("Answer", ""))
                    combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": str(q.get("PersonId", q.get("MemberId", ""))),
                            "name": q.get("MemberName", q.get("Member", "")),
                            "party": q.get("PartyName", q.get("Party", "")),
                            "constituency": q.get("ConstituencyName", q.get("Constituency", "")),
                            "role": "MLA",
                        },
                        date=q.get("TabledDate", q.get("RaisedDate", q.get("Date", ""))),
                        text=combined,
                        title=q.get("SubjectTitle", q.get("Subject", q.get("Title", ""))),
                        metadata={
                            "question_id": str(q.get("QuestionId", q.get("Id", ""))),
                            "question_type": q_type,
                            "minister": q.get("MinisterName", q.get("AnsweredBy", "")),
                            "department": q.get("DepartmentName", q.get("Department", "")),
                            "status": q.get("Status", ""),
                            "answer_text": answer,
                        },
                        source_url=f"{_BASE}/questions.asmx/{method}",
                    ))
        logger.info(f"[NI Assembly] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business (Official Report / Hansard)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        # Step 1: get list of all Hansard report IDs
        data = self._asmx("hansard", "GetAllHansardReports_JSON")
        reports = _first_list(data)

        # Filter by date if requested
        if from_date:
            cutoff = datetime.strptime(from_date, "%Y-%m-%d").date()
            filtered = []
            for r in reports:
                r_date_str = r.get("PlenaryDate", r.get("Date", ""))
                try:
                    r_date = datetime.strptime(r_date_str[:10], "%Y-%m-%d").date()
                    if r_date >= cutoff:
                        filtered.append(r)
                except ValueError:
                    filtered.append(r)
            reports = filtered

        # Step 2: fetch contributions for each report
        records = []
        for report in reports:
            report_id = str(report.get("ReportId", report.get("Id", "")))
            report_date = report.get("PlenaryDate", report.get("Date", ""))
            if not report_id:
                continue

            comp_data = self._asmx("hansard", "GetHansardComponentsByReportId_JSON",
                                   params={"reportId": report_id})
            components = _first_list(comp_data)
            for item in components:
                text = item.get("ComponentText", item.get("Text", item.get("Speech", "")))
                if not text or len(text.strip()) < 10:
                    continue
                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": str(item.get("PersonId", item.get("MemberId", ""))),
                        "name": item.get("MemberName", item.get("Speaker", "")),
                        "party": item.get("PartyName", item.get("Party", "")),
                        "constituency": item.get("ConstituencyName", ""),
                        "role": "MLA",
                    },
                    date=report_date,
                    text=text,
                    title=item.get("ComponentTitle", item.get("AgendaItem", "")),
                    metadata={
                        "report_id": report_id,
                        "component_id": str(item.get("ComponentId", item.get("Id", ""))),
                    },
                    source_url=f"{_BASE}/hansard.asmx",
                ))
        logger.info(f"[NI Assembly] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        for start, end in _date_chunks(from_date):
            data = self._asmx("plenary", "GetVotesOnDivision_JSON",
                              params={"startDate": start, "endDate": end})
            rows = _first_list(data)
            for vote in rows:
                direction_raw = vote.get("VoteType", vote.get("Vote", vote.get("Type", ""))).lower()
                # Normalise to aye/no/abstain
                if direction_raw in ("aye", "yes", "for", "1"):
                    direction = "aye"
                elif direction_raw in ("no", "noe", "against", "2"):
                    direction = "no"
                else:
                    direction = direction_raw or "abstain"

                div_title = vote.get("MotionText", vote.get("DivisionTitle", vote.get("Title", "")))
                records.append(self._make_record(
                    data_type="vote",
                    member={
                        "id": str(vote.get("PersonId", vote.get("MemberId", ""))),
                        "name": vote.get("MemberName", vote.get("Name", "")),
                        "party": vote.get("PartyName", vote.get("Party", "")),
                        "constituency": vote.get("ConstituencyName", vote.get("Constituency", "")),
                        "role": "MLA",
                    },
                    date=vote.get("DivisionDate", vote.get("Date", "")),
                    text=f"Voted {direction} on: {div_title}",
                    title=div_title,
                    metadata={
                        "division_id": str(vote.get("DivisionId", vote.get("Id", ""))),
                        "vote_direction": direction,
                        "division_result": vote.get("Result", ""),
                        "ayes": vote.get("AyeCount", vote.get("Ayes", "")),
                        "noes": vote.get("NoeCount", vote.get("Noes", "")),
                    },
                    source_url=f"{_BASE}/plenary.asmx",
                ))
        logger.info(f"[NI Assembly] {len(records)} vote records fetched")
        return records
