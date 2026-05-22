"""
Welsh Parliament (Senedd) scraper.

The Senedd does not expose a structured public REST API.  Data is scraped from:
  - https://senedd.wales/          — member profiles, register of interests
  - https://record.senedd.wales/   — Record of Proceedings (plenary, votes)
"""
import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["welsh_parliament"]
_BASE = _CFG["api_base"]       # https://senedd.wales
_RECORD = _CFG["record_base"]  # https://record.senedd.wales

# Candidate paths tried in order for each resource type
_MEMBER_PATHS = [
    "/find-a-member-of-the-senedd/",
    "/en/find-a-member-of-the-senedd/",
    "/en/senedd-members/current-senedd-members/",
    "/en/senedd-members/current-members/",
    "/en/ms-aMs/Pages/MSsbyRegion.aspx",
]
_INTEREST_PATHS = [
    "/senedd-business/register-of-members-interests/",
    "/en/senedd-business/register-of-members-interests/",
    "/en/senedd-members/register-of-members-financial-interests/",
    "/en/bus-home/Pages/bus-register-of-members-interests.aspx",
]


class WelshParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("Welsh Parliament (Senedd)")

    def _html_get(self, url: str, params: Optional[Dict] = None) -> Optional[BeautifulSoup]:
        resp = self._get(url, params=params, accept="text/html,application/xhtml+xml")
        if not resp:
            return None
        return BeautifulSoup(resp.text, "lxml")

    def _try_paths(self, base: str, paths: List[str]) -> Optional[BeautifulSoup]:
        """Try each path until one returns a non-empty page."""
        for path in paths:
            soup = self._html_get(f"{base}{path}")
            if soup and soup.find("body"):
                return soup
        return None

    # ------------------------------------------------------------------
    # Members (MSs — Members of the Senedd)
    # ------------------------------------------------------------------

    def fetch_members(self) -> List[Dict]:
        members = self._scrape_members()
        logger.info(f"[Welsh Parliament] {len(members)} MSs fetched")
        return members

    def _scrape_members(self) -> List[Dict]:
        soup = self._try_paths(_BASE, _MEMBER_PATHS)
        if not soup:
            logger.warning("[Welsh Parliament] Could not fetch member listing page")
            return []

        members = []
        # Modern Senedd website uses article/card elements
        selectors = [
            "article.senedd-member",
            ".ms-member-card",
            ".member-card",
            "article.member",
            ".senedd-member",
            "li.member",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            # Fallback: any <article> or <li> that contains a name-like heading
            cards = [el for el in soup.select("article, li") if el.select_one("h2, h3")]

        for card in cards:
            name_el = card.select_one("h2, h3, h4, .member-name, .ms-name, [class*='name']")
            party_el = card.select_one(".party, .ms-party, .member-party, [class*='party']")
            const_el = card.select_one(".constituency, .region, [class*='constituency'], [class*='region']")
            link_el = card.select_one("a[href]")
            member_id = ""
            if link_el:
                href = link_el.get("href", "")
                m = re.search(r"/(\d+)", href)
                if m:
                    member_id = m.group(1)
            name = name_el.get_text(strip=True) if name_el else ""
            if not name:
                continue
            members.append({
                "id": member_id,
                "name": name,
                "party": party_el.get_text(strip=True) if party_el else "",
                "constituency": const_el.get_text(strip=True) if const_el else "",
                "role": "MS",
                "status": "current",
            })
        return members

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        soup = self._try_paths(_BASE, _INTEREST_PATHS)
        records = []
        if not soup:
            logger.warning("[Welsh Parliament] Could not fetch register of interests page")
            return records

        # The interests page groups entries by member
        for section in soup.select("section, .member-interests, .ms-interests, article"):
            name_el = section.select_one("h2, h3, .member-name")
            if not name_el:
                continue
            member_name = name_el.get_text(strip=True)
            member = next(
                (m for m in members if m["name"].lower() == member_name.lower()),
                {"id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"},
            )
            for item in section.select("li, .interest-item, p.interest"):
                text = item.get_text(strip=True)
                if len(text) < 5:
                    continue
                records.append(self._make_record(
                    data_type="register_of_interests",
                    member=member,
                    date="",
                    text=text,
                    title="",
                    source_url=f"{_BASE}{_INTEREST_PATHS[0]}",
                ))
        logger.info(f"[Welsh Parliament] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions — scraped from Record of Proceedings
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []
        for path in ["/en/Business/OralQuestions", "/en/Business/WrittenQuestions",
                     "/en/Business/Questions", "/en/business/oralquestions",
                     "/en/business/writtenquestions"]:
            soup = self._html_get(f"{_RECORD}{path}")
            if not soup:
                continue
            for link in soup.select("a[href]")[:100]:
                href = link.get("href", "")
                if not re.search(r"/\d{4}-\d{2}-\d{2}|/\d+", href):
                    continue
                full_url = href if href.startswith("http") else f"{_RECORD}{href}"
                detail = self._html_get(full_url)
                if not detail:
                    continue
                date_el = detail.select_one("time, .date, [datetime]")
                date_str = ""
                if date_el:
                    date_str = date_el.get("datetime", date_el.get_text(strip=True))
                if from_date and date_str and date_str[:10] < from_date:
                    continue
                for contrib in detail.select(".question, .written-question, .contribution"):
                    speaker_el = contrib.select_one(".speaker, .member-name, strong")
                    text_el = contrib.select_one(".text, p")
                    text = text_el.get_text(strip=True) if text_el else contrib.get_text(strip=True)
                    if len(text) < 10:
                        continue
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": "",
                            "name": speaker_el.get_text(strip=True) if speaker_el else "",
                            "party": "",
                            "constituency": "",
                            "role": "MS",
                        },
                        date=date_str,
                        text=text,
                        title="",
                        metadata={"question_type": "oral" if "Oral" in path else "written"},
                        source_url=full_url,
                    ))
            if records:
                break  # stop once we have data from one endpoint

        logger.info(f"[Welsh Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business — Record of Proceedings
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        plenary_url = None
        for path in ["/en/Business/Plenary", "/en/business/plenary", "/en/Plenary"]:
            soup = self._html_get(f"{_RECORD}{path}")
            if soup and soup.find("body"):
                plenary_url = f"{_RECORD}{path}"
                break
        if not plenary_url:
            logger.warning("[Welsh Parliament] Could not fetch plenary index")
            return []

        session_links = []
        for link in soup.select("a[href]"):
            href = link.get("href", "")
            if re.search(r"[Pp]lenary/.*(/\d{4}-\d{2}-\d{2}|/\d+)", href):
                full_url = href if href.startswith("http") else f"{_RECORD}{href}"
                session_links.append(full_url)
        session_links = list(dict.fromkeys(session_links))  # deduplicate, preserve order

        records = []
        for session_url in session_links[:50]:
            session_soup = self._html_get(session_url)
            if not session_soup:
                continue
            date_el = session_soup.select_one("time[datetime], .date, h1")
            session_date = ""
            if date_el:
                session_date = date_el.get("datetime", date_el.get_text(strip=True))
            if from_date and session_date and session_date[:10] < from_date:
                continue

            for contrib in session_soup.select(".contribution, .speech, [class*='contribution']"):
                speaker_el = contrib.select_one(".speaker, .member-name, strong")
                text_el = contrib.select_one(".text, p, .speech-text")
                text = text_el.get_text(strip=True) if text_el else contrib.get_text(strip=True)
                if len(text) < 10:
                    continue
                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": "",
                        "name": speaker_el.get_text(strip=True) if speaker_el else "",
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
    # Votes on division — Record of Proceedings
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        divisions_soup = None
        for path in ["/en/Business/Divisions", "/en/business/divisions", "/en/Divisions"]:
            divisions_soup = self._html_get(f"{_RECORD}{path}")
            if divisions_soup and divisions_soup.find("body"):
                break
        soup = divisions_soup
        if not soup:
            logger.warning("[Welsh Parliament] Could not fetch divisions index")
            return []

        records = []
        for row in soup.select("table tr, .division-row, li.division"):
            cols = row.select("td, .col")
            title_el = row.select_one("td:first-child, .division-title, a")
            date_el = row.select_one("td:nth-child(2), time, .date")
            link_el = row.select_one("a[href]")
            if not link_el:
                continue
            title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
            div_date = date_el.get_text(strip=True) if date_el else ""
            if from_date and div_date and div_date[:10] < from_date:
                continue
            detail_href = link_el["href"]
            detail_url = detail_href if detail_href.startswith("http") else f"{_RECORD}{detail_href}"
            detail_soup = self._html_get(detail_url)
            if not detail_soup:
                continue

            # Parse voter lists — try multiple CSS selector patterns
            vote_sections = {
                "aye": [".ayes li", ".for li", "[class*='aye'] li", "[class*='for'] li"],
                "no": [".noes li", ".against li", "[class*='no'] li", "[class*='against'] li"],
                "abstain": [".abstentions li", ".abstain li", "[class*='abstain'] li"],
            }
            for direction, selectors in vote_sections.items():
                voters = []
                for sel in selectors:
                    voters = detail_soup.select(sel)
                    if voters:
                        break
                for voter_el in voters:
                    name = voter_el.get_text(strip=True)
                    if not name:
                        continue
                    records.append(self._make_record(
                        data_type="vote",
                        member={
                            "id": "",
                            "name": name,
                            "party": "",
                            "constituency": "",
                            "role": "MS",
                        },
                        date=div_date,
                        text=f"Voted {direction} on: {title}",
                        title=title,
                        metadata={
                            "vote_direction": direction,
                            "division_result": "",
                            "source_url": detail_url,
                        },
                        source_url=detail_url,
                    ))

        logger.info(f"[Welsh Parliament] {len(records)} vote records fetched")
        return records
