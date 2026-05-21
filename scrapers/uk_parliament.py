"""
UK Parliament scraper.

APIs used:
  Members:          https://members-api.parliament.uk/api
  Written Questions: https://writtenquestions-api.parliament.uk/api
  Commons Votes:    https://commonsvotes-api.parliament.uk/data
  Hansard (debates): https://hansard.parliament.uk/api
"""
import logging
from typing import Dict, List, Optional

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["uk_parliament"]
_MEMBERS = _CFG["members_api"]
_QUESTIONS = _CFG["questions_api"]
_VOTES = _CFG["commons_votes_api"]
_HANSARD = _CFG["hansard_api"]


class UKParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("UK Parliament")

    # ------------------------------------------------------------------
    # Members (Commons only — MPs)
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        url = f"{_MEMBERS}/Members/Search"
        all_members = []
        skip = 0
        page_size = 100
        while True:
            resp = self._get(url, params={
                "House": "Commons",
                "IsCurrentMember": "true",
                "skip": skip,
                "take": page_size,
            })
            if not resp:
                break
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                v = item.get("value", item)
                all_members.append({
                    "id": str(v.get("id", "")),
                    "name": v.get("nameDisplayAs", v.get("nameFullTitle", "")),
                    "party": v.get("latestParty", {}).get("name", "") if isinstance(v.get("latestParty"), dict) else "",
                    "constituency": v.get("latestHouseMembership", {}).get("membershipFrom", ""),
                    "role": "MP",
                    "status": "current",
                })
            if len(items) < page_size:
                break
            skip += page_size

        # Also pull historical members for full history
        skip = 0
        while True:
            resp = self._get(url, params={
                "House": "Commons",
                "IsCurrentMember": "false",
                "skip": skip,
                "take": page_size,
            })
            if not resp:
                break
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                v = item.get("value", item)
                all_members.append({
                    "id": str(v.get("id", "")),
                    "name": v.get("nameDisplayAs", v.get("nameFullTitle", "")),
                    "party": v.get("latestParty", {}).get("name", "") if isinstance(v.get("latestParty"), dict) else "",
                    "constituency": v.get("latestHouseMembership", {}).get("membershipFrom", ""),
                    "role": "MP",
                    "status": "historical",
                })
            if len(items) < page_size:
                break
            skip += page_size

        logger.info(f"[UK Parliament] {len(all_members)} MPs fetched")
        return all_members

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        records = []
        for member in members:
            url = f"{_MEMBERS}/Members/{member['id']}/RegisteredInterests"
            resp = self._get(url)
            if not resp:
                continue
            data = resp.json()
            categories = data.get("value", data) if isinstance(data, dict) else data
            if not isinstance(categories, list):
                continue
            for category in categories:
                cat_name = category.get("name", "")
                for interest in category.get("interests", []):
                    desc = interest.get("interest", interest.get("description", ""))
                    if not desc:
                        continue
                    records.append(self._make_record(
                        data_type="register_of_interests",
                        member=member,
                        date=interest.get("createdWhen", interest.get("lastAmendedWhen", "")),
                        text=desc,
                        title=cat_name,
                        metadata={
                            "category": cat_name,
                            "interest_id": str(interest.get("id", "")),
                            "registered_late": interest.get("registeredLate", False),
                        },
                        source_url=url,
                    ))
        logger.info(f"[UK Parliament] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions (written)
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_QUESTIONS}/writtenquestions/search"
        params = {
            "house": "Commons",
            "take": 100,
            "skip": 0,
        }
        if from_date:
            params["tabledWhenFrom"] = from_date

        all_questions = []
        skip = 0
        while True:
            params["skip"] = skip
            resp = self._get(url, params=params)
            if not resp:
                break
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_questions.extend(results)
            if len(results) < 100:
                break
            skip += 100

        records = []
        for item in all_questions:
            v = item.get("value", item)
            q_text = v.get("questionText", "")
            answer = v.get("answerText", "")
            combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
            records.append(self._make_record(
                data_type="question",
                member={
                    "id": str(v.get("askingMemberId", "")),
                    "name": v.get("askingMember", {}).get("name", "") if isinstance(v.get("askingMember"), dict) else "",
                    "party": v.get("askingMember", {}).get("party", "") if isinstance(v.get("askingMember"), dict) else "",
                    "constituency": v.get("askingMember", {}).get("memberFrom", "") if isinstance(v.get("askingMember"), dict) else "",
                    "role": "MP",
                },
                date=v.get("tabledWhen", v.get("dateTabled", "")),
                text=combined,
                title=v.get("heading", ""),
                metadata={
                    "question_id": str(v.get("id", "")),
                    "question_type": "written",
                    "answering_body": v.get("answeringBodyName", ""),
                    "answering_member": v.get("answeringMember", {}).get("name", "") if isinstance(v.get("answeringMember"), dict) else "",
                    "answer_date": v.get("dateAnswered", ""),
                    "is_withdrawn": v.get("isWithdrawn", False),
                    "answer_text": answer,
                },
                source_url=f"{_QUESTIONS}/writtenquestions/search",
            ))
        logger.info(f"[UK Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business (Hansard debates)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_HANSARD}/writtenstatements"
        params = {"take": 100, "skip": 0}
        if from_date:
            params["startDate"] = from_date

        records = []
        skip = 0
        while True:
            params["skip"] = skip
            resp = self._get(url, params=params)
            if not resp:
                break
            data = resp.json()
            items = data.get("Results", data.get("results", []))
            if not items:
                break
            for item in items:
                text = item.get("Value", item.get("text", item.get("body", "")))
                if not text:
                    continue
                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": str(item.get("MemberId", item.get("memberId", ""))),
                        "name": item.get("AttributedTo", item.get("memberName", "")),
                        "party": "",
                        "constituency": "",
                        "role": "MP",
                    },
                    date=item.get("Date", item.get("date", "")),
                    text=text,
                    title=item.get("Title", item.get("title", "")),
                    metadata={
                        "statement_id": str(item.get("Id", item.get("id", ""))),
                        "house": item.get("House", "Commons"),
                    },
                    source_url=url,
                ))
            if len(items) < 100:
                break
            skip += 100

        logger.info(f"[UK Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        # Step 1: fetch all divisions
        div_url = f"{_VOTES}/divisions.json/search"
        params = {"take": 25, "skip": 0}
        if from_date:
            params["startDate"] = from_date

        divisions = []
        skip = 0
        while True:
            params["skip"] = skip
            resp = self._get(div_url, params=params)
            if not resp:
                break
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            divisions.extend(batch)
            if len(batch) < 25:
                break
            skip += 25

        # Step 2: fetch per-division voting records
        records = []
        for div in divisions:
            div_id = div.get("DivisionId", div.get("divisionId", ""))
            div_title = div.get("Title", div.get("title", ""))
            div_date = div.get("Date", div.get("date", ""))
            ayes = div.get("AyeCount", div.get("ayeCount", 0))
            noes = div.get("NoeCount", div.get("noeCount", 0))
            result = "passed" if ayes > noes else "failed"

            detail_url = f"{_VOTES}/divisions.json/{div_id}"
            detail_resp = self._get(detail_url)
            if not detail_resp:
                continue
            detail = detail_resp.json()

            for vote_key, direction in [("Ayes", "aye"), ("Noes", "no"), ("NoVoteRecorded", "no_vote")]:
                for voter in detail.get(vote_key, []):
                    records.append(self._make_record(
                        data_type="vote",
                        member={
                            "id": str(voter.get("MemberId", voter.get("memberId", ""))),
                            "name": voter.get("Name", voter.get("name", voter.get("displayAs", ""))),
                            "party": voter.get("Party", voter.get("party", "")),
                            "constituency": voter.get("SubParty", ""),
                            "role": "MP",
                        },
                        date=div_date,
                        text=f"Voted {direction} on: {div_title}",
                        title=div_title,
                        metadata={
                            "division_id": str(div_id),
                            "vote_direction": direction,
                            "division_result": result,
                            "ayes": ayes,
                            "noes": noes,
                        },
                        source_url=detail_url,
                    ))
        logger.info(f"[UK Parliament] {len(records)} vote records fetched")
        return records
