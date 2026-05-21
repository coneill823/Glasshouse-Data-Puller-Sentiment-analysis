"""
Scottish Parliament scraper using the public OData API.
API documentation: https://data.parliament.scot/api/
"""
import logging
from typing import Dict, List, Optional

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["scottish_parliament"]
_API = _CFG["api_base"]  # https://data.parliament.scot/api


class ScottishParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("Scottish Parliament")

    def _odata_get(self, endpoint: str, filters: Optional[str] = None,
                   top: int = 1000, skip: int = 0) -> List[Dict]:
        """Paginate through an OData endpoint, returning all records."""
        url = f"{_API}/{endpoint}"
        params: Dict = {"$format": "json", "$top": top, "$skip": skip}
        if filters:
            params["$filter"] = filters

        all_results = []
        while True:
            params["$skip"] = skip
            resp = self._get(url, params=params)
            if not resp:
                break
            data = resp.json()
            items = data.get("value", data if isinstance(data, list) else [])
            if not items:
                break
            all_results.extend(items)
            if len(items) < top:
                break
            skip += top
        return all_results

    # ------------------------------------------------------------------
    # Members (MSPs)
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        rows = self._odata_get("Members")
        members = []
        for m in rows:
            members.append({
                "id": str(m.get("PersonId", m.get("MemberID", ""))),
                "name": f"{m.get('GivenName', '')} {m.get('FamilyName', '')}".strip() or m.get("DisplayName", ""),
                "party": m.get("PartyName", m.get("Party", "")),
                "constituency": m.get("ConstituencyName", m.get("RegionName", "")),
                "role": "MSP",
                "status": m.get("IsCurrent", ""),
            })
        logger.info(f"[Scottish Parliament] {len(members)} MSPs fetched")
        return members

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        rows = self._odata_get("MemberInterests")
        lookup = self._member_lookup(members)
        records = []
        for item in rows:
            pid = str(item.get("PersonId", item.get("MemberID", "")))
            member = lookup.get(pid, {
                "id": pid,
                "name": item.get("MemberName", ""),
                "party": "",
                "constituency": "",
                "role": "MSP",
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
                    "interest_id": str(item.get("MemberInterestId", item.get("Id", ""))),
                },
                source_url=f"{_API}/MemberInterests",
            ))
        logger.info(f"[Scottish Parliament] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        filters = None
        if from_date:
            filters = f"QuestionDate ge datetime'{from_date}'"
        rows = self._odata_get("Questions", filters=filters)
        records = []
        for q in rows:
            q_text = q.get("QuestionText", q.get("Text", ""))
            answer = q.get("AnswerText", q.get("Answer", ""))
            combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
            records.append(self._make_record(
                data_type="question",
                member={
                    "id": str(q.get("PersonId", q.get("AskingMemberId", ""))),
                    "name": q.get("AskingMemberName", q.get("MemberName", "")),
                    "party": q.get("AskingMemberParty", q.get("Party", "")),
                    "constituency": q.get("AskingMemberConstituency", q.get("Constituency", "")),
                    "role": "MSP",
                },
                date=q.get("QuestionDate", q.get("Date", "")),
                text=combined,
                title=q.get("SubjectText", q.get("Subject", "")),
                metadata={
                    "question_id": str(q.get("QuestionID", q.get("Id", ""))),
                    "question_type": q.get("QuestionType", "written"),
                    "answering_body": q.get("AnsweringBody", q.get("Department", "")),
                    "answer_text": answer,
                },
                source_url=f"{_API}/Questions",
            ))
        logger.info(f"[Scottish Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business (Official Reports)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        filters = None
        if from_date:
            filters = f"ReportDate ge datetime'{from_date}'"
        rows = self._odata_get("OfficialReportContributions", filters=filters)
        records = []
        for item in rows:
            text = item.get("ContributionText", item.get("Text", item.get("Speech", "")))
            if not text:
                continue
            records.append(self._make_record(
                data_type="plenary_speech",
                member={
                    "id": str(item.get("PersonId", item.get("MemberID", ""))),
                    "name": item.get("MemberName", item.get("Speaker", "")),
                    "party": item.get("PartyName", item.get("Party", "")),
                    "constituency": item.get("ConstituencyName", item.get("RegionName", "")),
                    "role": "MSP",
                },
                date=item.get("ReportDate", item.get("Date", "")),
                text=text,
                title=item.get("AgendaItem", item.get("Subject", item.get("Title", ""))),
                metadata={
                    "contribution_id": str(item.get("ContributionID", item.get("Id", ""))),
                    "report_id": str(item.get("OfficialReportID", "")),
                    "agenda_item": item.get("AgendaItem", ""),
                },
                source_url=f"{_API}/OfficialReportContributions",
            ))
        logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        filters = None
        if from_date:
            filters = f"DivisionDate ge datetime'{from_date}'"
        rows = self._odata_get("Votes", filters=filters)
        records = []
        for vote in rows:
            direction_map = {1: "aye", 2: "no", 3: "abstain"}
            direction_raw = vote.get("VoteType", vote.get("Vote", 0))
            direction = direction_map.get(direction_raw, str(direction_raw).lower())
            div_title = vote.get("DivisionName", vote.get("MotionText", vote.get("Title", "")))
            records.append(self._make_record(
                data_type="vote",
                member={
                    "id": str(vote.get("PersonId", vote.get("MemberID", ""))),
                    "name": vote.get("MemberName", vote.get("Name", "")),
                    "party": vote.get("PartyName", vote.get("Party", "")),
                    "constituency": vote.get("ConstituencyName", vote.get("RegionName", "")),
                    "role": "MSP",
                },
                date=vote.get("DivisionDate", vote.get("Date", "")),
                text=f"Voted {direction} on: {div_title}",
                title=div_title,
                metadata={
                    "division_id": str(vote.get("DivisionID", vote.get("VoteID", ""))),
                    "vote_direction": direction,
                    "division_result": vote.get("DivisionResult", vote.get("Result", "")),
                },
                source_url=f"{_API}/Votes",
            ))
        logger.info(f"[Scottish Parliament] {len(records)} vote records fetched")
        return records
