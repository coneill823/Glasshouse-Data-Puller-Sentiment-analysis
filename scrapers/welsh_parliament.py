"""
Welsh Parliament (Senedd) scraper.

Data sources:
  - https://senedd.wales/                    — member profiles, register of interests
  - https://record.senedd.wales/             — Record of Proceedings SPA (plenary, votes)
  - https://record.senedd.wales/api/         — Record of Proceedings REST API
  - https://business.senedd.wales/           — Senedd Business SPA (questions)
  - https://business.senedd.wales/api/       — Senedd Business REST API
  - https://senedd.wales/api/                — Senedd public REST API

record.senedd.wales and business.senedd.wales are both JavaScript SPAs; the
server-side rendered HTML is just a navigation shell.  Actual data is fetched
via their REST APIs, which we probe at /api/ with common path patterns.
All requests use a browser User-Agent; the Senedd CDN blocks generic bot UAs.
"""
import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["welsh_parliament"]
_BASE = _CFG["api_base"]        # https://senedd.wales
_RECORD = _CFG["record_base"]   # https://record.senedd.wales
_BUSINESS = "https://business.senedd.wales"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Current (2024-2026) senedd.wales URL paths
_MEMBER_PATHS = [
    "/find-a-member-of-the-senedd/",
    "/en/find-a-member-of-the-senedd/",
    "/en/senedd-members/current-senedd-members/",
    "/en/senedd-members/current-members/",
]
_INTEREST_PATHS = [
    "/senedd-business/register-of-members-interests/",
    "/en/senedd-business/register-of-members-interests/",
    "/en/senedd-members/register-of-members-financial-interests/",
]

# record.senedd.wales paths (capitalisation varies by version)
_PLENARY_PATHS = [
    "/en/plenary/",
    "/en/plenary/plenary-sessions/",
    "/en/plenary/plenary-session/",
    "/en/plenary/sessions/",
    "/en/Plenary/Plenary-Sessions/",
    "/en/business/plenary/",
    "/en/Business/Plenary/",
    "/en/Business/Plenary",
    "/en/business/",
    "/en/Business/",
]
_DIVISION_PATHS = [
    "/en/plenary/divisions/",
    "/en/business/divisions/",
    "/en/Business/Divisions",
    "/en/Plenary/Divisions",
]
_QUESTION_PATHS = [
    "/en/written-questions/",
    "/en/oral-questions/",
    "/en/business/written-questions/",
    "/en/business/oral-questions/",
    "/en/Business/OralQuestions",
    "/en/Business/WrittenQuestions",
    "/en/business/oral-questions",
    "/en/business/written-questions",
]

# senedd.wales main site question paths
_SENEDD_QUESTION_PATHS = [
    "/senedd-business/written-questions/",
    "/senedd-business/oral-questions/",
    "/en/senedd-business/written-questions/",
    "/en/senedd-business/oral-questions/",
    "/senedd-business/questions/",
]


