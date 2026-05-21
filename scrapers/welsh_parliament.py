"""
Welsh Parliament (Senedd) scraper.

The Senedd provides data through:
  - REST API:  https://senedd.wales/api/
  - OData API: https://business.senedd.wales/mgWebService.asmx (limited)
  - Record of Proceedings: https://record.assembly.wales (HTML)

Where structured API endpoints are unavailable, data is parsed from
the Record of Proceedings pages.
"""
import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["welsh_parliament"]
_API = _CFG["api_base"]         # https://senedd.wales
_RECORD = _CFG["record_base"]   # https://record.assembly.wales


class WelshParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("Welsh Parliament (Senedd)")

    def _html_get(self, url: str, params: Optional[Dict] = None) -> Optional[BeautifulSoup]:
        resp = self._get(url, params=params, accept="text/html,application/xhtml+xml")
        if not resp:
            return None
        return BeautifulSoup(resp.text, "lxml")

    # ------------------------------------------------------------------
    # Members (MSs — Members of the Senedd)
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        """Fetch current and historical MSs via the Senedd API."""
        url = f"{_API}/api/members"
        resp = self._get(url)
        members = []

        if resp:
            try:
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("value", data.get("members", []))
                for m in rows:
                    members.append({
                        "id": str(m.get("id", m.get("Id", m.get("PersonId", "")))),
                        "name": m.get("fullName", m.get("name", m.get("Name", ""))),
                        "party": m.get("party", m.get("Party", m.get("groupName", ""))),
                        "constituency": m.get("constituency", m.get("Constituency", m.get("region", ""))),
                        "role": "MS",
                        "status": m.get("isActive", m.get("IsCurrent", "")),
                    })
            except Exception as e:
                logger.warning(f"[Welsh Parliament] JSON member parse failed: {e}. Falling back to HTML.")

        if not members:
            members = self._fetch_members_from_html()

        logger.info(f"[Welsh Parliament] {len(members)} MSs fetched")
        return members

    def _fetch_members_from_html(self) -> List[Dict]:
        """Parse member list from Senedd website as fallback."""
        soup = self._html_get(f"{_API}/en/senedd-members/current-members/")
        if not soup:
            return []
        members = []
        for card in soup.select(".ms-member-card, .member-card, article.member"):
            name_el = card.select_one(".ms-name, .member-name, h3, h2")
            party_el = card.select_one(".ms-party, .member-party, .party")
            const_el = card.select_one(".ms-constituency, .member-constituency, .constituency")
            link_el = card.select_one("a[href]")
            member_id = ""
            if link_el:
                href = link_el.get("href", "")
                id_match = re.search(r"/(\d+)", href)
                if id_match:
                    member_id = id_match.group(1)
            members.append({
                "id": member_id,
                "name": name_el.get_text(strip=True) if name_el else "",
                "party": party_el.get_text(strip=True) if party_el else "",
                "constituency": const_el.get_text(strip=True) if const_el else "",
                "role": "MS",
                "status": "current",
            })
        return [m for m in members if m["name"]]

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        url = f"{_API}/api/members/interests"
        resp = self._get(url)
        records = []

        if resp:
            try:
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("value", data.get("interests", []))
                lookup = self._member_lookup(members)
                for item in rows:
                    pid = str(item.get("personId", item.get("memberId", "")))
                    member = lookup.get(pid, {
                        "id": pid,
                        "name": item.get("memberName", item.get("name", "")),
                        "party": "",
                        "constituency": "",
                        "role": "MS",
                    })
                    desc = item.get("description", item.get("interest", item.get("detail", "")))
                    if not desc:
                        continue
                    records.append(self._make_record(
                        data_type="register_of_interests",
                        member=member,
                        date=item.get("registeredDate", item.get("date", "")),
                        text=desc,
                        title=item.get("category", item.get("type", "")),
                        metadata={
                            "category": item.get("category", ""),
                            "interest_id": str(item.get("id", "")),
                        },
                        source_url=url,
                    ))
                logger.info(f"[Welsh Parliament] {len(records)} interest records fetched")
                return records
            except Exception as e:
                logger.warning(f"[Welsh Parliament] Interest API failed: {e}. Trying HTML.")

        records = self._fetch_interests_from_html(members)
        logger.info(f"[Welsh Parliament] {len(records)} interest records fetched (HTML)")
        return records

    def _fetch_interests_from_html(self, members: List[Dict]) -> List[Dict]:
        soup = self._html_get(f"{_API}/en/senedd-members/register-of-members-financial-interests/")
        if not soup:
            return []
        records = []
        for member_section in soup.select(".member-interests, .ms-interests, section.member"):
            name_el = member_section.select_one("h2, h3, .member-name")
            member_name = name_el.get_text(strip=True) if name_el else ""
            member = next((m for m in members if m["name"] == member_name), {
                "id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"
            })
            for interest_item in member_section.select("li, .interest-item"):
                text = interest_item.get_text(strip=True)
                if text:
                    records.append(self._make_record(
                        data_type="register_of_interests",
                        member=member,
                        date="",
                        text=text,
                        title="",
                        source_url=f"{_API}/en/senedd-members/register-of-members-financial-interests/",
                    ))
        return records

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_API}/api/questions"
        params = {"take": 100, "skip": 0}
        if from_date:
            params["dateFrom"] = from_date

        records = []
        skip = 0
        while True:
            params["skip"] = skip
            resp = self._get(url, params=params)
            if not resp:
                break
            try:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", data.get("questions", []))
                if not items:
                    break
                for q in items:
                    q_text = q.get("questionText", q.get("text", ""))
                    answer = q.get("answerText", q.get("answer", ""))
                    combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": str(q.get("askingMemberId", q.get("memberId", ""))),
                            "name": q.get("askingMemberName", q.get("memberName", "")),
                            "party": q.get("askingMemberParty", q.get("party", "")),
                            "constituency": q.get("askingMemberConstituency", q.get("constituency", "")),
                            "role": "MS",
                        },
                        date=q.get("date", q.get("questionDate", "")),
                        text=combined,
                        title=q.get("subject", q.get("title", "")),
                        metadata={
                            "question_id": str(q.get("id", q.get("questionId", ""))),
                            "question_type": q.get("questionType", "written"),
                            "answering_body": q.get("answeringBody", ""),
                            "answer_text": answer,
                        },
                        source_url=url,
                    ))
                if len(items) < 100:
                    break
                skip += 100
            except Exception as e:
                logger.warning(f"[Welsh Parliament] Question API failed: {e}")
                break

        logger.info(f"[Welsh Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business (Record of Proceedings)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch plenary contributions from the Record of Proceedings."""
        index_url = f"{_RECORD}/en/Business/Plenary"
        soup = self._html_get(index_url)
        if not soup:
            return []

        session_links = []
        for link in soup.select("a[href*='/Plenary/']"):
            href = link.get("href", "")
            if re.search(r"/\d{4}-\d{2}-\d{2}", href) or re.search(r"/\d+$", href):
                full_url = href if href.startswith("http") else f"{_RECORD}{href}"
                session_links.append(full_url)

        records = []
        for session_url in session_links[:50]:  # cap per run to avoid very long initial pulls
            session_soup = self._html_get(session_url)
            if not session_soup:
                continue
            date_el = session_soup.select_one("time, .date, h1")
            session_date = ""
            if date_el:
                session_date = date_el.get("datetime", date_el.get_text(strip=True))

            for contrib in session_soup.select(".contribution, .speech, .contribution-text"):
                speaker_el = contrib.select_one(".speaker, .member-name, strong")
                text_el = contrib.select_one(".text, p, .speech-text")
                speaker = speaker_el.get_text(strip=True) if speaker_el else ""
                text = text_el.get_text(strip=True) if text_el else contrib.get_text(strip=True)
                if not text or len(text) < 10:
                    continue
                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": "",
                        "name": speaker,
                        "party": "",
                        "constituency": "",
                        "role": "MS",
                    },
                    date=session_date,
                    text=text,
                    title="",
                    metadata={"session_url": session_url},
                    source_url=session_url,
                ))

        logger.info(f"[Welsh Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        url = f"{_API}/api/votes"
        params = {"take": 100, "skip": 0}
        if from_date:
            params["dateFrom"] = from_date

        records = []
        skip = 0
        while True:
            params["skip"] = skip
            resp = self._get(url, params=params)
            if not resp:
                break
            try:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", data.get("votes", []))
                if not items:
                    break
                for vote in items:
                    direction = vote.get("voteDirection", vote.get("vote", vote.get("type", ""))).lower()
                    div_title = vote.get("divisionTitle", vote.get("motionText", vote.get("title", "")))
                    records.append(self._make_record(
                        data_type="vote",
                        member={
                            "id": str(vote.get("memberId", vote.get("personId", ""))),
                            "name": vote.get("memberName", vote.get("name", "")),
                            "party": vote.get("party", vote.get("groupName", "")),
                            "constituency": vote.get("constituency", vote.get("region", "")),
                            "role": "MS",
                        },
                        date=vote.get("date", vote.get("divisionDate", "")),
                        text=f"Voted {direction} on: {div_title}",
                        title=div_title,
                        metadata={
                            "division_id": str(vote.get("divisionId", vote.get("id", ""))),
                            "vote_direction": direction,
                            "division_result": vote.get("result", ""),
                        },
                        source_url=url,
                    ))
                if len(items) < 100:
                    break
                skip += 100
            except Exception as e:
                logger.warning(f"[Welsh Parliament] Vote API failed: {e}")
                break

        if not records:
            records = self._fetch_votes_from_record(from_date)

        logger.info(f"[Welsh Parliament] {len(records)} vote records fetched")
        return records

    def _fetch_votes_from_record(self, from_date: Optional[str] = None) -> List[Dict]:
        """Parse division results from the Record of Proceedings as fallback."""
        soup = self._html_get(f"{_RECORD}/en/Business/Divisions")
        if not soup:
            return []
        records = []
        for div_row in soup.select("table tr, .division-row"):
            cols = div_row.select("td")
            if len(cols) < 2:
                continue
            title = cols[0].get_text(strip=True) if cols else ""
            date = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            link = div_row.select_one("a[href]")
            if link:
                detail_url = link["href"] if link["href"].startswith("http") else f"{_RECORD}{link['href']}"
                detail_soup = self._html_get(detail_url)
                if detail_soup:
                    for section, direction in [(".ayes, .for", "aye"), (".noes, .against", "no"), (".abstain", "abstain")]:
                        for voter_el in detail_soup.select(f"{section} li, {section} .member"):
                            name = voter_el.get_text(strip=True)
                            if name:
                                records.append(self._make_record(
                                    data_type="vote",
                                    member={"id": "", "name": name, "party": "", "constituency": "", "role": "MS"},
                                    date=date,
                                    text=f"Voted {direction} on: {title}",
                                    title=title,
                                    metadata={"vote_direction": direction, "division_result": ""},
                                    source_url=detail_url,
                                ))
        return records
