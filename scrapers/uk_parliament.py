"""
UK Parliament scraper.

APIs used:
  Members:          https://members-api.parliament.uk/api
  Written Questions: https://questions-statements-api.parliament.uk/api  (old writtenquestions-api domain retired)
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
_QUESTIONS = _CFG["questions_api"]   # https://questions-statements-api.parliament.uk/api
_VOTES = _CFG["commons_votes_api"]
_HANSARD = _CFG["hansard_api"]

# Members API caps take at 20
_MEMBERS_PAGE = 20


class UKParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("UK Parliament")

    # ------------------------------------------------------------------
    # Members (Commons — MPs)
    # ------------------------------------------------------------------

    def _fetch_member_page(self, url: str, is_current: bool, skip: int) -> List[Dict]:
        resp = self._get(url, params={
            "House": "Commons",
            "IsCurrentMember": "true" if is_current else "false",
            "skip": skip,
            "take": _MEMBERS_PAGE,
        })
        if not resp:
            return []
        data = resp.json()
        items = data.get("items", [])
        members = []
        for item in items:
            v = item.get("value", item)
            members.append({
                "id": str(v.get("id", "")),
                "name": v.get("nameDisplayAs", v.get("nameFullTitle", "")),
                "party": v.get("latestParty", {}).get("name", "") if isinstance(v.get("latestParty"), dict) else "",
                "constituency": v.get("latestHouseMembership", {}).get("membershipFrom", "") if isinstance(v.get("latestHouseMembership"), dict) else "",
                "role": "MP",
                "status": "current" if is_current else "historical",
            })
        return members

    def fetch_members(self) -> List[Dict]:
        url = f"{_MEMBERS}/Members/Search"
        all_members = []
        for is_current in (True, False):
            skip = 0
            while True:
                batch = self._fetch_member_page(url, is_current, skip)
                all_members.extend(batch)
                if len(batch) < _MEMBERS_PAGE:
                    break
                skip += _MEMBERS_PAGE
        logger.info(f"[UK Parliament] {len(all_members)} MPs fetched")
        return all_members

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        records = []
        total = len(members)
        for i, member in enumerate(members):
            if i % 100 == 0:
                logger.info(f"[UK Parliament] Interests: {i}/{total} members processed ({len(records)} records so far)")
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
    # Questions (written) — new API domain
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        # New endpoint: questions-statements-api.parliament.uk
        url = f"{_QUESTIONS}/writtenquestions/questions"
        params: Dict = {"house": "Commons", "take": 100, "skip": 0}
        if from_date:
            params["tabledWhenFrom"] = from_date

        records = []
        skip = 0
        while True:
            params["skip"] = skip
            if skip % 1000 == 0 and skip > 0:
                logger.info(f"[UK Parliament] Questions: fetched {len(records)} so far (page {skip // 100})...")
            resp = self._get(url, params=params, timeout=90)
            if not resp:
                break
            data = resp.json()
            # Response shape: {"results": [...]} or {"questions": [...]}
            items = data.get("results", data.get("questions", []))
            if not items:
                break
            for item in items:
                v = item.get("value", item)
                q_text = v.get("questionText", v.get("text", ""))
                answer = v.get("answerText", v.get("answer", ""))
                combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                records.append(self._make_record(
                    data_type="question",
                    member={
                        "id": str(v.get("askingMemberId", v.get("memberId", ""))),
                        "name": v.get("askingMember", {}).get("name", "") if isinstance(v.get("askingMember"), dict) else v.get("memberName", ""),
                        "party": v.get("askingMember", {}).get("party", "") if isinstance(v.get("askingMember"), dict) else "",
                        "constituency": v.get("askingMember", {}).get("memberFrom", "") if isinstance(v.get("askingMember"), dict) else "",
                        "role": "MP",
                    },
                    date=v.get("tabledWhen", v.get("dateTabled", "")),
                    text=combined,
                    title=v.get("heading", v.get("subject", "")),
                    metadata={
                        "question_id": str(v.get("id", "")),
                        "question_type": "written",
                        "answering_body": v.get("answeringBodyName", ""),
                        "answering_member": v.get("answeringMember", {}).get("name", "") if isinstance(v.get("answeringMember"), dict) else "",
                        "answer_date": v.get("dateAnswered", ""),
                        "is_withdrawn": v.get("isWithdrawn", False),
                        "answer_text": answer,
                    },
                    source_url=url,
                ))
            if len(items) < 100:
                break
            skip += 100
        logger.info(f"[UK Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business (Written Statements via Hansard API)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        # Written statements live on the same API as questions, not hansard.parliament.uk
        # hansard.parliament.uk/api/* all return 404; correct domain is questions-statements-api
        endpoints = [
            (f"{_QUESTIONS}/writtenstatements/statements", "plenary_speech"),
            (f"{_HANSARD}/writtenStatements/Commons", "plenary_speech"),
            (f"{_HANSARD}/writtenStatements", "plenary_speech"),
            (f"{_HANSARD}/debates/Commons", "plenary_speech"),
            (f"{_HANSARD}/debates", "plenary_speech"),
        ]
        for url, dtype in endpoints:
            params: Dict = {"take": 100, "skip": 0}
            if from_date:
                params["startDate"] = from_date
            skip = 0
            batch_found = False
            while True:
                params["skip"] = skip
                if skip % 1000 == 0 and skip > 0:
                    logger.info(f"[UK Parliament] Plenary: fetched {len(records)} so far from {url}...")
                resp = self._get(url, params=params, timeout=90)
                if not resp:
                    break
                data = resp.json()
                # questions-statements-api wraps in {"results": [...]} or {"statements": [...]}
                if isinstance(data, list):
                    raw_items = data
                else:
                    raw_items = data.get("results", data.get("statements", data.get("items", data.get("contributions", []))))
                # Each item may itself be wrapped in a "value" key
                items = []
                for entry in raw_items:
                    items.append(entry.get("value", entry) if isinstance(entry, dict) else entry)
                if not items:
                    if skip == 0:
                        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
                        logger.warning(f"[UK Parliament] Plenary endpoint {url} responded but returned no items (keys: {keys})")
                    break
                batch_found = True
                for item in items:
                    text = item.get("Value", item.get("text", item.get("body",
                           item.get("ContributionText", item.get("StatementText", "")))))
                    if not text:
                        continue
                    member_obj = item.get("member", item.get("Member", {})) if isinstance(item.get("member", item.get("Member")), dict) else {}
                    records.append(self._make_record(
                        data_type=dtype,
                        member={
                            "id": str(item.get("MemberId", item.get("memberId", member_obj.get("id", "")))),
                            "name": item.get("AttributedTo", item.get("MemberName",
                                   item.get("memberName", member_obj.get("name",
                                   item.get("nameDisplayAs", ""))))),
                            "party": item.get("Party", member_obj.get("party", "")),
                            "constituency": item.get("MemberFrom", member_obj.get("memberFrom", "")),
                            "role": "MP",
                        },
                        date=item.get("Date", item.get("date", item.get("SittingDate",
                             item.get("dateMade", "")))),
                        text=text,
                        title=item.get("Title", item.get("title", item.get("DebateSection",
                              item.get("subject", "")))),
                        metadata={
                            "statement_id": str(item.get("Id", item.get("id",
                                              item.get("ContributionId", "")))),
                            "house": item.get("House", item.get("house", "Commons")),
                        },
                        source_url=url,
                    ))
                if len(items) < 100:
                    break
                skip += 100
            if batch_found:
                logger.info(f"[UK Parliament] Plenary data from: {url}")
                break  # got data from this endpoint — skip remaining
        logger.info(f"[UK Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        # Step 1: get the list of divisions
        div_url = f"{_VOTES}/divisions.json/search"
        params: Dict = {"take": 25, "skip": 0}
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

        logger.info(f"[UK Parliament] Found {len(divisions)} divisions — fetching per-member votes...")
        # Step 2: fetch voter lists per division
        # Correct endpoint: /data/division/{id}.json  (singular "division", .json suffix)
        # Confirmed format from the UK Parliament R client library (clvotes)
        records = []
        for i, div in enumerate(divisions):
            if i % 50 == 0:
                logger.info(f"[UK Parliament] Votes: {i}/{len(divisions)} divisions processed ({len(records)} records so far)")
            div_id = div.get("DivisionId", div.get("divisionId", ""))
            div_title = div.get("Title", div.get("title", ""))
            div_date = div.get("Date", div.get("date", ""))
            ayes = div.get("AyeCount", div.get("ayeCount", 0))
            noes = div.get("NoeCount", div.get("noeCount", 0))
            result = "passed" if ayes > noes else "failed"

            detail_url = f"{_VOTES}/division/{div_id}.json"
            detail_resp = self._get(detail_url, timeout=60)
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
                            "constituency": voter.get("SubParty", voter.get("constituency", "")),
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
