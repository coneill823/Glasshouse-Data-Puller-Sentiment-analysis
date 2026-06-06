"""
Welsh Parliament (Senedd) scraper.

Data sources:
  - https://senedd.wales/                    — member profiles, register of interests
  - https://record.assembly.wales/Search     — Record of Proceedings search (SSR, confirmed working)
  - https://record.senedd.wales/             — Record of Proceedings (same site, modern domain)
  - https://record.senedd.wales/XMLExport/   — XML transcript export by meetingID

record.assembly.wales and record.senedd.wales are the same site (assembly.wales
redirects to senedd.wales after the 2020 rename).  The /en/plenary/* sub-paths
are all broken (redirect to cofnod.senedd.cymru/Error/NotFound).  The /Search
endpoint is confirmed SSR and returns question/vote cards with member names.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["welsh_parliament"]
_BASE = _CFG["api_base"]        # https://senedd.wales
_RECORD = _CFG["record_base"]   # https://record.senedd.wales
_RECORD_ALT = "https://record.assembly.wales"  # old domain — redirects to _RECORD
_BUSINESS = "https://business.senedd.wales"

# Search page — SSR, confirmed returning question cards with member names + dates.
# record.assembly.wales is tried first because the user confirmed this URL; it
# redirects to record.senedd.wales so either domain works.
_SEARCH_URLS = [
    f"{_RECORD_ALT}/Search",
    f"{_RECORD}/Search",
    f"{_RECORD}/search",
    f"{_RECORD_ALT}/search",
]

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

# NOTE: ALL /en/plenary/* and /en/business/* paths on record.senedd.wales redirect
# to cofnod.senedd.cymru/Error/NotFound — they are confirmed broken (2026-06).
# The working paths are on senedd.wales (WordPress) and the /Search endpoint.
_PLENARY_PATHS: list = []   # No working record.senedd.wales plenary paths
_DIVISION_PATHS: list = []  # No working record.senedd.wales division paths
_QUESTION_PATHS: list = []  # Questions fetched via /Search instead

# senedd.wales main site question paths
_SENEDD_QUESTION_PATHS = [
    "/senedd-business/written-questions/",
    "/senedd-business/oral-questions/",
    "/en/senedd-business/written-questions/",
    "/en/senedd-business/oral-questions/",
    "/senedd-business/questions/",
]

# senedd.wales main site plenary paths (WordPress, SSR — distinct from record.senedd.wales SPA)
_SENEDD_PLENARY_PATHS = [
    "/senedd-business/plenary/",
    "/en/senedd-business/plenary/",
    "/senedd-business/chamber/",
    "/en/senedd-business/chamber/",
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
            snippet = resp.text.strip()[:150]
            logger.warning(f"[Welsh Parliament] API {url} returned HTML/non-JSON (200+shell) — snippet: {snippet!r}")
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

    def _try_wp_rest_members(self) -> List[Dict]:
        """Attempt to get MS data from the WordPress REST API.

        senedd.wales runs WordPress; custom post types for MSs are accessible via
        /wp-json/wp/v2/<post-type>?_embed&per_page=100
        """
        for post_type in ["ms", "aelod", "member", "senedd-member", "mlas", "ms-profile"]:
            for base in [_BASE, f"{_BASE}/en"]:
                url = f"{base}/wp-json/wp/v2/{post_type}"
                resp = self._api_get(url, params={"per_page": 100, "_embed": 1})
                if not resp or not isinstance(resp, list) or not resp:
                    continue
                if not resp[0].get("title"):
                    continue
                members = []
                for post in resp:
                    title = post.get("title", {})
                    name = title.get("rendered", "") if isinstance(title, dict) else str(title)
                    name = re.sub(r"<[^>]+>", "", name).strip()
                    if not name or len(name) < 3:
                        continue
                    # Try embedded terms for party / constituency
                    embedded = post.get("_embedded", {})
                    terms = embedded.get("wp:term", [])
                    party = ""
                    constituency = ""
                    for term_group in terms:
                        for term in (term_group if isinstance(term_group, list) else [term_group]):
                            taxonomy = term.get("taxonomy", "")
                            term_name = term.get("name", "")
                            if "party" in taxonomy.lower() or "group" in taxonomy.lower():
                                party = term_name
                            elif "constituency" in taxonomy.lower() or "region" in taxonomy.lower():
                                constituency = term_name
                    meta = post.get("meta", {}) if isinstance(post.get("meta"), dict) else {}
                    if not party:
                        party = meta.get("party", meta.get("political_party", ""))
                    if not constituency:
                        constituency = meta.get("constituency", meta.get("region", ""))
                    members.append({
                        "id": str(post.get("id", post.get("slug", ""))),
                        "name": name,
                        "party": party,
                        "constituency": constituency,
                        "role": "MS",
                        "status": "current",
                    })
                if members:
                    logger.warning(f"[Welsh Parliament] WP REST API {url}: {len(members)} MSs, sample={members[0]!r:.200}")
                    return members
        return []

    def _scrape_members(self) -> List[Dict]:
        soup = self._try_paths(_BASE, _MEMBER_PATHS)
        if not soup:
            logger.warning("[Welsh Parliament] Could not load any member listing page — check log for failed URLs")
            return []

        members = []

        # Primary approach: find member profile links and scrape each profile.
        # Try the WordPress REST API first (fastest, most reliable for party data).
        wp_members = self._try_wp_rest_members()
        if wp_members:
            logger.info(f"[Welsh Parliament] {len(wp_members)} MSs fetched via WordPress REST API")
            return wp_members

        # Fallback: scrape profile pages from the member listing
        # senedd.wales profile URLs match /find-a-member-of-the-senedd/{slug}/ or /senedd-members/{slug}/
        sample_hrefs = [a.get("href", "") for a in soup.select("a[href]")][:20]
        logger.warning(f"[Welsh Parliament] Sample hrefs on listing page: {sample_hrefs}")
        profile_links = list(dict.fromkeys(
            (a["href"] if a["href"].startswith("http") else f"{_BASE}{a['href']}")
            for a in soup.select("a[href]")
            if re.search(
                r"/(find-a-member-of-the-senedd|senedd-members|members|aelodau-senedd)/[a-z][a-z0-9-]+/?$",
                a.get("href", ""), re.I)
            and not re.search(r"/(category|tag|page|search|help|glossary|contact)", a.get("href", ""), re.I)
        ))
        logger.warning(f"[Welsh Parliament] Member profile links found: {len(profile_links)} — e.g. {profile_links[:3]}")

        if profile_links:
            for profile_url in profile_links[:80]:
                profile_soup = self._html_get(profile_url)
                if not profile_soup:
                    continue
                name_el = profile_soup.select_one("h1, .page-title, [class*='member-name']")
                name = name_el.get_text(strip=True) if name_el else ""
                if not name or len(name) < 3:
                    # Fallback: use slug as display name
                    slug_m = re.search(r"/find-a-member-of-the-senedd/([a-z0-9-]+)/?$", profile_url, re.I)
                    name = slug_m.group(1).replace("-", " ").title() if slug_m else ""
                party_el = (
                    profile_soup.select_one("[class*='party'], [class*='Party']")
                    or profile_soup.select_one("[class*='group'], [class*='Group']")
                    or profile_soup.select_one(".tag, .badge, [class*='tag'], [class*='badge']")
                    or profile_soup.select_one("span.wp-block-post-terms, .wp-block-post-terms")
                )
                party = party_el.get_text(strip=True) if party_el else ""
                const_el = profile_soup.select_one(
                    "[class*='constituency'], [class*='region'], [class*='Constituency'], [class*='Region']"
                )
                constituency = const_el.get_text(strip=True) if const_el else ""
                slug = re.search(r"/find-a-member-of-the-senedd/([a-z0-9-]+)/?$", profile_url, re.I)
                member_id = slug.group(1) if slug else ""
                if not hasattr(self, "_ms_profile_logged"):
                    self._ms_profile_logged = True
                    logger.warning(
                        f"[Welsh Parliament] First MS profile: name={name!r} party={party!r} "
                        f"const={constituency!r} id={member_id!r}"
                    )
                members.append({
                    "id": member_id,
                    "name": name,
                    "party": party,
                    "constituency": constituency,
                    "role": "MS",
                    "status": "current",
                })
            if members:
                logger.info(f"[Welsh Parliament] {len(members)} MSs scraped via profile pages")
                return members

        # Fallback: card-based extraction from the listing page
        card_selectors = [
            "article.member-card", "article.senedd-member", ".member-card", ".ms-card",
            "[class*='member-card']", "[class*='memberCard']",
            "article.wp-block-post", "li.wp-block-post", "article",
        ]
        cards = []
        for sel in card_selectors:
            cards = [c for c in soup.select(sel) if c.get_text(strip=True)]
            if cards:
                break
        if not cards:
            cards = [el for el in soup.select("li, div") if el.select_one("h2, h3, h4")]

        if cards:
            sample_cls = sorted({c for el in cards[0].select("[class]") for c in el.get("class", [])})
            logger.warning(
                f"[Welsh Parliament] Fallback card selectors — first card CSS classes: {sample_cls[:20]}\n"
                f"  Snippet: {str(cards[0])[:400]}"
            )

        for card in cards:
            name_el = (
                card.select_one("h2, h3, h4")
                or card.select_one("[class*='name'], [class*='Name']")
                or card.select_one("strong, b")
            )
            party_el = (
                card.select_one("[class*='party'], [class*='Party']")
                or card.select_one("[class*='group'], [class*='Group']")
                or card.select_one(".tag, .badge, [class*='tag'], [class*='badge']")
                or card.select_one("span.wp-block-post-terms, .wp-block-post-terms")
            )
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
    # NOTE: business.senedd.wales API endpoints consistently TIME OUT (30s × 3 retries
    # each = ~7 min wasted) and senedd.wales/api/* all 404.  Only record.senedd.wales/api
    # is kept (it returns the SPA shell quickly, which _api_get rejects fast).
    _QUESTION_API_CANDIDATES = [
        f"{_RECORD}/api/questions",
        f"{_RECORD}/api/written-questions",
        f"{_RECORD}/api/oral-questions",
    ]

    def _search_soup(self, params: Dict) -> Optional[BeautifulSoup]:
        """Fetch record.assembly.wales/Search (or record.senedd.wales/Search) with given params."""
        for url in _SEARCH_URLS:
            soup = self._html_get(url, params=params)
            if soup and len(soup.get_text(strip=True)) > 300:
                return soup
        return None

    def _try_search_api(self, from_date: Optional[str] = None) -> List[Dict]:
        """Discover and call the JSON search API behind the record.senedd.wales SPA.

        The SPA shell references JS bundles and often embeds an API base URL or calls
        a predictable controller endpoint.  We try a list of likely JSON endpoints with
        a JSON Accept header; any that return real JSON (not the HTML shell) are parsed.
        Logs the raw response keys so we can refine extraction on the next run.
        """
        records: List[Dict] = []

        # Candidate JSON search endpoints (ASP.NET MVC / Cofnod conventions).
        # ?term= / ?searchTerm= empty returns recent items in most implementations.
        api_candidates = [
            f"{_RECORD}/Search/Results",
            f"{_RECORD}/Search/GetResults",
            f"{_RECORD}/api/search",
            f"{_RECORD}/Search/Search",
            f"{_RECORD}/SearchResults",
            f"{_RECORD_ALT}/Search/Results",
            f"{_RECORD_ALT}/api/search",
        ]
        param_variants = [
            {"searchTerm": "", "page": 1},
            {"term": "", "page": 1},
            {"query": "", "page": 1},
            {"q": ""},
        ]

        for api_url in api_candidates:
            for params in param_variants:
                p = dict(params)
                if from_date:
                    p["dateFrom"] = from_date
                data = self._api_get(api_url, params=p)
                if not data:
                    continue
                # Found JSON! Log its shape so we can map fields next run.
                if isinstance(data, dict):
                    logger.warning(
                        f"[Welsh Parliament] Search API responded: {api_url} params={p} "
                        f"keys={list(data.keys())[:15]}"
                    )
                    items = (data.get("results") or data.get("items")
                             or data.get("Results") or data.get("data") or [])
                elif isinstance(data, list):
                    logger.warning(
                        f"[Welsh Parliament] Search API responded (list): {api_url} "
                        f"len={len(data)} sample_keys={list(data[0].keys())[:15] if data and isinstance(data[0], dict) else 'n/a'}"
                    )
                    items = data
                else:
                    continue

                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    name = (item.get("memberName") or item.get("MemberName")
                            or item.get("tabledBy") or item.get("askedBy")
                            or item.get("author") or "")
                    text = (item.get("text") or item.get("Text") or item.get("body")
                            or item.get("questionText") or item.get("title") or "")
                    q_date = (item.get("date") or item.get("Date")
                              or item.get("tabledDate") or "")[:10]
                    if not text:
                        continue
                    records.append(self._make_record(
                        data_type="question",
                        member={"id": "", "name": name, "party": "",
                                "constituency": "", "role": "MS"},
                        date=q_date,
                        text=text,
                        title=item.get("title", item.get("Title", "")),
                        metadata={"question_type": "written"},
                        source_url=api_url,
                    ))
                if records:
                    logger.info(f"[Welsh Parliament] Search API: {len(records)} records from {api_url}")
                    return records

        logger.warning("[Welsh Parliament] No working JSON search API found — Welsh questions "
                       "will fall back to order-paper enumeration (text only, no member names)")
        return records

    def _is_spa_shell(self, soup: BeautifulSoup) -> bool:
        """Detect the record.senedd.wales JS nav-shell (no SSR content).

        The shell's entire body text starts with the site chrome
        ("National Assembly for Wales Help ... Glossary Contact us ...") and
        contains no result content.  Returns True if this looks like the empty shell.
        """
        if not soup:
            return True
        body = soup.find("body")
        text = body.get_text(separator=" ", strip=True) if body else ""
        # The shell is short-ish and dominated by nav chrome
        shell_markers = ("National Assembly for Wales Help", "Glossary Contact us",
                         "What is Plenary", "Go to Senedd Business")
        has_chrome = sum(1 for m in shell_markers if m in text) >= 2
        # Real result pages contain WQ/AQ numbers or multiple result/article elements
        has_results = bool(re.search(r"(WQ|AQ|OQ)[- ]?\d{3,}", text)) or \
            len(soup.select("article, [class*='result']")) > 2
        return has_chrome and not has_results

    def _fetch_questions_search(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch questions from record.senedd.wales/Search.

        NOTE: This page is a JavaScript SPA — the server returns only a nav shell.
        Result cards (with member names, WQ numbers, dates) are rendered client-side.
        We detect the shell early and bail so we don't waste time probing dead filters.
        If the Senedd ever serves SSR content here (or we find the JSON API), this
        path will pick it up automatically.
        """
        records: List[Dict] = []
        seen_ids: set = set()

        # Verify the search page is reachable and is NOT just the JS shell
        probe = self._search_soup({})
        if not probe:
            logger.warning("[Welsh Parliament] Search page not reachable — all URLs failed")
            return records

        if self._is_spa_shell(probe):
            logger.warning(
                "[Welsh Parliament] record.senedd.wales/Search is a JS SPA shell "
                "(no server-side result cards) — skipping HTML scrape. "
                "Member names require the underlying JSON search API or a headless browser."
            )
            # Try to discover the search API from the shell's JS references before giving up
            api_records = self._try_search_api(from_date)
            return api_records

        logger.info("[Welsh Parliament] Search page returned SSR content — parsing result cards")

        # Type-ID variants to try for each question category.
        # We try numeric typeIds first (ASP.NET MVC convention for the Cofnod system)
        # then fall back to string-name params.
        for q_type, type_variants in [
            ("written", [
                {"typeIds": "4"}, {"typeIds": "5"}, {"typeIds": "1"}, {"typeIds": "6"},
                {"type": "WrittenQuestion"}, {"type": "Written"},
                {"FilterType": "WrittenQuestion"}, {"category": "WrittenQuestion"},
            ]),
            ("oral", [
                {"typeIds": "3"}, {"typeIds": "2"},
                {"type": "OralQuestion"}, {"type": "Oral"},
                {"FilterType": "OralQuestion"},
            ]),
        ]:
            found_params: Optional[Dict] = None

            for type_params in type_variants:
                test_params: Dict = dict(type_params)
                if from_date:
                    test_params["dateFrom"] = from_date
                    test_params["dateTo"] = date.today().isoformat()

                soup = self._search_soup(test_params)
                if not soup:
                    continue

                # Look for result cards — Cofnod uses various class names
                cards = []
                for sel in [
                    "article.result", ".search-result", "[class*='result-item']",
                    "[class*='result-card']", "li[class*='result']",
                    "article", "div[class*='result']", "li[class*='search']",
                ]:
                    cards = soup.select(sel)
                    if cards:
                        break

                if not cards:
                    body = soup.find("body")
                    snippet = body.get_text(separator=" ", strip=True)[:200] if body else ""
                    logger.warning(
                        f"[Welsh Parliament] Search {type_params}: no result cards — snippet: {snippet!r}"
                    )
                    continue

                page_text = soup.get_text()
                if not re.search(
                    r"WQ[- ]?\d+|AQ[- ]?\d+|Written Question|Oral Question|Tabled|Question",
                    page_text, re.I,
                ):
                    logger.warning(
                        f"[Welsh Parliament] Search {type_params}: {len(cards)} cards but no question markers"
                    )
                    continue

                logger.info(f"[Welsh Parliament] Search {type_params}: {len(cards)} cards (type={q_type})")
                found_params = test_params
                break

            if found_params is None:
                # No type filter worked — fall back to unfiltered search for this q_type
                logger.warning(
                    f"[Welsh Parliament] No working type filter for {q_type} questions — "
                    f"will try unfiltered search"
                )
                found_params = {}
                if from_date:
                    found_params["dateFrom"] = from_date
                    found_params["dateTo"] = date.today().isoformat()

            # Page through results
            page = 1
            while page <= 200:
                page_params = {**found_params, "page": page}
                soup = self._search_soup(page_params)
                if not soup:
                    break

                cards = []
                for sel in [
                    "article.result", ".search-result", "[class*='result-item']",
                    "[class*='result-card']", "li[class*='result']",
                    "article", "div[class*='result']", "li[class*='search']",
                ]:
                    cards = soup.select(sel)
                    if cards:
                        break

                if not cards:
                    break

                page_added = 0
                for card in cards:
                    card_text = card.get_text(separator=" ", strip=True)

                    # Question ID (WQ98839 / WQ-98839 / AQ12345)
                    wq_m = re.search(r"(WQ|AQ)[- ]?(\d+)", card_text, re.I)
                    q_id = f"{wq_m.group(1).upper()}{wq_m.group(2)}" if wq_m else ""
                    if q_id and q_id in seen_ids:
                        continue
                    if q_id:
                        seen_ids.add(q_id)

                    # Member name — try label patterns first then structural selectors
                    member_name = ""

                    # <dt>Tabled by</dt><dd>Name</dd>
                    for dt in card.select("dt"):
                        dt_text = dt.get_text(strip=True).lower()
                        if any(kw in dt_text for kw in ("tabled", "asked", "member", "by", "aelod")):
                            dd = dt.find_next_sibling("dd")
                            if dd:
                                member_name = dd.get_text(strip=True)
                                break

                    # "Tabled by: Name" or "Asked by Name" inline in text
                    if not member_name:
                        m = re.search(
                            r"(?:Tabled|Asked)\s+by[:\s]+([A-Z][a-zA-Záéíóú'\-]+(?:\s+[A-Z][a-zA-Záéíóú'\-]+)+)",
                            card_text,
                        )
                        if m:
                            member_name = m.group(1).strip()

                    # CSS-class-based selectors
                    if not member_name:
                        for sel in (
                            ".member-name", "[class*='member']", "[class*='tabled']",
                            "[class*='asked']", "[class*='author']", "[class*='name']",
                        ):
                            el = card.select_one(sel)
                            if el:
                                cand = el.get_text(strip=True)
                                if cand and len(cand) > 2 and cand not in ("Member", "Name", "Aelod"):
                                    member_name = cand
                                    break

                    # Last resort: first <strong>/<b> that looks like a person name
                    if not member_name:
                        for el in card.select("strong, b"):
                            cand = el.get_text(strip=True)
                            words = cand.split()
                            if 2 <= len(words) <= 6 and all(
                                w and w[0].isupper() for w in words if w.isalpha()
                            ):
                                member_name = cand
                                break

                    # Date — prefer time[datetime] then regex
                    q_date = ""
                    date_el = card.select_one("time[datetime]")
                    if date_el:
                        q_date = date_el.get("datetime", "")[:10]
                    if not q_date:
                        dm = re.search(
                            r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})",
                            card_text,
                        )
                        if dm:
                            raw = dm.group(1)
                            if "/" in raw:
                                try:
                                    from datetime import datetime as _dt
                                    q_date = _dt.strptime(raw, "%d/%m/%Y").strftime("%Y-%m-%d")
                                except ValueError:
                                    q_date = raw
                            elif re.match(r"\d{4}-\d{2}-\d{2}", raw):
                                q_date = raw
                            else:
                                try:
                                    from datetime import datetime as _dt
                                    for fmt in ("%d %B %Y", "%d %b %Y"):
                                        try:
                                            q_date = _dt.strptime(raw, fmt).strftime("%Y-%m-%d")
                                            break
                                        except ValueError:
                                            continue
                                except Exception:
                                    q_date = raw

                    if from_date and q_date and q_date[:10] < from_date:
                        continue

                    title_el = card.select_one("h2, h3, h4, .title, [class*='title']")
                    q_title = title_el.get_text(strip=True) if title_el else q_id

                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": "", "name": member_name, "party": "",
                            "constituency": "", "role": "MS",
                        },
                        date=q_date,
                        text=card_text,
                        title=q_title or q_id,
                        metadata={"question_type": q_type, "question_id": q_id},
                        source_url=_SEARCH_URLS[0],
                    ))
                    page_added += 1

                # Log sample from first page to diagnose member extraction
                if page == 1 and records and not hasattr(self, "_search_q_sample_logged"):
                    self._search_q_sample_logged = True
                    samp = records[-1]
                    logger.warning(
                        f"[Welsh Parliament] Search question sample: "
                        f"name={samp.get('member', {}).get('name', '')!r} "
                        f"date={samp.get('date', '')!r} "
                        f"q_id={samp.get('metadata', {}).get('question_id', '')!r}"
                    )

                # Check for a "Next" pagination link
                next_link = None
                for sel in [
                    "a[rel='next']", ".pagination__next:not(.disabled)",
                    "[class*='next']:not([class*='disabled'])", "a[aria-label='Next page']",
                ]:
                    el = soup.select_one(sel)
                    if el:
                        next_link = el
                        break
                if not next_link:
                    for a in soup.select(".pagination a, [class*='pag'] a"):
                        if re.search(r"next|»|›", a.get_text(), re.I):
                            next_link = a
                            break

                if not next_link or page_added == 0:
                    break
                page += 1

        named = sum(1 for r in records if r.get("member", {}).get("name", ""))
        logger.info(
            f"[Welsh Parliament] Search questions: {len(records)} records, "
            f"{named} with member names"
        )
        return records

    def _date_range_days(self, from_date: Optional[str] = None) -> List[str]:
        """Return ISO date strings from from_date (or 2016-05-11, Senedd start) to today."""
        start = date.fromisoformat(from_date) if from_date else date(2016, 5, 11)
        end = date.today()
        days = []
        current = start
        while current <= end:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _fetch_questions_order_paper(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch written questions from the record.senedd.wales order paper pages.

        URL pattern: https://record.senedd.wales/OrderPaper/WrittenQuestions/DD-MM-YYYY/
        This is a confirmed SSR page listing questions submitted for each sitting day.
        Individual questions: https://record.senedd.wales/WrittenQuestion/WQ-NNNNN
        """
        records = []
        # Enumerate recent dates — start from 3 months ago for incremental, or 2016 for full
        from_dt = date.fromisoformat(from_date) if from_date else date(2020, 1, 1)
        today = date.today()
        seen_ids: set = set()

        current = from_dt
        consecutive_empty = 0
        while current <= today and consecutive_empty < 90:
            day_str = current.strftime("%d-%m-%Y")  # DD-MM-YYYY as used by senedd.wales
            url = f"{_RECORD}/OrderPaper/WrittenQuestions/{day_str}/"
            soup = self._html_get(url)
            current += timedelta(days=1)
            if not soup:
                consecutive_empty += 1
                continue

            # Check for actual question content (not just nav shell)
            body_text = soup.get_text(separator=" ", strip=True)
            if len(body_text) < 300 or not re.search(r"WQ-\d+|question|tabled|written", body_text, re.I):
                consecutive_empty += 1
                continue

            consecutive_empty = 0
            # Find individual question links
            q_links = [
                (a["href"] if a["href"].startswith("http") else f"{_RECORD}{a['href']}")
                for a in soup.select("a[href]")
                if re.search(r"/WrittenQuestion/WQ-\d+|/Question/\d+", a.get("href", ""), re.I)
            ]
            q_links = list(dict.fromkeys(q_links))
            if not q_links:
                # Try parsing directly from the listing page (some dates list question text inline)
                for row in soup.select("tr, li, .question-item, article"):
                    text = row.get_text(strip=True)
                    if len(text) < 10:
                        continue
                    q_id_match = re.search(r"WQ-(\d+)", text)
                    q_id = q_id_match.group(0) if q_id_match else ""
                    if q_id and q_id in seen_ids:
                        continue
                    if q_id:
                        seen_ids.add(q_id)
                    name_el = row.select_one("strong, b, .member-name, td:first-child")
                    records.append(self._make_record(
                        data_type="question",
                        member={"id": "", "name": name_el.get_text(strip=True) if name_el else "",
                                "party": "", "constituency": "", "role": "MS"},
                        date=current.isoformat(),
                        text=text,
                        title=q_id,
                        metadata={"question_type": "written", "question_id": q_id},
                        source_url=url,
                    ))
                continue

            logger.info(f"[Welsh Parliament] Questions: {len(q_links)} question links for {day_str}")
            for q_url in q_links[:50]:
                q_id_match = re.search(r"WQ-(\d+)|/(\d+)$", q_url)
                q_id = q_id_match.group(0) if q_id_match else ""
                if q_id and q_id in seen_ids:
                    continue
                if q_id:
                    seen_ids.add(q_id)
                q_detail = self._html_get(q_url)
                if not q_detail:
                    continue
                # Parse question text, member name, and answer
                q_text_el = q_detail.select_one(
                    ".question-text, .question-body, [class*='question'], article p, main p"
                )
                q_text = q_text_el.get_text(strip=True) if q_text_el else ""
                ans_el = q_detail.select_one(".answer-text, .answer-body, [class*='answer']")
                answer = ans_el.get_text(strip=True) if ans_el else ""
                combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                if not combined:
                    combined = q_detail.get_text(separator=" ", strip=True)[:500]
                member_name = ""
                # Try specific Senedd member selectors first
                for sel in [
                    ".member-name", ".asked-by", "[class*='member-name']",
                    "[class*='asked-by']", "[class*='tabled-by']",
                ]:
                    el = q_detail.select_one(sel)
                    if el:
                        member_name = el.get_text(strip=True)
                        break
                # Try label-value patterns: <dt>Tabled by</dt><dd>Name</dd>
                if not member_name:
                    for dt in q_detail.select("dt"):
                        dt_text = dt.get_text(strip=True).lower()
                        if any(kw in dt_text for kw in ("tabled", "asked", "member")):
                            dd = dt.find_next_sibling("dd")
                            if dd:
                                member_name = dd.get_text(strip=True)
                                break
                # Try looking for "Asked by:" / "Tabled by:" pattern in paragraph text
                if not member_name:
                    for p in q_detail.select("p, span, td"):
                        text_raw = p.get_text(strip=True)
                        m = re.match(r"(?:Asked|Tabled)\s+by[:\s]+(.+)", text_raw, re.I)
                        if m:
                            member_name = m.group(1).strip()
                            break
                # Last resort: first <strong> or <b> that looks like a name (2+ words, title-case)
                if not member_name:
                    for el in q_detail.select("strong, b"):
                        candidate = el.get_text(strip=True)
                        words = candidate.split()
                        if 2 <= len(words) <= 5 and all(w[0].isupper() for w in words if w):
                            member_name = candidate
                            break
                date_el = q_detail.select_one("time[datetime], time, .date, [class*='date']")
                q_date = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else current.isoformat()
                subject_el = q_detail.select_one("h1, .subject, .title, [class*='subject']")
                subject = subject_el.get_text(strip=True) if subject_el else ""
                records.append(self._make_record(
                    data_type="question",
                    member={"id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"},
                    date=q_date,
                    text=combined,
                    title=subject or q_id,
                    metadata={"question_type": "written", "question_id": q_id, "answer_text": answer},
                    source_url=q_url,
                ))

        logger.info(f"[Welsh Parliament] Order paper questions: {len(records)} records")
        return records

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        # 1. Search page (confirmed SSR — returns question cards with member names)
        records = self._fetch_questions_search(from_date)
        if records:
            logger.info(f"[Welsh Parliament] {len(records)} question records fetched via Search page")
            return records

        # 2. Try REST API endpoints (SPAs — these return HTML shell, but worth trying)
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

        # 2. Order Paper date-enumeration approach (confirmed SSR endpoint)
        records = self._fetch_questions_order_paper(from_date)
        if records:
            logger.info(f"[Welsh Parliament] {len(records)} question records fetched via order paper")
            return records

        # 3. Fall back to HTML scraping
        _ITEM_LINK_RE = re.compile(
            r"/\d{4}-\d{2}-\d{2}|/\d{4}/\d{2}|/\d{5,}|"
            r"question[s]?/\w|oral[s]?/\d|written[s]?/\d",
            re.I,
        )

        search_targets = [
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

        # 2b. If record.senedd.wales paths all 404'd, try the main senedd.wales site.
        # https://senedd.wales/senedd-business/plenary/ is a WordPress SSR page that
        # lists plenary sessions and may link to record.senedd.wales SSR session pages.
        if not session_links:
            for path in _SENEDD_PLENARY_PATHS:
                url = f"{_BASE}{path}"
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
                        if href.startswith("http"):
                            full_link = href
                        else:
                            # relative links on senedd.wales resolve against _BASE
                            full_link = f"{_BASE}{href}"
                        found.append(full_link)
                found = list(dict.fromkeys(found))
                if found:
                    session_links = found
                    logger.info(f"[Welsh Parliament] Plenary: found {len(session_links)} session links at {url}")
                    break
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:400] if body else ""
                sample_hrefs = all_hrefs[:10]
                logger.warning(f"[Welsh Parliament] Plenary: no session links at {url} — sample hrefs: {sample_hrefs} — snippet: {snippet}")
                # When landing on the senedd.wales plenary overview, follow sub-pages
                # (e.g. /senedd-business/plenary/past-plenary-sessions/) to find listings.
                if "senedd-business/plenary" in path:
                    sub_paths = [
                        h for h in all_hrefs
                        if ("senedd-business/plenary/" in h)
                        and h not in ("/senedd-business/plenary/", path, url)
                        and not h.endswith("/what-is-plenary/")
                    ]
                    for sub_href in sub_paths[:8]:
                        sub_url = sub_href if sub_href.startswith("http") else f"{_BASE}{sub_href}"
                        sub_soup = self._html_get(sub_url)
                        if not sub_soup:
                            continue
                        sub_hrefs = []
                        for link in sub_soup.select("a[href]"):
                            h2 = link.get("href", "")
                            if not h2 or not (h2.startswith("/") or h2.startswith("http")):
                                continue
                            sub_hrefs.append(h2)
                            if self._SESSION_LINK_RE.search(h2):
                                fl = h2 if h2.startswith("http") else f"{_BASE}{h2}"
                                found.append(fl)
                        logger.info(f"[Welsh Parliament] Plenary sub-page {sub_url}: {len(found)} session links — sample hrefs: {sub_hrefs[:8]}")
                    if found:
                        session_links = list(dict.fromkeys(found))
                        logger.info(f"[Welsh Parliament] Plenary: {len(session_links)} session links from sub-pages of {url}")
                        # Do NOT break here — keep checking remaining _SENEDD_PLENARY_PATHS
                        # in case other sub-pages add more session links.

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
                # WordPress content selectors (senedd.wales main site)
                ".wp-block-post-content p", ".entry-content p", "article p",
            ]
            contribs = []
            for sel in contrib_selectors:
                contribs = session_soup.select(sel)
                if contribs:
                    break

            if not contribs:
                body = session_soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
                logger.warning(f"[Welsh Parliament] Plenary: 0 contribs at {session_url} — snippet: {snippet}")
                continue

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

    def _fetch_meeting_ids_wales(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch plenary meeting IDs needed for the XML transcript export.

        All /en/plenary/* paths on record.senedd.wales redirect to an error page.
        Instead we scan senedd.wales/senedd-business/plenary/ and its sub-pages
        (the same WordPress pages used by fetch_plenary_business) looking for links
        to record.senedd.wales/Plenary/{meetingId} or record.assembly.wales/Plenary/{id}.
        """
        meetings: List[Dict] = []
        seen: set = set()

        # Links to the Record of Proceedings for a specific plenary session look like:
        #   https://record.senedd.wales/Plenary/7622/
        #   https://record.assembly.wales/Plenary/7622
        #   https://record.senedd.wales/en/Plenary/Meeting/?meetingId=7622
        _MID_RE = re.compile(
            r"record\.(?:senedd|assembly)\.wales(?:/[a-z]{2})?/[Pp]lenary/(\d+)"
            r"|[Mm]eeting[Ii][Dd]=(\d+)",
            re.I,
        )

        def _parse_date(text: str) -> str:
            dm = re.search(r"\d{4}-\d{2}-\d{2}", text)
            if dm:
                return dm.group(0)
            dm2 = re.search(r"(\d{1,2})[/ ](\d{1,2})[/ ](\d{4})", text)
            if dm2:
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(dm2.group(0), "%d/%m/%Y").strftime("%Y-%m-%d")
                except Exception:
                    pass
            dm3 = re.search(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
                            r"September|October|November|December)\s+(\d{4})", text, re.I)
            if dm3:
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(dm3.group(0), "%d %B %Y").strftime("%Y-%m-%d")
                except Exception:
                    pass
            return ""

        def _add(href: str, context: str) -> None:
            m = _MID_RE.search(href)
            if not m:
                return
            mid = m.group(1) or m.group(2)
            if not mid or mid in seen:
                return
            m_date = _parse_date(context)
            if from_date and m_date and m_date[:10] < from_date:
                return
            seen.add(mid)
            meetings.append({"id": mid, "date": m_date})

        # Scan the senedd.wales plenary pages — same approach as fetch_plenary_business
        for plenary_path in _SENEDD_PLENARY_PATHS:
            plenary_url = f"{_BASE}{plenary_path}"
            soup = self._html_get(plenary_url)
            if not soup:
                continue

            all_hrefs = [a.get("href", "") for a in soup.select("a[href]") if a.get("href")]

            # Collect sub-pages of /senedd-business/plenary/ (exclude nav-only pages)
            sub_hrefs = [
                h for h in all_hrefs
                if "senedd-business/plenary/" in h
                and h not in (plenary_path, plenary_url, "/senedd-business/plenary/")
                and not any(x in h for x in ("/what-is-plenary", "/about-plenary", "#"))
            ]

            pages_to_scan = [(plenary_url, soup)]
            for sub_href in sub_hrefs[:20]:
                sub_url = sub_href if sub_href.startswith("http") else f"{_BASE}{sub_href}"
                sub_soup = self._html_get(sub_url)
                if sub_soup:
                    pages_to_scan.append((sub_url, sub_soup))
                    # Follow one more level: individual session pages linked from sub-pages
                    for a2 in sub_soup.select("a[href]"):
                        h2 = a2.get("href", "")
                        if not h2:
                            continue
                        # Session pages: date-based like /senedd-business/plenary/2026-03-15/
                        if re.search(r"senedd-business/plenary/\d{4}-\d{2}", h2):
                            sess_url = h2 if h2.startswith("http") else f"{_BASE}{h2}"
                            sess_soup = self._html_get(sess_url)
                            if sess_soup:
                                pages_to_scan.append((sess_url, sess_soup))

            # Scan all collected pages for record.senedd.wales/Plenary/{id} links
            for page_url, page_soup in pages_to_scan:
                for a in page_soup.select("a[href]"):
                    href = a.get("href", "")
                    if not href:
                        continue
                    if not _MID_RE.search(href):
                        continue
                    row = (a.find_parent("tr") or a.find_parent("li")
                           or a.find_parent("article") or a.find_parent("div"))
                    context = (row.get_text(separator=" ", strip=True)
                               if row else a.get_text(strip=True))
                    _add(href, context)

            if meetings:
                logger.info(f"[Welsh Parliament] {len(meetings)} meeting IDs from senedd.wales plenary pages")
                dated = [x for x in meetings if x["date"]][:3]
                undated = [x for x in meetings if not x["date"]][:3]
                logger.warning(f"[Welsh Parliament] Meeting IDs sample dated={dated} undated={undated}")
                return meetings
            else:
                logger.warning(
                    f"[Welsh Parliament] No record.senedd.wales Plenary links found on {plenary_url} "
                    f"(checked {len(pages_to_scan)} pages) — session pages may not link to Record"
                )

        logger.warning("[Welsh Parliament] Could not find any meeting IDs — XML export unavailable")
        return meetings

    def _fetch_votes_xml_export(self, meeting_id: str, meeting_date: str,
                                 from_date: Optional[str], records: List[Dict]) -> int:
        """Fetch votes from the XML transcript export for a given meeting.

        URL: https://record.senedd.wales/XMLExport/Download?meetingID=NNNN&xmlDownloadType=EnglishTranscript
        The XML contains <Division> elements with <MotionText> and member vote lists.
        Returns number of records added.
        """
        if from_date and meeting_date and len(meeting_date) >= 10 and meeting_date[:10] < from_date:
            return 0
        url = f"{_RECORD}/XMLExport/Download"
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/xml,text/xml,*/*;q=0.8",
            "Referer": f"{_RECORD}/en/plenary/divisions/",
        })
        resp = self._get(url, params={"meetingID": meeting_id, "xmlDownloadType": "EnglishTranscript"},
                         timeout=60)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0

        ct = resp.headers.get("Content-Type", "")
        if "html" in ct and "<html" in resp.text.lower()[:200]:
            logger.warning(f"[Welsh Parliament] XML export meeting {meeting_id}: got HTML shell, not XML")
            return 0

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            logger.warning(f"[Welsh Parliament] XML parse error for meeting {meeting_id}: {e}")
            return 0

        # Strip namespace prefixes to simplify element access
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]

        # Extract date from XML — try multiple element names
        if not meeting_date:
            for date_tag in ("SittingDate", "MeetingDate", "Date", "PlnryDate",
                             "PlenaryDate", "SessionDate", "DateOfSitting"):
                date_el = root.find(f".//{date_tag}")
                if date_el is not None and date_el.text:
                    meeting_date = date_el.text.strip()[:10]
                    break
        if not meeting_date and not hasattr(self, "_xml_date_logged"):
            self._xml_date_logged = True
            all_tags = list({el.tag for el in root.iter()})
            logger.warning(f"[Welsh Parliament] XML meeting {meeting_id}: could not find date. Tags present: {all_tags[:20]}")

        before = len(records)
        for div_el in root.iter("Division"):
            div_title_el = div_el.find("MotionText") or div_el.find("DivisionSubject") or div_el.find("Title")
            div_title = div_title_el.text.strip() if div_title_el is not None and div_title_el.text else ""
            div_date_el = div_el.find("DivisionDate") or div_el.find("Date")
            div_date = (div_date_el.text[:10] if div_date_el is not None and div_date_el.text else meeting_date)

            for vote_group, direction in [
                ("AyeVoters", "aye"), ("ForVoters", "aye"),
                ("NoeVoters", "no"), ("AgainstVoters", "no"), ("NoVoters", "no"),
                ("AbstainVoters", "abstain"), ("AbstentionVoters", "abstain"),
            ]:
                group_el = div_el.find(vote_group)
                if group_el is None:
                    continue
                for member_el in group_el.iter("Member"):
                    name_el = member_el.find("Name") or member_el.find("MemberName")
                    name = name_el.text.strip() if name_el is not None and name_el.text else member_el.text or ""
                    name = name.strip()
                    if not name:
                        continue
                    mid_el = member_el.find("MemberId") or member_el.find("PersonId")
                    member_id = mid_el.text.strip() if mid_el is not None and mid_el.text else ""
                    records.append(self._make_record(
                        data_type="vote",
                        member={"id": member_id, "name": name, "party": "", "constituency": "", "role": "MS"},
                        date=div_date,
                        text=f"Voted {direction} on: {div_title}",
                        title=div_title,
                        metadata={"vote_direction": direction, "division_result": "",
                                  "meeting_id": meeting_id},
                        source_url=f"{url}?meetingID={meeting_id}",
                    ))

        added = len(records) - before
        if added == 0 and not hasattr(self, "_xml_vote_empty_logged"):
            self._xml_vote_empty_logged = True
            logger.warning(
                f"[Welsh Parliament] XML export meeting {meeting_id}: 0 division records. "
                f"Root tag={root.tag}, children={[c.tag for c in root][:10]}"
            )
        return added

    def _fetch_votes_search(self, from_date: Optional[str] = None) -> List[Dict]:
        """Try to find division/vote content via the record.assembly.wales/Search page.

        Looks for search result types that match divisions (e.g. typeIds for Vote/Division).
        Returns vote records if found, empty list otherwise.
        """
        records: List[Dict] = []
        seen: set = set()

        # Try common type IDs and names for division content
        for type_params in [
            {"typeIds": "7"}, {"typeIds": "8"}, {"typeIds": "9"}, {"typeIds": "10"},
            {"type": "Division"}, {"type": "Vote"}, {"type": "VoteOnDivision"},
            {"FilterType": "Division"}, {"FilterType": "Vote"},
        ]:
            test_params: Dict = dict(type_params)
            if from_date:
                test_params["dateFrom"] = from_date

            soup = self._search_soup(test_params)
            if not soup:
                continue

            cards = []
            for sel in [
                "article.result", ".search-result", "[class*='result-item']",
                "article", "div[class*='result']",
            ]:
                cards = soup.select(sel)
                if cards:
                    break

            if not cards:
                continue

            page_text = soup.get_text()
            if not re.search(r"[Dd]ivision|[Vv]ote|[Pp]lenary", page_text):
                continue

            logger.info(f"[Welsh Parliament] Search votes {type_params}: {len(cards)} cards")

            for card in cards:
                card_text = card.get_text(separator=" ", strip=True)
                # Extract division title and member name
                title_el = card.select_one("h2, h3, h4, .title, [class*='title']")
                div_title = title_el.get_text(strip=True) if title_el else card_text[:100]

                member_name = ""
                for dt in card.select("dt"):
                    if any(kw in dt.get_text(strip=True).lower() for kw in ("voted", "member", "ms ")):
                        dd = dt.find_next_sibling("dd")
                        if dd:
                            member_name = dd.get_text(strip=True)
                            break

                q_date = ""
                date_el = card.select_one("time[datetime]")
                if date_el:
                    q_date = date_el.get("datetime", "")[:10]
                if not q_date:
                    dm = re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}", card_text)
                    if dm:
                        raw = dm.group(0)
                        if "/" in raw:
                            try:
                                from datetime import datetime as _dt
                                q_date = _dt.strptime(raw, "%d/%m/%Y").strftime("%Y-%m-%d")
                            except ValueError:
                                q_date = raw
                        else:
                            q_date = raw

                if from_date and q_date and q_date[:10] < from_date:
                    continue

                card_id = card_text[:50]
                if card_id in seen:
                    continue
                seen.add(card_id)

                records.append(self._make_record(
                    data_type="vote",
                    member={"id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"},
                    date=q_date,
                    text=card_text,
                    title=div_title,
                    metadata={"vote_direction": "", "division_result": ""},
                    source_url=_SEARCH_URLS[0],
                ))

            if records:
                break

        logger.info(f"[Welsh Parliament] Search votes: {len(records)} records")
        return records

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        records: List[Dict] = []

        # 1. Try XML Export for each meeting that has divisions.
        #    Meeting IDs come from scanning senedd.wales plenary session pages.
        meeting_ids = self._fetch_meeting_ids_wales(from_date)
        if meeting_ids:
            logger.info(f"[Welsh Parliament] Fetching votes via XML export for {len(meeting_ids)} meetings...")
            hits = 0
            for i, m in enumerate(meeting_ids):
                added = self._fetch_votes_xml_export(m["id"], m.get("date", ""), from_date, records)
                if added > 0:
                    hits += 1
            logger.info(f"[Welsh Parliament] XML export: {hits}/{len(meeting_ids)} meetings had votes, {len(records)} total")
            if records:
                logger.info(f"[Welsh Parliament] {len(records)} vote records fetched via XML export")
                return records
            logger.warning(f"[Welsh Parliament] {len(meeting_ids)} meetings found but XML export returned 0 votes")

        # 2. Try the Search page with division-type filter
        records = self._fetch_votes_search(from_date)
        if records:
            logger.info(f"[Welsh Parliament] {len(records)} vote records fetched via Search page")
            return records

        # 3. Fall back to HTML scraping from the divisions index — all known paths are broken
        # (all /en/plenary/* redirect to cofnod.senedd.cymru/Error/NotFound) but log for diagnosis
        soup = self._try_paths(_RECORD, _DIVISION_PATHS) if _DIVISION_PATHS else None
        if not soup:
            logger.warning("[Welsh Parliament] Could not load divisions index — all known paths broken")
            return records

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
            logger.info(f"[Welsh Parliament] {len(records)} vote records fetched")
            return records

        logger.info(f"[Welsh Parliament] Divisions: found {len(rows)} rows to check")
        sample_div_hrefs = [r.select_one("a[href]")["href"] for r in rows[:5] if r.select_one("a[href]")]
        logger.info(f"[Welsh Parliament] Sample division hrefs: {sample_div_hrefs}")
        for row in rows:
            link_el = row.select_one("a[href]")
            if not link_el:
                continue
            title_el = row.select_one("td:first-child, .title, h2, h3") or link_el
            date_el = row.select_one("td:nth-child(2), time, .date, [class*='date'], li:nth-child(2), span[class*='date'], p[class*='date']")
            title = title_el.get_text(strip=True)
            div_date = date_el.get_text(strip=True) if date_el else ""
            if not div_date:
                row_text = row.get_text(separator=" ", strip=True)
                dm = re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{1,2}\s+\w+\s+\d{4}", row_text)
                div_date = dm.group(0) if dm else ""
            if from_date and div_date and div_date[:10] < from_date:
                continue

            # Check if this is a meeting-ID link — if so, try XML export directly
            detail_href = link_el["href"]
            if not detail_href or not (detail_href.startswith("/") or detail_href.startswith("http")):
                continue
            mid_match = re.search(r"[Mm]eeting[Ii][Dd]=(\d+)|/[Mm]eeting/(\d+)", detail_href)
            if mid_match:
                mid = mid_match.group(1) or mid_match.group(2)
                self._fetch_votes_xml_export(mid, div_date, from_date, records)
                continue

            detail_url = detail_href if detail_href.startswith("http") else f"{_RECORD}{detail_href}"
            detail_soup = self._html_get(detail_url)
            if not detail_soup:
                continue

            vote_sections = {
                "aye": [".ayes li", ".for li", "[class*='aye'] li", "[class*='For'] li"],
                "no": [".noes li", ".against li", "[class*='no'] li", "[class*='Against'] li"],
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
                        member={"id": "", "name": name, "party": "", "constituency": "", "role": "MS"},
                        date=div_date,
                        text=f"Voted {direction} on: {title}",
                        title=title,
                        metadata={"vote_direction": direction, "division_result": ""},
                        source_url=detail_url,
                    ))

        logger.info(f"[Welsh Parliament] {len(records)} vote records fetched")
        return records
