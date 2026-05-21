"""
NI Assembly scraper using the AIMS public API.
API documentation: https://aims.niassembly.gov.uk/api/
"""
import logging
from typing import Dict, List, Optional

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["ni_assembly"]
_API = f"{_CFG['api_base']}/api/1.0"


class NIAssemblyScraper(BaseScraper):
    def __init__(self):
        super().__init__("NI Assembly")

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        resp = self._get(f"{_API}/members/members.json")
        if not resp:
            return []
        raw = resp.json()
        rows = raw.get("Members", raw) if isinstance(raw, dict) else raw
        members = []
        for m in rows:
            members.append({
                "id": str(m.get("PersonId", m.get("MemberId", ""))),
                "name": m.get("MemberName", m.get("FullName", "")),
                "party": m.get("PartyName", m.get("Party", "")),
                "constituency": m.get("ConstituencyName", m.get("Constituency", "")),
                "role": "MLA",
                "status": m.get("Status", ""),
            })
        logger.info(f"[NI Assembly] {len(members)} MLAs fetched")
        return members

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        resp = self._get(f"{_API}/members/interests.json")
        if not resp:
            return []
        raw = resp.json()
        rows = raw.get("Interests", raw) if isinstance(raw, dict) else raw
        lookup = self._member_lookup(members)
        records = []
        for item in rows:
            pid = str(item.get("PersonId", ""))
            member = lookup.get(pid, {
                "id": pid,
                "name": item.get("MemberName", ""),
                "party": item.get("PartyName", item.get("Party", "")),
                "constituency": "",
                "role": "MLA",
            })
            desc = item.get("Description", item.get("Interest", ""))
            if not desc:
                continue
            records.append(self._make_record(
                data_type="register_of_interests",
                member=member,
                date=item.get("RegisteredDate", item.get("Date", "")),
                text=desc,
                title=item.get("Category", item.get("InterestType", "")),
                metadata={
                    "category": item.get("Category", ""),
                    "interest_id": str(item.get("InterestId", "")),
                },
                source_url=f"{_CFG['api_base']}/members/interests",
            ))
        logger.info(f"[NI Assembly] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        endpoints = {
            "oral": f"{_API}/questions/orals.json",
            "written": f"{_API}/questions/writtenquestions.json",
        }
        for q_type, url in endpoints.items():
            params = {}
            if from_date:
                params["DateRaisedFrom"] = from_date
            resp = self._get(url, params=params or None)
            if not resp:
                continue
            raw = resp.json()
            # Handle varied key names across API versions
            for key in ("Questions", "OralQuestions", "WrittenQuestions"):
                if key in raw:
                    rows = raw[key]
                    break
            else:
                rows = raw if isinstance(raw, list) else []

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
                    date=q.get("RaisedDate", q.get("Date", "")),
                    text=combined,
                    title=q.get("Subject", q.get("Topic", q.get("Title", ""))),
                    metadata={
                        "question_id": str(q.get("QuestionId", q.get("Id", ""))),
                        "question_type": q_type,
                        "minister": q.get("MinisterName", q.get("AnsweredBy", "")),
                        "department": q.get("Department", ""),
                        "status": q.get("Status", ""),
                        "answer_text": answer,
                    },
                    source_url=url,
                ))
        logger.info(f"[NI Assembly] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_API}/plenary/hansard.json"
        params = {}
        if from_date:
            params["DateFrom"] = from_date
        resp = self._get(url, params=params or None)
        if not resp:
            return []
        raw = resp.json()
        for key in ("Contributions", "Speeches", "PlenaryItems"):
            if key in raw:
                rows = raw[key]
                break
        else:
            rows = raw if isinstance(raw, list) else []

        records = []
        for item in rows:
            text = item.get("ContributionText", item.get("Text", item.get("Speech", "")))
            if not text:
                continue
            records.append(self._make_record(
                data_type="plenary_speech",
                member={
                    "id": str(item.get("PersonId", item.get("MemberId", ""))),
                    "name": item.get("MemberName", item.get("Speaker", "")),
                    "party": item.get("PartyName", item.get("Party", "")),
                    "constituency": item.get("ConstituencyName", item.get("Constituency", "")),
                    "role": "MLA",
                },
                date=item.get("Date", item.get("SittingDate", "")),
                text=text,
                title=item.get("Topic", item.get("AgendaItem", item.get("Title", ""))),
                metadata={
                    "contribution_id": str(item.get("ContributionId", item.get("Id", ""))),
                    "sitting_id": str(item.get("SittingId", "")),
                    "agenda_item": item.get("AgendaItem", ""),
                },
                source_url=url,
            ))
        logger.info(f"[NI Assembly] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_API}/plenary/divisions.json"
        params = {}
        if from_date:
            params["DateFrom"] = from_date
        resp = self._get(url, params=params or None)
        if not resp:
            return []
        raw = resp.json()
        divisions = raw.get("Divisions", raw) if isinstance(raw, dict) else raw

        records = []
        for div in divisions:
            div_id = str(div.get("DivisionId", div.get("Id", "")))
            div_title = div.get("Title", div.get("Motion", ""))
            div_date = div.get("Date", div.get("SittingDate", ""))
            ayes = div.get("Ayes", 0)
            noes = div.get("Noes", 0)
            result = "passed" if ayes > noes else "failed"

            for group_key, direction in [("AyeVotes", "aye"), ("NoeVotes", "no"), ("AbstainVotes", "abstain")]:
                for vote in div.get(group_key, []):
                    records.append(self._make_record(
                        data_type="vote",
                        member={
                            "id": str(vote.get("PersonId", vote.get("MemberId", ""))),
                            "name": vote.get("MemberName", vote.get("Name", "")),
                            "party": vote.get("PartyName", vote.get("Party", "")),
                            "constituency": vote.get("ConstituencyName", vote.get("Constituency", "")),
                            "role": "MLA",
                        },
                        date=div_date,
                        text=f"Voted {direction} on: {div_title}",
                        title=div_title,
                        metadata={
                            "division_id": div_id,
                            "vote_direction": direction,
                            "division_result": result,
                            "ayes": ayes,
                            "noes": noes,
                        },
                        source_url=url,
                    ))
        logger.info(f"[NI Assembly] {len(records)} vote records fetched")
        return records
