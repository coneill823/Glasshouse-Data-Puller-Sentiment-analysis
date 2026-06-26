"""
UK Parliament scraper.

APIs used:
  Members:          https://members-api.parliament.uk/api
  Written Questions: https://questions-statements-api.parliament.uk/api  (old writtenquestions-api domain retired)
  Commons Votes:    https://commonsvotes-api.parliament.uk/data
  Hansard (spoken debate contributions): https://hansard-api.parliament.uk
"""
import logging
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
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

# The Hansard search index caps deep pagination (results beyond ~10k skip are not
# returned), so the spoken-contributions pull walks the date range in chunks of
# this many days to keep each query's result set under the cap. A busy sitting
# fortnight stays well below 10k Commons contributions.
_HANSARD_CHUNK_DAYS = 14
_HANSARD_SKIP_CAP = 10000


class UKParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("UK Parliament")
        # Populated by fetch_members(); used by fetch_questions() / fetch_plenary_business()
        # to resolve member names when the API returns null for askingMember / member fields.
        self._member_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Members (Commons — MPs)
    # ------------------------------------------------------------------

    def _fetch_member_page(self, url: str, is_current: bool, skip: int,
                            house: str = "Commons") -> List[Dict]:
        resp = self._get(url, params={
            "House": house,
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
                "role": "MP" if house == "Commons" else "Lord",
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
        self._member_cache = {m["id"]: m for m in all_members}
        # Also populate the cache with Lords members so written-statement authors
        # from the upper House resolve too (statements API mixes both Houses).
        # Lords are added to the cache only — not the returned MP list.
        lords_count = 0
        for is_current in (True, False):
            skip = 0
            while True:
                batch = self._fetch_member_page(url, is_current, skip, house="Lords")
                for m in batch:
                    if m["id"] and m["id"] not in self._member_cache:
                        self._member_cache[m["id"]] = m
                        lords_count += 1
                if len(batch) < _MEMBERS_PAGE:
                    break
                skip += _MEMBERS_PAGE
        logger.info(f"[UK Parliament] {lords_count} Lords added to member cache (cache size {len(self._member_cache)})")
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

    def fetch_questions(self, from_date: Optional[str] = None,
                        to_date: Optional[str] = None) -> List[Dict]:
        if not self._member_cache:
            self.fetch_members()
        # questions-statements-api hard-caps at page 200 (offset 20,000) with HTTP 500.
        # Chunk by year so each chunk's offset pagination stays well below that limit.
        url = f"{_QUESTIONS}/writtenquestions/questions"
        today = to_date or _date.today().isoformat()

        if from_date:
            # Incremental pull — single range, unlikely to exceed the per-chunk cap
            chunks = [(from_date, today)]
        else:
            # Full pull — quarterly from 2015 to the range end ("today" above).
            # Year-level chunks exceeded the 20K/page-200 hard cap for high-volume years
            # (2017, 2018, 2019, 2021, 2024 each had 25K–32K questions per year).
            # Quarterly chunks keep each chunk under ~10K, safely below the cap.
            start_year = 2015
            current_year = int(today[:4])
            chunks = []
            quarter_starts = ["01-01", "04-01", "07-01", "10-01"]
            quarter_ends   = ["03-31", "06-30", "09-30", "12-31"]
            for year in range(start_year, current_year + 1):
                for i in range(4):
                    q_start = f"{year}-{quarter_starts[i]}"
                    if q_start > today:
                        break
                    q_end = min(f"{year}-{quarter_ends[i]}", today)
                    chunks.append((q_start, q_end))

        records = []
        seen_ids: set = set()
        for chunk_start, chunk_end in chunks:
            logger.info(f"[UK Parliament] Questions: fetching {chunk_start} → {chunk_end}")
            params: Dict = {
                "house": "Commons",
                "take": 100,
                "skip": 0,
                "tabledWhenFrom": chunk_start,
                "tabledWhenTo": chunk_end,
            }
            chunk_count = 0
            skip = 0
            while True:
                params["skip"] = skip
                if skip % 1000 == 0 and skip > 0:
                    logger.info(f"[UK Parliament] Questions {chunk_start}: {chunk_count} so far (skip {skip})...")
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
                    q_id = str(v.get("id", ""))
                    if q_id and q_id in seen_ids:
                        continue
                    if q_id:
                        seen_ids.add(q_id)
                    if not seen_ids or len(seen_ids) == 1:
                        asking_sample = v.get("askingMember")
                        logger.warning(
                            f"[UK Parliament] Questions first-record fields: {list(v.keys())} | "
                            f"askingMember type={type(asking_sample).__name__} value={asking_sample!r:.200} | "
                            f"askingMemberId={v.get('askingMemberId')!r} cache_size={len(self._member_cache)}"
                        )
                    q_text = v.get("questionText", v.get("text", ""))
                    answer = v.get("answerText", v.get("answer", ""))
                    combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                    asking = v.get("askingMember") or {}
                    member_id = str(v.get("askingMemberId") or v.get("memberId") or "")
                    cached = self._member_cache.get(member_id, {})
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": member_id,
                            "name": asking.get("name") or asking.get("listAs") or cached.get("name") or "",
                            "party": asking.get("party") or cached.get("party") or "",
                            "constituency": asking.get("memberFrom") or cached.get("constituency") or "",
                            "role": "MP",
                        },
                        date=v.get("tabledWhen", v.get("dateTabled", "")),
                        text=combined,
                        title=v.get("heading", v.get("subject", "")),
                        metadata={
                            "question_id": q_id,
                            "question_type": "written",
                            "answering_body": v.get("answeringBodyName", ""),
                            "answering_member": v.get("answeringMember", {}).get("name", "") if isinstance(v.get("answeringMember"), dict) else "",
                            "answer_date": v.get("dateAnswered", ""),
                            "is_withdrawn": v.get("isWithdrawn", False),
                            "answer_text": answer,
                        },
                        source_url=url,
                    ))
                    chunk_count += 1
                if len(items) < 100:
                    break
                skip += 100
            logger.info(f"[UK Parliament] Questions {chunk_start}–{chunk_end}: {chunk_count} records")
        logger.info(f"[UK Parliament] {len(records)} question records fetched total")
        return records

    # ------------------------------------------------------------------
    # Plenary business (spoken debate contributions + written statements)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None,
                               to_date: Optional[str] = None) -> List[Dict]:
        """Commons plenary business = spoken debate contributions + written statements.

        Spoken contributions are the bulk of plenary and the richest text for
        sentiment analysis; they come from the Hansard search API. Written
        ministerial statements come from the questions-statements API. Both are
        fetched and combined so neither is silently dropped.
        """
        if not self._member_cache:
            self.fetch_members()
        spoken = self._fetch_spoken_contributions(from_date, to_date)
        written = self._fetch_written_statements(from_date, to_date)
        logger.info(
            f"[UK Parliament] {len(spoken) + len(written)} plenary records fetched "
            f"({len(spoken)} spoken contributions + {len(written)} written statements)"
        )
        return spoken + written

    @staticmethod
    def _iter_date_chunks(start: str, end: str, days: int):
        """Yield (chunk_start, chunk_end) ISO date pairs covering [start, end] inclusive."""
        d0 = _datetime.strptime(start[:10], "%Y-%m-%d").date()
        d1 = _datetime.strptime(end[:10], "%Y-%m-%d").date()
        cur = d0
        while cur <= d1:
            chunk_end = min(cur + _timedelta(days=days - 1), d1)
            yield cur.isoformat(), chunk_end.isoformat()
            cur = chunk_end + _timedelta(days=1)

    def _fetch_spoken_contributions(self, from_date: Optional[str] = None,
                                    to_date: Optional[str] = None) -> List[Dict]:
        """Spoken Commons debate contributions from the Hansard search API.

        hansard-api.parliament.uk/search/contributions/Spoken.json returns one
        record per spoken contribution (a Member's speech or intervention in a
        debate) and honours startDate/endDate, so we walk the range in date
        chunks to stay under the search index's pagination depth cap.
        """
        url = f"{_HANSARD}/search/contributions/Spoken.json"
        today = to_date or _date.today().isoformat()
        start = from_date or "2015-01-01"   # match the questions pull's historical floor
        records: List[Dict] = []
        for chunk_start, chunk_end in self._iter_date_chunks(start, today, _HANSARD_CHUNK_DAYS):
            skip = 0
            chunk_count = 0
            while True:
                params: Dict = {
                    "queryParameters.house": "Commons",
                    "queryParameters.startDate": chunk_start,
                    "queryParameters.endDate": chunk_end,
                    "queryParameters.orderBy": "SittingDateAsc",
                    "queryParameters.take": 100,
                    "queryParameters.skip": skip,
                }
                resp = self._get(url, params=params, timeout=90)
                if not resp:
                    break
                data = resp.json()
                # Search API wraps hits in {"Results": [...]} (PascalCase).
                items = data.get("Results") or data.get("results") or []
                if not items:
                    break
                for entry in items:
                    item = entry.get("value", entry) if isinstance(entry, dict) else entry
                    # ContributionTextFull is the complete speech; ContributionText
                    # is a search snippet — prefer the full text when present.
                    text = (item.get("ContributionTextFull") or item.get("ContributionText")
                            or item.get("Value") or item.get("text") or "")
                    if not text or len(text.strip()) < 3:
                        continue
                    sitting = str(item.get("SittingDate") or item.get("sittingDate")
                                  or item.get("Date") or item.get("date") or "")[:10]
                    member_id = str(item.get("MemberId") or item.get("memberId") or "")
                    cached = self._member_cache.get(member_id, {})
                    name = (item.get("AttributedTo") or item.get("attributedTo")
                            or item.get("MemberName") or item.get("memberName")
                            or cached.get("name") or "")
                    records.append(self._make_record(
                        data_type="plenary_speech",
                        member={
                            "id": member_id,
                            "name": name,
                            "party": cached.get("party", ""),
                            "constituency": cached.get("constituency", ""),
                            "role": "MP",
                        },
                        date=sitting,
                        text=text,
                        title=(item.get("DebateSection") or item.get("Section")
                               or item.get("Title") or item.get("title") or ""),
                        metadata={
                            "contribution_id": str(item.get("ContributionExtId")
                                                   or item.get("Id") or item.get("id") or ""),
                            "debate_section": item.get("DebateSection", ""),
                            "debate_ext_id": item.get("DebateSectionExtId", ""),
                            "house": item.get("House", "Commons"),
                            "contribution_type": "spoken",
                        },
                        source_url=url,
                    ))
                    chunk_count += 1
                if len(items) < 100:
                    break
                skip += 100
                if skip >= _HANSARD_SKIP_CAP:
                    logger.warning(
                        f"[UK Parliament] Plenary: spoken contributions for "
                        f"{chunk_start}→{chunk_end} reached the {skip} pagination "
                        f"cap — some contributions in this window may be missing; "
                        f"reduce _HANSARD_CHUNK_DAYS if this recurs"
                    )
                    break
            if chunk_count:
                logger.info(f"[UK Parliament] Plenary: {chunk_count} spoken "
                            f"contributions {chunk_start}→{chunk_end}")
        return records

    def _fetch_written_statements(self, from_date: Optional[str] = None,
                                  to_date: Optional[str] = None) -> List[Dict]:
        """Written ministerial statements from the questions-statements API.

        This endpoint ignores startDate/endDate and returns the full corpus
        newest-first, so we filter client-side and stop paginating once a whole
        page predates the requested window.
        """
        url = f"{_QUESTIONS}/writtenstatements/statements"
        records: List[Dict] = []
        params: Dict = {"take": 100, "skip": 0}
        if from_date:
            params["startDate"] = from_date
        if to_date:
            params["endDate"] = to_date
        skip = 0
        order_desc = None
        while True:
            params["skip"] = skip
            if skip % 1000 == 0 and skip > 0:
                logger.info(f"[UK Parliament] Plenary (written): {len(records)} so far...")
            resp = self._get(url, params=params, timeout=90)
            if not resp:
                break
            data = resp.json()
            if isinstance(data, list):
                raw_items = data
            else:
                raw_items = data.get("results", data.get("statements", data.get("items", [])))
            items = [e.get("value", e) if isinstance(e, dict) else e for e in raw_items]
            if not items:
                if skip == 0:
                    keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
                    logger.warning(f"[UK Parliament] Written-statements endpoint {url} "
                                   f"returned no items (keys: {keys})")
                break
            page_dates = []
            for item in items:
                item_date = str(item.get("Date", item.get("date", item.get("dateMade", ""))))[:10]
                if item_date:
                    page_dates.append(item_date)
                if from_date and item_date and item_date < from_date:
                    continue
                text = item.get("Value", item.get("text", item.get("body",
                       item.get("StatementText", ""))))
                if not text:
                    continue
                member_obj = (item.get("member") or item.get("Member") or {})
                mid = str(item.get("MemberId") or item.get("memberId") or member_obj.get("id") or "")
                cached = self._member_cache.get(mid, {})
                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": mid,
                        "name": (item.get("AttributedTo") or item.get("attributedTo")
                                 or item.get("MemberName") or item.get("memberName")
                                 or member_obj.get("name") or item.get("nameDisplayAs")
                                 or cached.get("name") or ""),
                        "party": item.get("Party") or member_obj.get("party") or cached.get("party") or "",
                        "constituency": item.get("MemberFrom") or member_obj.get("memberFrom") or cached.get("constituency") or "",
                        "role": "MP",
                    },
                    date=item.get("Date", item.get("date", item.get("dateMade", ""))),
                    text=text,
                    title=item.get("Title", item.get("title", item.get("subject", ""))),
                    metadata={
                        "statement_id": str(item.get("Id", item.get("id", ""))),
                        "house": item.get("House", item.get("house", "Commons")),
                        "contribution_type": "written_statement",
                    },
                    source_url=url,
                ))
            if order_desc is None and len(page_dates) >= 2:
                order_desc = page_dates[0] >= page_dates[-1]
            if from_date and order_desc and page_dates and max(page_dates) < from_date:
                logger.info(f"[UK Parliament] Plenary (written): page at skip={skip} entirely "
                            f"predates {from_date} — stopping pagination early")
                break
            if len(items) < 100:
                break
            skip += 100
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None,
                                to_date: Optional[str] = None) -> List[Dict]:
        # Step 1: get the list of divisions
        div_url = f"{_VOTES}/divisions.json/search"
        params: Dict = {"take": 25, "skip": 0}
        if from_date:
            params["startDate"] = from_date
        if to_date:
            params["endDate"] = to_date

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