class WelshParliamentScraper(BaseScraper):
    def __init__(self):
        super().__init__("Welsh Parliament (Senedd)")

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    def _api_get(self, url: str, params: Optional[Dict] = None):
        """Fetch a JSON API endpoint with browser UA.  Returns the parsed JSON or None."""
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json, */*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        resp = self._get(url, params=params)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp:
            return None
        ct = resp.headers.get("Content-Type", "")
        if "json" not in ct and not resp.text.strip().startswith(("[", "{")):
            return None
        try:
            return resp.json()
        except Exception:
            return None

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

    def _try_paths(self, base: str, paths: List[str]) -> Optional[BeautifulSoup]:
        """Try each path in order; return the first soup whose body has real content."""
        for path in paths:
            url = f"{base}{path}"
            soup = self._html_get(url)
            if soup and soup.find("body") and len(soup.get_text(strip=True)) > 200:
                logger.info(f"[Welsh Parliament] Loaded: {url}")
                return soup
            elif soup:
                logger.warning(f"[Welsh Parliament] Page loaded but looks empty/error: {url}")
            else:
                logger.warning(f"[Welsh Parliament] Failed to load: {url}")
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
            logger.warning("[Welsh Parliament] Could not load any member listing page — check log for failed URLs")
            return []

        members = []

        # senedd.wales uses WordPress with various card/block patterns.
        # Try progressively broader selectors.
        card_selectors = [
            "article.member-card",
            "article.senedd-member",
            ".member-card",
            ".ms-card",
            "[class*='member-card']",
            "[class*='memberCard']",
            "article.wp-block-post",
            "li.wp-block-post",
            "article",
        ]
        cards = []
        for sel in card_selectors:
            cards = [c for c in soup.select(sel) if c.get_text(strip=True)]
            if cards:
                logger.debug(f"[Welsh Parliament] Member cards found with selector: {sel!r} ({len(cards)} cards)")
                break

        if not cards:
            # Last resort: any element containing a name-like heading
            cards = [el for el in soup.select("li, div") if el.select_one("h2, h3, h4")]
            logger.debug(f"[Welsh Parliament] Fallback card extraction: {len(cards)} candidates")

        for card in cards:
            name_el = (
                card.select_one("h2, h3, h4")
                or card.select_one("[class*='name'], [class*='Name']")
                or card.select_one("strong, b")
            )
            party_el = card.select_one("[class*='party'], [class*='Party']")
            const_el = card.select_one(
                "[class*='constituency'], [class*='region'], [class*='Constituency'], [class*='Region']"
            )
            link_el = card.select_one("a[href]")

            member_id = ""
            if link_el:
                href = link_el.get("href", "")
                m = re.search(r"/(\d+)", href)
                if m:
                    member_id = m.group(1)
                else:
                    slug = re.search(r"/([a-z0-9-]+)/?$", href, re.I)
                    if slug:
                        member_id = slug.group(1)

            name = name_el.get_text(strip=True) if name_el else ""
            if not name or len(name) < 3:
                continue

            members.append({
                "id": member_id,
                "name": name,
                "party": party_el.get_text(strip=True) if party_el else "",
                "constituency": const_el.get_text(strip=True) if const_el else "",
                "role": "MS",
                "status": "current",
            })

        if not members:
            # Log a snippet of the page HTML to help diagnose the selector
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
            logger.warning(f"[Welsh Parliament] 0 members parsed — page snippet: {snippet}")

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
            logger.warning("[Welsh Parliament] Could not load register of interests page")
            return records

        # The interests page may link to a PDF or list interests inline.
        # Detect PDF link and warn; otherwise parse inline HTML.
        pdf_links = soup.select("a[href$='.pdf'], a[href*='/media/']")
        if pdf_links:
            pdf_url = pdf_links[0].get("href", "")
            logger.warning(
                f"[Welsh Parliament] Register of interests appears to be a PDF — "
                f"HTML parsing skipped. PDF: {pdf_url}"
            )
            return records

        # Try to find per-member interest sections
        section_selectors = [
            "section.member-interests",
            "[class*='member-interest']",
            "article",
            "section",
        ]
        sections = []
        for sel in section_selectors:
            sections = [s for s in soup.select(sel) if s.select_one("h2, h3, h4")]
            if sections:
                break

        for section in sections:
            name_el = section.select_one("h2, h3, h4")
            if not name_el:
                continue
            member_name = name_el.get_text(strip=True)
            member = next(
                (m for m in members if m["name"].lower() == member_name.lower()),
                {"id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"},
            )
            for item in section.select("li, p"):
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

        if not records:
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
            logger.warning(f"[Welsh Parliament] 0 interest records parsed — page snippet: {snippet}")

        logger.info(f"[Welsh Parliament] {len(records)} interest records fetched")
        return records

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    # Known REST API endpoint patterns for Senedd questions.
    # Both sites are React SPAs; the underlying APIs serve the actual data.
    _QUESTION_API_CANDIDATES = [
        f"{_RECORD}/api/questions",
        f"{_RECORD}/api/written-questions",
        f"{_RECORD}/api/oral-questions",
        f"{_BUSINESS}/api/questions",
        f"{_BUSINESS}/api/written-questions",
        f"{_BUSINESS}/api/oral-questions",
        f"{_BUSINESS}/api/businessquestions",
        "https://senedd.wales/api/questions",
        "https://senedd.wales/api/written-questions",
        "https://senedd.wales/api/oral-questions",
    ]

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = []

        # 1. Try REST API endpoints first (SPAs load data from APIs, not HTML)
        for api_url in self._QUESTION_API_CANDIDATES:
            params = {}
            if from_date:
                params["startDate"] = from_date
            data = self._api_get(api_url, params=params if params else None)
            if not data:
                continue
            items = data if isinstance(data, list) else data.get("items", data.get("results", data.get("questions", [])))
            if not items:
                logger.warning(f"[Welsh Parliament] Questions API {api_url} responded but returned no items (keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__})")
                continue
            logger.info(f"[Welsh Parliament] Questions API: {len(items)} items from {api_url}")
            for item in items:
                q_text = item.get("questionText", item.get("text", item.get("body", "")))
                answer = item.get("answerText", item.get("answer", ""))
                combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                if not combined:
                    continue
                records.append(self._make_record(
                    data_type="question",
                    member={
                        "id": str(item.get("memberId", item.get("askingMemberId", ""))),
                        "name": item.get("memberName", item.get("askingMember", {}).get("name", "") if isinstance(item.get("askingMember"), dict) else ""),
                        "party": item.get("party", ""),
                        "constituency": item.get("constituency", item.get("memberFrom", "")),
                        "role": "MS",
                    },
                    date=item.get("dateTabled", item.get("date", "")),
                    text=combined,
                    title=item.get("subject", item.get("title", "")),
                    metadata={"question_type": item.get("questionType", "written")},
                    source_url=api_url,
                ))
            if records:
                logger.info(f"[Welsh Parliament] {len(records)} question records fetched via API")
                return records

        # 2. Fall back to HTML scraping
        # Regex for links that are individual question items (not just category navigation).
        # Requires a date component OR a numeric ID that looks like a specific item.
        _ITEM_LINK_RE = re.compile(
            r"/\d{4}-\d{2}-\d{2}|/\d{4}/\d{2}|/\d{5,}|"
            r"question[s]?/\w|oral[s]?/\d|written[s]?/\d",
            re.I,
        )

        search_targets = [
            # (base, paths, question_type)
            (_RECORD, _QUESTION_PATHS, None),
            (_BASE, _SENEDD_QUESTION_PATHS, None),
            (_BUSINESS, ["/en/written-questions/", "/en/oral-questions/",
                         "/written-questions/", "/oral-questions/"], None),
        ]

        for base, paths, _ in search_targets:
            for path in paths:
                url = f"{base}{path}"
                soup = self._html_get(url)
                if not soup:
                    continue

                links_found = []
                for link in soup.select("a[href]"):
                    href = link.get("href", "")
                    if not href or not (href.startswith("/") or href.startswith("http")):
                        continue
                    if _ITEM_LINK_RE.search(href):
                        links_found.append(href)

                if not links_found:
                    body = soup.find("body")
                    snippet = body.get_text(separator=" ", strip=True)[:600] if body else ""
                    logger.warning(
                        f"[Welsh Parliament] Questions: no item links found at {url} — snippet: {snippet}"
                    )
                    continue

                logger.info(f"[Welsh Parliament] Questions: found {len(links_found)} item links at {url}")
                for href in links_found[:100]:
                    full_url = href if href.startswith("http") else f"{base}{href}"
                    detail = self._html_get(full_url)
                    if not detail:
                        continue
                    date_el = detail.select_one("time[datetime], time, .date, [class*='date']")
                    date_str = ""
                    if date_el:
                        date_str = date_el.get("datetime", date_el.get_text(strip=True))
                    if from_date and date_str and date_str[:10] < from_date:
                        continue

                    item_count_before = len(records)
                    for contrib in detail.select(
                        ".question, .written-question, .contribution, .item, "
                        ".q-item, .answer, [class*='question'], article, p"
                    ):
                        speaker_el = contrib.select_one(".speaker, .member-name, strong, b")
                        text_el = contrib.select_one(".text, .body, p")
                        text = text_el.get_text(strip=True) if text_el else contrib.get_text(strip=True)
                        if len(text) < 10:
                            continue
                        q_type = "oral" if "oral" in path.lower() else "written"
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
                            metadata={"question_type": q_type},
                            source_url=full_url,
                        ))
                    if len(records) == item_count_before:
                        body = detail.find("body")
                        snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
                        logger.warning(
                            f"[Welsh Parliament] 0 items from question page {full_url} — snippet: {snippet}"
                        )

                if records:
                    logger.info(f"[Welsh Parliament] {len(records)} question records fetched")
                    return records

        logger.info(f"[Welsh Parliament] {len(records)} question records fetched")
        return records

    # ------------------------------------------------------------------
    # Plenary business — Record of Proceedings
    # ------------------------------------------------------------------

    # Known REST API endpoint patterns for plenary proceedings
    _PLENARY_API_CANDIDATES = [
        f"{_RECORD}/api/plenary/sessions",
        f"{_RECORD}/api/plenary",
        f"{_RECORD}/api/proceedings",
        f"{_RECORD}/api/agenda",
        f"{_RECORD}/api/contributions",
        f"{_RECORD}/api/meetings",
        "https://senedd.wales/api/plenary",
        "https://senedd.wales/api/proceedings",
    ]

    # Links that indicate an individual plenary session (date-based or ID-based).
    # Matches 4+ digit IDs, date-based paths, or standard plenary URL patterns.
    _SESSION_LINK_RE = re.compile(
        r"\d{4}-\d{2}-\d{2}|/\d{4}/\d{2}|/\d{4,}|"
        r"[Pp]lenary/\d|[Ss]ession/\d|[Ss]itting/\d|[Mm]eeting/\d",
    )

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        # 1. Try REST API endpoints (SPAs load data from APIs, not HTML)
        for api_url in self._PLENARY_API_CANDIDATES:
            params = {}
            if from_date:
                params["startDate"] = from_date
            data = self._api_get(api_url, params=params if params else None)
            if not data:
                continue
            sessions = data if isinstance(data, list) else data.get("sessions", data.get("items", data.get("results", [])))
            if not sessions:
                logger.warning(f"[Welsh Parliament] Plenary API {api_url} responded but no sessions (keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__})")
                continue
            logger.info(f"[Welsh Parliament] Plenary API: {len(sessions)} sessions from {api_url}")
            records = []
            for session in sessions:
                session_date = session.get("date", session.get("sittingDate", ""))
                contributions = session.get("contributions", session.get("speeches", session.get("items", [])))
                for contrib in contributions:
                    text = contrib.get("text", contrib.get("body", contrib.get("speech", "")))
                    if not text or len(text) < 10:
                        continue
                    records.append(self._make_record(
                        data_type="plenary_speech",
                        member={
                            "id": str(contrib.get("memberId", "")),
                            "name": contrib.get("memberName", contrib.get("speaker", "")),
                            "party": contrib.get("party", ""),
                            "constituency": contrib.get("constituency", ""),
                            "role": "MS",
                        },
                        date=session_date,
                        text=text,
                        title=contrib.get("subject", contrib.get("title", "")),
                        source_url=api_url,
                    ))
            if records:
                logger.info(f"[Welsh Parliament] {len(records)} plenary records fetched via API")
                return records

        # 2. Try each HTML path individually; stop at the first one that contains session links.
        # record.senedd.wales is a SPA — most path variants return a nav-only shell with no
        # content links. Only paths that are server-side rendered include session-link rows.
        session_links = []
        for path in _PLENARY_PATHS:
            url = f"{_RECORD}{path}"
            soup = self._html_get(url)
            if not soup:
                logger.warning(f"[Welsh Parliament] Plenary: could not load {url}")
                continue
            found = []
            all_hrefs = []
            for link in soup.select("a[href]"):
                href = link.get("href", "")
                if not href or not (href.startswith("/") or href.startswith("http")):
                    continue
                all_hrefs.append(href)
                if self._SESSION_LINK_RE.search(href):
                    full_url = href if href.startswith("http") else f"{_RECORD}{href}"
                    found.append(full_url)
            found = list(dict.fromkeys(found))
            if found:
                session_links = found
                logger.info(f"[Welsh Parliament] Plenary: found {len(session_links)} session links at {url}")
                break
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:400] if body else ""
            sample_hrefs = all_hrefs[:10]
            logger.warning(f"[Welsh Parliament] Plenary: no session links at {url} — sample hrefs: {sample_hrefs} — snippet: {snippet}")

        if not session_links:
            logger.warning("[Welsh Parliament] No plenary session links found — all paths exhausted")
            return []

        records = []
        for session_url in session_links[:50]:
            session_soup = self._html_get(session_url)
            if not session_soup:
                continue

            date_el = session_soup.select_one("time[datetime], time, .date, h1, [class*='date']")
            session_date = ""
            if date_el:
                session_date = date_el.get("datetime", date_el.get_text(strip=True))
            if from_date and session_date and session_date[:10] < from_date:
                continue

            contrib_selectors = [
                ".contribution", ".speech", "[class*='contribution']",
                "[class*='speech']", ".item", "tr.speech",
            ]
            contribs = []
            for sel in contrib_selectors:
                contribs = session_soup.select(sel)
                if contribs:
                    break

            for contrib in contribs:
                speaker_el = (
                    contrib.select_one(".speaker, .member-name, [class*='speaker'], [class*='member']")
                    or contrib.select_one("strong, b")
                )
                text_el = contrib.select_one(".text, p, .speech-text, [class*='text']")
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
        soup = self._try_paths(_RECORD, _DIVISION_PATHS)
        if not soup:
            logger.warning("[Welsh Parliament] Could not load divisions index from record.senedd.wales")
            return []

        records = []
        row_selectors = ["table tr", ".division-row", "li.division", "article.division", "li"]
        rows = []
        for sel in row_selectors:
            rows = soup.select(sel)
            if rows:
                break

        if not rows:
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
            logger.warning(f"[Welsh Parliament] No division rows found — page snippet: {snippet}")
            return []

        logger.info(f"[Welsh Parliament] Divisions: found {len(rows)} rows to check")
        # Log first few division hrefs so we can see the URL pattern
        sample_div_hrefs = [r.select_one("a[href]")["href"] for r in rows[:5] if r.select_one("a[href]")]
        logger.info(f"[Welsh Parliament] Sample division hrefs: {sample_div_hrefs}")
        for row in rows:
            link_el = row.select_one("a[href]")
            if not link_el:
                continue
            title_el = row.select_one("td:first-child, .title, h2, h3") or link_el
            date_el = row.select_one("td:nth-child(2), time, .date, [class*='date']")
            title = title_el.get_text(strip=True)
            div_date = date_el.get_text(strip=True) if date_el else ""
            if from_date and div_date and div_date[:10] < from_date:
                continue

            detail_href = link_el["href"]
            # Skip non-HTTP links (tel:, mailto:, javascript:, etc.)
            if not detail_href or not (detail_href.startswith("/") or detail_href.startswith("http")):
                continue
            detail_url = detail_href if detail_href.startswith("http") else f"{_RECORD}{detail_href}"
            detail_soup = self._html_get(detail_url)
            if not detail_soup:
                continue

            vote_sections = {
                "aye": [
                    ".ayes li", ".for li", "[class*='aye'] li", "[class*='for'] li",
                    "[class*='Aye'] li", "[class*='For'] li",
                ],
                "no": [
                    ".noes li", ".against li", "[class*='no'] li", "[class*='against'] li",
                    "[class*='No'] li", "[class*='Against'] li",
                ],
                "abstain": [
                    ".abstentions li", ".abstain li", "[class*='abstain'] li",
                    "[class*='Abstain'] li",
                ],
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
                        metadata={"vote_direction": direction, "division_result": ""},
                        source_url=detail_url,
                    ))

        logger.info(f"[Welsh Parliament] {len(records)} vote records fetched")
        return records
