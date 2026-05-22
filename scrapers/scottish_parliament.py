"""
Scottish Parliament scraper.

Members are fetched from the public OData API at https://data.parliament.scot/api.
All other entity endpoints on that API return 404; interests, questions, plenary,
and votes are scraped from https://www.parliament.scot with a browser User-Agent.
"""
import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["scottish_parliament"]
_API = _CFG["api_base"]          # https://data.parliament.scot/api
_WEB = "https://www.parliament.scot"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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
            if isinstance(data, list):
                items = data
            else:
                items = data.get("value", [])
            if not items:
                break
            all_results.extend(items)
            if len(items) < top:
                break
            skip += top
        return all_results

    def _odata_probe(self, endpoint: str) -> str:
        """Return HTTP status code (as string) for a single probe request, for logging."""
        import requests as _req
        url = f"{_API}/{endpoint}"
        self._rate_limit()
        try:
            r = self.session.get(url, params={"$format": "json", "$top": 1}, timeout=15)
            return str(r.status_code)
        except Exception as e:
            return f"ERR({e})"

    def _odata_try(self, candidates: List[str], filters: Optional[str] = None) -> tuple:
        """Try each candidate endpoint name until one returns data. Returns (data, endpoint_name).
        Logs HTTP status for every candidate so failures appear in the run log."""
        for name in candidates:
            rows = self._odata_get(name, filters=filters)
            if rows:
                logger.info(f"[Scottish Parliament] Endpoint worked: {name} → {len(rows)} rows")
                return rows, name
            status = self._odata_probe(name)
            logger.warning(f"[Scottish Parliament] Endpoint {name!r} → HTTP {status} / 0 rows")
        logger.warning(f"[Scottish Parliament] All candidates exhausted: {candidates}")
        return [], candidates[0]

    # ------------------------------------------------------------------
    # HTML helper — uses browser UA so parliament.scot doesn't block us
    # ------------------------------------------------------------------

    def _html_get(self, url: str, params: Optional[Dict] = None) -> Optional[BeautifulSoup]:
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        resp = self._get(url, params=params)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp:
            return None
        return BeautifulSoup(resp.text, "lxml")

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
    # Register of interests — scraped from parliament.scot
    # (data.parliament.scot/api does not expose this entity publicly)
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        # URL structure changes between sessions; try several candidates
        interest_candidates = [
            f"{_WEB}/msps/members-interests/",
            f"{_WEB}/msps/members-interests",
            f"{_WEB}/msps/members-interests/register-of-interests",
            f"{_WEB}/msps/members-interests/register-of-interests/",
            f"{_WEB}/msps/register-of-interests",
            f"{_WEB}/msps/",
        ]
        soup = None
        url = ""
        for candidate in interest_candidates:
            resp_soup = self._html_get(candidate)
            if resp_soup:
                soup = resp_soup
                url = candidate
                logger.info(f"[Scottish Parliament] Loaded interests page: {candidate}")
                break
            logger.warning(f"[Scottish Parliament] Could not load interests page: {candidate}")
        records = []
        if not soup:
            logger.warning("[Scottish Parliament] All interest page candidates failed")
            return records

        member_lookup = {m["name"].lower(): m for m in members}

        # The page lists each MSP followed by their categories and interests
        for section in soup.select("details, .member-interests, article, section"):
            name_el = section.select_one("summary, h2, h3, h4, .msp-name, [class*='name']")
            if not name_el:
                continue
            member_name = name_el.get_text(strip=True)
            member = member_lookup.get(member_name.lower(), {
                "id": "", "name": member_name, "party": "",
                "constituency": "", "role": "MSP",
            })
            for item in section.select("li, p, td"):
                text = item.get_text(strip=True)
                if len(text) < 5:
                    continue
                records.append(self._make_record(
                    data_type="register_of_interests",
                    member=member,
                    date="",
                    text=text,
                    title="",
                    source_url=url,
                ))

        if not records:
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:600] if body else ""
            logger.warning(f"[Scottish Parliament] 0 interest records parsed from {url} — snippet: {snippet}")
        logger.info(f"[Scottish Parliament] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions — scraped from parliament.scot
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        for path in [
            "/chamber-and-committees/questions-and-answers/question-search",
            "/chamber-and-committees/questions-and-answers",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)
            if not soup:
                continue

            # Log what we find so we can diagnose selector issues
            links = [a["href"] for a in soup.select("a[href]")
                     if a.get("href", "").startswith(("/", "http"))
                     and re.search(r"/question|/answer|\d{4}-\d{2}-\d{2}|/\d+", a.get("href", ""), re.I)]

            if not links:
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
                logger.warning(f"[Scottish Parliament] No question links at {url} — snippet: {snippet}")
                continue

            logger.info(f"[Scottish Parliament] Found {len(links)} question links at {url}")
            page_records_before = len(records)
            for href in links[:200]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                detail = self._html_get(full_url)
                if not detail:
                    continue
                date_el = detail.select_one("time[datetime], time, .date, [class*='date']")
                date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
                if from_date and date_str and date_str[:10] < from_date:
                    continue
                item_count_before = len(records)
                for contrib in detail.select(".question, .answer, .contribution, .item, article, .q-text, .a-text, p"):
                    text = contrib.get_text(strip=True)
                    if len(text) < 10:
                        continue
                    speaker_el = contrib.select_one(".speaker, .msp-name, strong, b, h3")
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": "", "name": speaker_el.get_text(strip=True) if speaker_el else "",
                            "party": "", "constituency": "", "role": "MSP",
                        },
                        date=date_str,
                        text=text,
                        title="",
                        source_url=full_url,
                    ))
                if len(records) == item_count_before:
                    body = detail.find("body")
                    snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
                    logger.warning(f"[Scottish Parliament] 0 items from question page {full_url} — snippet: {snippet}")
            if len(records) > page_records_before:
                break

        logger.info(f"[Scottish Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business — Official Report from parliament.scot
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        for path in [
            "/chamber-and-committees/official-report/what-was-said-in-parliament",
            "/chamber-and-committees/official-report",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)
            if not soup:
                continue

            links = [a["href"] for a in soup.select("a[href]")
                     if a.get("href", "").startswith(("/", "http"))
                     and re.search(r"\d{4}-\d{2}-\d{2}|/official-report/|/or-\d", a.get("href", ""), re.I)]

            if not links:
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
                logger.warning(f"[Scottish Parliament] No Official Report links at {url} — snippet: {snippet}")
                continue

            logger.info(f"[Scottish Parliament] Found {len(links)} Official Report links")
            for href in links[:50]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                detail = self._html_get(full_url)
                if not detail:
                    continue
                date_el = detail.select_one("time[datetime], time, .date, h1")
                date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
                if from_date and date_str and date_str[:10] < from_date:
                    continue
                for contrib in detail.select(".contribution, .speech, [class*='contribution'], tr"):
                    speaker_el = contrib.select_one(".speaker, .msp-name, strong, b, td:first-child")
                    text_el = contrib.select_one(".text, p, td:last-child")
                    text = text_el.get_text(strip=True) if text_el else contrib.get_text(strip=True)
                    if len(text) < 10:
                        continue
                    records.append(self._make_record(
                        data_type="plenary_speech",
                        member={
                            "id": "", "name": speaker_el.get_text(strip=True) if speaker_el else "",
                            "party": "", "constituency": "", "role": "MSP",
                        },
                        date=date_str,
                        text=text,
                        title="",
                        source_url=full_url,
                    ))
            if records:
                break

        logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        filters = None
        if from_date:
            filters = f"DivisionDate ge datetime'{from_date}'"
        rows, _ = self._odata_try([
            "Votes", "VoteResults", "DivisionVotes", "MemberVotes",
            "Divisions", "VotedFor", "VotingData", "VoteRecords",
            "MSPVotes", "DivisionResults", "DivisionVote", "MemberVoting",
        ], filters=filters)

        if rows:
            # OData data found — use it
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

        # Fallback: scrape votes/divisions from parliament.scot
        records = []
        for path in [
            "/chamber-and-committees/votes-and-divisions/search",
            "/chamber-and-committees/votes-and-divisions",
            "/chamber-and-committees/votes-and-divisions/",
            "/the-work-of-the-parliament/votes-and-divisions",
            "/parliamentarybusiness/voting/",
            "/msps/voting-behaviour",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)
            if not soup:
                continue

            links = [a["href"] for a in soup.select("a[href]")
                     if a.get("href", "").startswith(("/", "http"))
                     and re.search(r"/division|/vote|\d{4}-\d{2}-\d{2}|/\d+", a.get("href", ""), re.I)]

            if not links:
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:600] if body else ""
                logger.warning(f"[Scottish Parliament] No division links at {url} — snippet: {snippet}")
                continue

            logger.info(f"[Scottish Parliament] Found {len(links)} division links")
            for href in links[:200]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                detail = self._html_get(full_url)
                if not detail:
                    continue
                date_el = detail.select_one("time[datetime], time, .date, h1")
                date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
                if from_date and date_str and date_str[:10] < from_date:
                    continue
                title_el = detail.select_one("h1, h2, .title, .motion")
                div_title = title_el.get_text(strip=True) if title_el else ""
                for direction, sel_list in [
                    ("aye", [".ayes li", ".for li", "[class*='aye'] li", "[class*='for'] li"]),
                    ("no", [".noes li", ".against li", "[class*='no'] li", "[class*='against'] li"]),
                    ("abstain", [".abstentions li", ".abstain li", "[class*='abstain'] li"]),
                ]:
                    voters = []
                    for sel in sel_list:
                        voters = detail.select(sel)
                        if voters:
                            break
                    for voter_el in voters:
                        name = voter_el.get_text(strip=True)
                        if not name:
                            continue
                        records.append(self._make_record(
                            data_type="vote",
                            member={"id": "", "name": name, "party": "", "constituency": "", "role": "MSP"},
                            date=date_str,
                            text=f"Voted {direction} on: {div_title}",
                            title=div_title,
                            metadata={"vote_direction": direction, "division_result": ""},
                            source_url=full_url,
                        ))
            if records:
                break

        logger.info(f"[Scottish Parliament] {len(records)} vote records fetched")
        return records
