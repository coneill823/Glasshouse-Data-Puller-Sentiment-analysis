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
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import (PARLIAMENTS, MAX_QUESTION_DETAIL_PAGES,
                    MAX_PLENARY_SESSION_PAGES, REQUEST_TIMEOUT)

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

# Committee filter IDs on the record.senedd.wales/XMLExport form (confirmed 2026-06):
#   0 = All, 908 = Plenary, 909 = Business Committee.
# Filtering to 908 enumerates exactly the plenary meetings whose votes we want.
_PLENARY_COMMITTEE_ID = "908"

# Per-member result token in the Senedd Votes export -> our normalised direction.
_WALES_VOTE_DIR = {
    "For": "aye",
    "Against": "no",
    "Abstain": "abstain",
    "DidNotVote": "no_vote",
}


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
        # The Senedd's ModernGov web service is the clean, structured source;
        # fall back to scraping the listing page only if it's unavailable.
        members = self._fetch_members_moderngov()
        if not members:
            logger.warning("[Welsh Parliament] ModernGov member service returned nothing "
                           "— falling back to listing-page scrape")
            members = self._scrape_members()
        logger.info(f"[Welsh Parliament] {len(members)} MSs fetched")
        return members

    def _fetch_members_moderngov(self) -> List[Dict]:
        """Fetch all MSs from the Senedd's ModernGov web service.

        business.senedd.wales/mgwebservice.asmx/GetCouncillorsByWard returns every
        Member grouped by ward (= constituency/region) as XML, with clean
        id / name / party fields — far more reliable than scraping the JS-rendered
        senedd.wales listing (which now yields only nav chrome).
        """
        url = f"{_BUSINESS}/mgwebservice.asmx/GetCouncillorsByWard"
        saved = dict(self.session.headers)
        self.session.headers.update({"User-Agent": _BROWSER_UA,
                                     "Accept": "text/xml,application/xml,*/*;q=0.8"})
        resp = self._get(url, timeout=60)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            logger.warning(f"[Welsh Parliament] ModernGov member XML parse error: {e}")
            return []
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]

        def _txt(parent, tag: str) -> str:
            e = parent.find(tag)
            return (e.text or "").strip() if e is not None and e.text else ""

        members: List[Dict] = []
        seen: set = set()
        for ward in root.iter("ward"):
            ward_title = _txt(ward, "wardtitle")
            for c in ward.iter("councillor"):
                cid = _txt(c, "councillorid")
                # "Steve Bayliss MS" / "Steve Bayliss AS" -> drop the trailing title
                name = re.sub(r"\s+(MS|AS)$", "", _txt(c, "fullusername")).strip()
                if not name or (cid and cid in seen):
                    continue
                if cid:
                    seen.add(cid)
                members.append({
                    "id": cid,
                    "name": name,
                    "party": _txt(c, "politicalpartytitle"),
                    "constituency": ward_title,
                    "role": "MS",
                    "status": "current",
                })
        if members:
            logger.info(f"[Welsh Parliament] {len(members)} MSs from ModernGov web service")
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
                    logger.debug(f"[Welsh Parliament] WP REST API {url}: {len(members)} MSs, sample={members[0]!r:.200}")
                    return members
        return []

    # Known Senedd party names (used for text-scan fallback on profile pages)
    _SENEDD_PARTIES = [
        "Labour", "Welsh Labour", "Conservative", "Welsh Conservative",
        "Plaid Cymru", "Liberal Democrat", "UKIP", "Reform UK",
        "Welsh Conservatives", "Independent",
    ]

    def _extract_party_from_profile(self, profile_soup: BeautifulSoup, profile_url: str = "") -> str:
        """Extract party/political group from a senedd.wales MS profile page.

        Tries multiple strategies in order:
          1. Taxonomy term links (WordPress category/tag links that match party names)
          2. CSS class hints: [class*=party], [class*=group], .wp-block-post-terms, etc.
          3. JSON-LD structured data embedded in <script type="application/ld+json">
          4. Meta tags with party/group name
          5. Data attributes: data-party, data-group
          6. Breadcrumb links that look like party names
          7. Full-text scan for known party names near "Party:" / "Group:" labels
        """
        # 1. WordPress taxonomy term links — filter by known party name
        for a in profile_soup.select("a[href]"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not text or len(text) > 60:
                continue
            if any(p.lower() in text.lower() for p in self._SENEDD_PARTIES):
                # Make sure this is a category/tag/party link, not a nav link
                if re.search(r"/(party|group|parties|political|plaid|labour|conservative|"
                             r"liberal|ukip|reform|independent)/", href, re.I):
                    return text
                # Or if the text IS a known party name (exact-ish match)
                for p in self._SENEDD_PARTIES:
                    if p.lower() == text.lower() or p.lower() in text.lower():
                        return p

        # 2. CSS class-based selectors
        for sel in (
            "[class*='party-name']", "[class*='partyname']",
            "[class*='party-label']", "[class*='partylabel']",
            "[class*='political-party']", "[class*='politicalparty']",
            "[class*='party-tag']",  "[class*='partytag']",
            "[class*='party']",
            "[class*='group-name']", "[class*='groupname']",
            "[class*='group-label']", "[class*='grouplabel']",
            "[class*='group']",
            ".wp-block-post-terms a", ".wp-block-post-terms",
            ".tag-list a", ".term-list a", ".taxonomy-party a",
        ):
            el = profile_soup.select_one(sel)
            if el:
                candidate = el.get_text(strip=True)
                if candidate and 2 < len(candidate) < 80:
                    return candidate

        # 3. JSON-LD structured data
        for script in profile_soup.select("script[type='application/ld+json']"):
            try:
                import json as _json
                data = _json.loads(script.string or "")
                if isinstance(data, dict):
                    for key in ("partyName", "party", "politicalParty", "group",
                                "memberOf", "affiliation"):
                        val = data.get(key)
                        if isinstance(val, str) and val:
                            return val
                        if isinstance(val, dict):
                            n = val.get("name", "")
                            if n:
                                return n
            except Exception:
                pass

        # 4. Meta tags
        for meta in profile_soup.select("meta[name], meta[property]"):
            attr = meta.get("name", "") or meta.get("property", "")
            if re.search(r"party|group|political", attr, re.I):
                content = meta.get("content", "")
                if content:
                    return content

        # 5. Data attributes
        for el in profile_soup.select("[data-party], [data-group], [data-political-party]"):
            val = el.get("data-party") or el.get("data-group") or el.get("data-political-party") or ""
            if val:
                return val

        # 6. Breadcrumb links
        for a in profile_soup.select(".breadcrumb a, nav[aria-label*='breadcrumb'] a, "
                                     "[class*='breadcrumb'] a"):
            text = a.get_text(strip=True)
            for p in self._SENEDD_PARTIES:
                if p.lower() in text.lower():
                    return p

        # 7. Label/value pattern in body text: "Party: Labour" or "Group: Plaid Cymru"
        body_text = profile_soup.get_text(separator=" ", strip=True)
        m = re.search(
            r"(?:Party|Group|Political\s+Party|Gwleidyddol)[:\s]+"
            r"([A-Z][a-zA-Záéíóú'\-]+(?:\s+[a-zA-Záéíóú'\-]+){0,3})",
            body_text,
        )
        if m:
            candidate = m.group(1).strip().rstrip(".,;")
            # Verify it matches a known party, trim to just the party portion
            # Sort longest first so "Welsh Labour" wins over "Labour"
            for p in sorted(self._SENEDD_PARTIES, key=len, reverse=True):
                if p.lower() in candidate.lower():
                    return p
            # Accept it as-is if it looks short enough to be a party name
            if len(candidate.split()) <= 4:
                return candidate

        # 8. Scan text for any known party name (longest match first to prefer "Welsh Labour" > "Labour")
        for p in sorted(self._SENEDD_PARTIES, key=len, reverse=True):
            if p.lower() in body_text.lower():
                return p

        return ""

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
        logger.debug(f"[Welsh Parliament] Sample hrefs on listing page: {sample_hrefs}")
        profile_links = list(dict.fromkeys(
            (a["href"] if a["href"].startswith("http") else f"{_BASE}{a['href']}")
            for a in soup.select("a[href]")
            if re.search(
                r"/(find-a-member-of-the-senedd|senedd-members|members|aelodau-senedd)/[a-z][a-z0-9-]+/?$",
                a.get("href", ""), re.I)
            and not re.search(r"/(category|tag|page|search|help|glossary|contact)", a.get("href", ""), re.I)
        ))
        logger.debug(f"[Welsh Parliament] Member profile links found: {len(profile_links)} — e.g. {profile_links[:3]}")

        if profile_links:
            for profile_url in profile_links[:80]:
                profile_soup = self._html_get(profile_url)
                if not profile_soup:
                    continue
                name_el = profile_soup.select_one("h1, .page-title, [class*='member-name']")
                name = name_el.get_text(strip=True) if name_el else ""
                if not name or len(name) < 3:
                    slug_m = re.search(r"/find-a-member-of-the-senedd/([a-z0-9-]+)/?$", profile_url, re.I)
                    name = slug_m.group(1).replace("-", " ").title() if slug_m else ""
                party = self._extract_party_from_profile(profile_soup, profile_url)
                const_el = profile_soup.select_one(
                    "[class*='constituency'], [class*='region'], [class*='Constituency'], [class*='Region']"
                )
                constituency = const_el.get_text(strip=True) if const_el else ""
                slug = re.search(r"/find-a-member-of-the-senedd/([a-z0-9-]+)/?$", profile_url, re.I)
                member_id = slug.group(1) if slug else ""
                if not hasattr(self, "_ms_profile_logged"):
                    self._ms_profile_logged = True
                    # Log full HTML of first profile for selector diagnosis
                    import json as _json
                    body_el = profile_soup.find("body")
                    classes_found = sorted({
                        c for el in profile_soup.select("[class]")
                        for c in el.get("class", [])
                    })
                    logger.debug(
                        f"[Welsh Parliament] First MS profile {profile_url}: "
                        f"name={name!r} party={party!r} const={constituency!r} "
                        f"all CSS classes: {classes_found[:40]}\n"
                        f"Body snippet: {body_el.get_text(separator=' ',strip=True)[:500] if body_el else ''!r}"
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
                named_party = sum(1 for m in members if m.get("party"))
                logger.info(f"[Welsh Parliament] {len(members)} MSs scraped via profile pages, {named_party} with party")
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
            logger.debug(
                f"[Welsh Parliament] Fallback card selectors — first card CSS classes: {sample_cls[:20]}\n"
                f"  Snippet: {str(cards[0])[:400]}"
            )

        for card in cards:
            name_el = (
                card.select_one("h2, h3, h4")
                or card.select_one("[class*='name'], [class*='Name']")
                or card.select_one("strong, b")
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

            # Use comprehensive party extraction on the card element
            party = self._extract_party_from_profile(card)

            members.append({
                "id": member_id,
                "name": name,
                "party": party,
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

    @staticmethod
    def _find_register_pdf(soup: BeautifulSoup) -> Tuple[str, int]:
        """Pick the newest Register-of-Interests PDF link on the page.

        Matches links whose href/text mention both 'register' and 'interest'
        (so unrelated /media/ assets and the non-interest "Assembly Register"
        archives are skipped), and returns the one with the latest year, as
        (href, year) — ("", -1) if none found.
        """
        best_href, best_year = "", -1
        for a in soup.select("a[href*='.pdf']"):
            href = a.get("href", "")
            haystack = f"{href} {a.get_text(strip=True)}".lower()
            if "register" not in haystack or "interest" not in haystack:
                continue
            years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", haystack)]
            year = max(years) if years else 0
            if year > best_year:
                best_href, best_year = href, year
        return best_href, best_year

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        soup = self._try_paths(_BASE, _INTEREST_PATHS)
        records = []
        if not soup:
            logger.warning("[Welsh Parliament] Could not load register of interests page")
            return records

        # The Senedd publishes the consolidated Register of Interests only as an
        # end-of-term PDF (one per Senedd/Assembly), and the page lists every
        # term's archive. Pick the newest *register* PDF by the years in its link
        # rather than the first link in DOM order — which is an older archive or
        # an unrelated /media/ asset (Scotland's scraper hit the same trap).
        pdf_href, pdf_year = self._find_register_pdf(soup)
        if pdf_href:
            pdf_url = pdf_href if pdf_href.startswith("http") else urljoin(_BASE, pdf_href)
            logger.info(f"[Welsh Parliament] Register of interests PDF "
                        f"(newest published, to {pdf_year or 'unknown'}): {pdf_url}")
            records = self._parse_interests_pdf(pdf_url, members)
            if not records:
                # 0 records here is the genuine source state, not a parse failure:
                # the newest consolidated register on the site is the previous
                # term's end-of-term archive, whose Members predate the current
                # Senedd. The in-term register lives on per-member profile pages
                # (not scraped here) and no consolidated PDF exists for it yet.
                logger.info(
                    "[Welsh Parliament] 0 register records — the newest published "
                    "consolidated register is a prior-term archive; the current "
                    "Senedd's consolidated register is not yet published."
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

    # Matches numbered category headings in the register PDF, e.g.
    # "1. Remunerated employment, office, profession etc." or "2) Sponsorship".
    _PDF_CATEGORY_RE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.{3,120})$")

    def _parse_interests_pdf(self, pdf_url: str, members: List[Dict]) -> List[Dict]:
        """Download the consolidated register-of-interests PDF and parse it with PyMuPDF.

        Layout (per the published Senedd register): each Member's name appears as
        a heading, followed by numbered category headings ("1. Remunerated
        employment...", "2. Sponsorship...", etc.), each followed by free-text
        entries (or "I have no relevant interests to declare"). We walk the
        extracted text line-by-line, switching the "current member" whenever a
        line exactly matches a name from the known member roster, and the
        "current category" whenever a line matches the numbered-heading pattern.
        """
        records: List[Dict] = []
        full_url = pdf_url if pdf_url.startswith("http") else urljoin(_BASE, pdf_url)

        try:
            import fitz  # PyMuPDF
        except Exception as e:
            logger.warning(
                f"[Welsh Parliament] PyMuPDF unavailable ({type(e).__name__}: {e}) — "
                "register-of-interests PDF parsing skipped. Install with: pip install pymupdf"
            )
            return records

        resp = self._get(full_url, accept="application/pdf,*/*", timeout=90)
        if not resp:
            logger.warning(f"[Welsh Parliament] Could not download interests PDF: {full_url}")
            return records

        try:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception as e:
            logger.warning(f"[Welsh Parliament] Could not parse interests PDF {full_url}: {type(e).__name__}: {e}")
            return records

        if not text.strip():
            logger.warning(f"[Welsh Parliament] Interests PDF {full_url} produced no extractable text")
            return records

        # Build a lookup of known member names so heading lines can be matched
        # to a roster entry (the PDF prints "Forename Surname", same as our records).
        member_by_name = {m["name"].strip().lower(): m for m in members if m.get("name")}

        current_member: Optional[Dict] = None
        current_category = ""
        buffer: List[str] = []

        def flush():
            if current_member is None or not buffer:
                return
            entry_text = " ".join(b for b in buffer if b).strip()
            if len(entry_text) >= 5:
                entry_date = self._extract_date_from_text(entry_text)
                if not entry_date and not hasattr(self, "_no_date_diag_logged"):
                    # Confirm whether the absence of a parsed date reflects the
                    # source text genuinely carrying no date (a structural fact
                    # about the register) or a format our regexes don't cover.
                    self._no_date_diag_logged = True
                    logger.warning(
                        f"[Welsh Parliament] No date extracted from interest entry — "
                        f"sample text: {entry_text[:300]!r}"
                    )
                records.append(self._make_record(
                    data_type="register_of_interests",
                    member=current_member,
                    date=entry_date,
                    text=entry_text,
                    title=current_category,
                    metadata={"source_format": "pdf"},
                    source_url=full_url,
                ))

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            matched_member = member_by_name.get(line.lower())
            if matched_member is not None:
                flush()
                buffer = []
                current_member = matched_member
                current_category = ""
                continue

            if current_member is None:
                continue  # skip front matter / TOC before the first member heading

            cat_match = self._PDF_CATEGORY_RE.match(line)
            if cat_match:
                flush()
                buffer = []
                current_category = cat_match.group(2).strip()
                continue

            buffer.append(line)

        flush()

        if not records:
            logger.warning(
                f"[Welsh Parliament] 0 interest records parsed from PDF {full_url} "
                f"({len(text)} chars extracted, {len(member_by_name)} known member names) — "
                f"text sample: {text[:400]!r}"
            )
        logger.info(f"[Welsh Parliament] {len(records)} interest records parsed from PDF")
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
        # Real result pages contain WQ/AQ/OQ numbers in the VISIBLE text.
        # (Don't count <article>/[class*=result] elements — the SPA shell ships
        #  empty template articles that falsely look like results.)
        has_results = bool(re.search(r"(WQ|AQ|OQ)[- ]?\d{3,}", text))
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

                    # Junk guard: a real question card has a WQ/AQ id OR a member name.
                    # Cards with neither are SPA template/nav chrome — skip them so we
                    # don't emit thousands of empty records and fall through to the
                    # order-paper path instead.
                    if not q_id and not member_name:
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
                    logger.debug(
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

    def _name_from_row(self, anchor_el, soup_row) -> str:
        """Try to extract a member name from the HTML context surrounding a question link.

        The order-paper listing is SSR.  The MS name is typically in a sibling <td>,
        a <dt>/<dd> pair, a span with a class hint, or a "Tabled by: Name" text pattern.
        Returns the best candidate or an empty string.
        """
        if not soup_row:
            return ""
        href = anchor_el.get("href", "") if anchor_el else ""

        # Table rows: look for a cell that is NOT the WQ-link cell and looks like a name
        tds = soup_row.select("td")
        for td in tds:
            linked = td.find("a", href=href)
            if linked:
                continue  # This is the WQ-ID cell
            candidate = td.get_text(strip=True)
            words = candidate.split()
            # A name: 2–6 words, each starting uppercase, nothing numeric
            if 2 <= len(words) <= 6 and all(
                w and w[0].isupper() for w in words if w.isalpha()
            ) and not re.search(r"\d", candidate):
                return candidate

        # dt/dd pair in any parent container
        for dt in soup_row.select("dt"):
            if any(kw in dt.get_text(strip=True).lower() for kw in ("tabled", "asked", "member", "by")):
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(strip=True)

        # CSS-class hints
        for sel in (
            "[class*='member-name']", "[class*='membername']",
            "[class*='tabled-by']", "[class*='asked-by']",
            "[class*='author']", ".member", ".ms",
        ):
            el = soup_row.select_one(sel)
            if el and el != anchor_el:
                candidate = el.get_text(strip=True)
                if candidate and len(candidate) > 2:
                    return candidate

        # "Tabled by: Name" / "Asked by Name" / "By: Name" in raw row text
        row_text = soup_row.get_text(separator=" ", strip=True)
        m = re.search(
            r"(?:Tabled\s+by|Asked\s+by|By)[:\s]+([A-Z][a-zA-Záéíóú'\-]+(?:\s+[A-Z][a-zA-Záéíóú'\-]+){1,4})",
            row_text,
        )
        if m:
            return m.group(1).strip()

        return ""

    def _member_from_detail(self, soup) -> str:
        """Extract member name from an individual question detail page (SSR only)."""
        for sel in (
            ".member-name", ".asked-by", ".tabled-by",
            "[class*='member-name']", "[class*='asked-by']", "[class*='tabled-by']",
        ):
            el = soup.select_one(sel)
            if el:
                return el.get_text(strip=True)
        for dt in soup.select("dt"):
            if any(kw in dt.get_text(strip=True).lower() for kw in ("tabled", "asked", "member")):
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(strip=True)
        for el in soup.select("p, span, td, li"):
            txt = el.get_text(strip=True)
            m = re.match(r"(?:Asked|Tabled)\s+by[:\s]+(.+)", txt, re.I)
            if m:
                return m.group(1).strip()
        for el in soup.select("strong, b"):
            candidate = el.get_text(strip=True)
            words = candidate.split()
            if 2 <= len(words) <= 5 and all(w[0].isupper() for w in words if w):
                return candidate
        return ""

    def _fetch_questions_order_paper(self, from_date: Optional[str] = None,
                                     to_date: Optional[str] = None) -> List[Dict]:
        """Fetch written questions from the record.senedd.wales order paper pages.

        URL pattern: https://record.senedd.wales/OrderPaper/WrittenQuestions/DD-MM-YYYY/
        This is a confirmed SSR page listing questions submitted for each sitting day.
        Member names are extracted from the listing page row context first; individual
        question pages (record.senedd.wales/WrittenQuestion/WQ-NNNNN) are only visited
        if the listing page has no name AND the page is not a SPA shell.
        """
        records = []
        from_dt = date.fromisoformat(from_date) if from_date else date(2020, 1, 1)
        today = date.fromisoformat(to_date) if to_date else date.today()
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

            body_text = soup.get_text(separator=" ", strip=True)
            if len(body_text) < 300 or not re.search(r"WQ-?\d+|question|tabled|written", body_text, re.I):
                consecutive_empty += 1
                continue

            consecutive_empty = 0

            # ----------------------------------------------------------------
            # Path 1: confirmed order-paper structure (6th Senedd 2021-present)
            # <div class="itemContent writtenQuestion"> containing:
            #   span.name, span.area, a[href*='mgUserInfo'], span.title (WQ id),
            #   span.date ("Tabled on DD/MM/YYYY"), .itemContent__content (question),
            #   .itemContent__nested-item-content (answer)
            # ----------------------------------------------------------------
            wq_items = soup.select("div.itemContent.writtenQuestion")
            if wq_items:
                if not hasattr(self, "_op_item_logged"):
                    self._op_item_logged = True
                    logger.debug(
                        f"[Welsh Parliament] Order-paper itemContent structure ({day_str}): "
                        f"{len(wq_items)} items. First HTML: {str(wq_items[0])[:700]!r}"
                    )
                day_added = 0
                for item in wq_items:
                    name_el = item.select_one("span.name")
                    member_name = name_el.get_text(strip=True) if name_el else ""
                    area_el = item.select_one("span.area")
                    constituency = area_el.get_text(strip=True) if area_el else ""
                    uid_el = item.select_one("a[href*='mgUserInfo']")
                    member_id = ""
                    if uid_el:
                        uid_m = re.search(r"UID=(\d+)", uid_el.get("href", ""), re.I)
                        if uid_m:
                            member_id = uid_m.group(1)
                    title_el = item.select_one("span.title")
                    raw_id = title_el.get_text(strip=True) if title_el else ""
                    # Normalize WQ98479 → WQ-98479
                    if raw_id and re.match(r"WQ\d+$", raw_id, re.I):
                        q_id = "WQ-" + raw_id[2:]
                    else:
                        q_id = raw_id.upper()
                    if q_id in seen_ids:
                        continue
                    if q_id:
                        seen_ids.add(q_id)
                    date_el = item.select_one("span.date")
                    date_text = date_el.get_text(strip=True) if date_el else ""
                    dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_text)
                    q_date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else current.isoformat()
                    content_el = item.select_one(".itemContent__content")
                    q_text = content_el.get_text(separator=" ", strip=True) if content_el else ""
                    nested_el = item.select_one(".itemContent__nested-item-content")
                    answer = nested_el.get_text(separator=" ", strip=True) if nested_el else ""
                    combined = (f"Question: {q_text}\n\nAnswer: {answer}"
                                if (q_text and answer) else (q_text or answer or ""))
                    records.append(self._make_record(
                        data_type="question",
                        member={"id": member_id, "name": member_name,
                                "party": "", "constituency": constituency, "role": "MS"},
                        date=q_date,
                        text=combined,
                        title=q_id,
                        metadata={"question_type": "written", "question_id": q_id,
                                  "answer_text": answer},
                        source_url=url,
                    ))
                    day_added += 1
                logger.info(f"[Welsh Parliament] Questions: {day_added} from itemContent ({day_str})")
                continue

            # ----------------------------------------------------------------
            # Path 2: anchor links to /WrittenQuestion/WQ-NNNNN detail pages
            # ----------------------------------------------------------------
            listing_questions: list = []
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                if not re.search(r"/WrittenQuestion/WQ-?\d+|/Question/\d+", href, re.I):
                    continue
                q_url = href if href.startswith("http") else f"{_RECORD}{href}"
                q_id_match = re.search(r"WQ-?(\d+)", href, re.I)
                q_id = f"WQ-{q_id_match.group(1)}" if q_id_match else ""
                if q_id and q_id in seen_ids:
                    continue
                if q_id:
                    seen_ids.add(q_id)

                parent = (a.find_parent("tr") or a.find_parent("li")
                          or a.find_parent("article") or a.find_parent("div"))
                member_name = self._name_from_row(a, parent)
                listing_questions.append((q_url, q_id, member_name))

            if not listing_questions:
                # ----------------------------------------------------------------
                # Path 3: plain table/list rows containing a WQ id in text
                # ----------------------------------------------------------------
                day_added = 0
                first_row_logged = hasattr(self, "_op_inline_logged")
                for row in soup.select("tr, li, .question-item, article"):
                    row_text = row.get_text(" ", strip=True)
                    q_id_match = re.search(r"WQ-?(\d+)", row_text)
                    if not q_id_match:
                        continue
                    q_id = f"WQ-{q_id_match.group(1)}"
                    if q_id in seen_ids:
                        continue
                    seen_ids.add(q_id)
                    member_name = self._name_from_row(None, row)
                    if not first_row_logged:
                        first_row_logged = True
                        self._op_inline_logged = True
                        logger.debug(
                            f"[Welsh Parliament] Order-paper INLINE row ({q_id}): "
                            f"name={member_name!r} cells={[td.get_text(strip=True) for td in row.select('td')][:6]} "
                            f"HTML={str(row)[:600]!r}"
                        )
                    records.append(self._make_record(
                        data_type="question",
                        member={"id": "", "name": member_name,
                                "party": "", "constituency": "", "role": "MS"},
                        date=current.isoformat(),
                        text=row_text,
                        title=q_id,
                        metadata={"question_type": "written", "question_id": q_id},
                        source_url=url,
                    ))
                    day_added += 1
                continue

            logger.info(f"[Welsh Parliament] Questions: {len(listing_questions)} question links for {day_str}")
            if len(listing_questions) > MAX_QUESTION_DETAIL_PAGES:
                logger.warning(
                    f"[Welsh Parliament] Questions for {day_str}: {len(listing_questions)} links capped at "
                    f"{MAX_QUESTION_DETAIL_PAGES} (MAX_QUESTION_DETAIL_PAGES)"
                )
            for q_url, q_id, listing_member_name in listing_questions[:MAX_QUESTION_DETAIL_PAGES]:
                member_name = listing_member_name
                q_text = ""
                answer = ""
                subject = ""
                q_date = current.isoformat()

                # Only fetch the detail page when listing didn't give us a name
                if not member_name:
                    q_detail = self._html_get(q_url)
                    if q_detail and not self._is_spa_shell(q_detail):
                        member_name = self._member_from_detail(q_detail)
                        q_text_el = q_detail.select_one(
                            ".question-text, .question-body, [class*='question'], article p, main p"
                        )
                        q_text = q_text_el.get_text(strip=True) if q_text_el else ""
                        ans_el = q_detail.select_one(".answer-text, .answer-body, [class*='answer']")
                        answer = ans_el.get_text(strip=True) if ans_el else ""
                        date_el = q_detail.select_one("time[datetime], time, .date, [class*='date']")
                        if date_el:
                            q_date = date_el.get("datetime", date_el.get_text(strip=True))
                        subject_el = q_detail.select_one("h1, .subject, .title, [class*='subject']")
                        subject = subject_el.get_text(strip=True) if subject_el else ""
                    elif not member_name and q_id:
                        # SPA shell on record.senedd.wales — try the senedd.wales WordPress URL
                        wp_url = f"{_BASE}/senedd-business/written-questions/{q_id}/"
                        wp_detail = self._html_get(wp_url)
                        if wp_detail and not self._is_spa_shell(wp_detail):
                            member_name = self._member_from_detail(wp_detail)
                            if not q_text:
                                main_el = wp_detail.select_one("article, main, .entry-content")
                                q_text = main_el.get_text(separator=" ", strip=True)[:500] if main_el else ""
                            if not hasattr(self, "_wp_q_logged"):
                                self._wp_q_logged = True
                                logger.warning(
                                    f"[Welsh Parliament] WP question page {wp_url}: "
                                    f"member={member_name!r} text={q_text[:100]!r}"
                                )

                combined = f"Question: {q_text}\n\nAnswer: {answer}" if (q_text and answer) else (q_text or answer or "")
                records.append(self._make_record(
                    data_type="question",
                    member={"id": "", "name": member_name, "party": "", "constituency": "", "role": "MS"},
                    date=q_date,
                    text=combined,
                    title=subject or q_id,
                    metadata={"question_type": "written", "question_id": q_id, "answer_text": answer},
                    source_url=q_url,
                ))

        named = sum(1 for r in records if r.get("member", {}).get("name"))
        logger.info(f"[Welsh Parliament] Order paper questions: {len(records)} records, {named} with member names")
        return records

    def fetch_questions(self, from_date: Optional[str] = None,
                        to_date: Optional[str] = None) -> List[Dict]:
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
        records = self._fetch_questions_order_paper(from_date, to_date)
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
                if len(links_found) > MAX_QUESTION_DETAIL_PAGES:
                    logger.warning(
                        f"[Welsh Parliament] Questions: {len(links_found)} item links capped at "
                        f"{MAX_QUESTION_DETAIL_PAGES} (MAX_QUESTION_DETAIL_PAGES)"
                    )
                for href in links_found[:MAX_QUESTION_DETAIL_PAGES]:
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

    def _fetch_transcript_xml(self, meeting_id: str, meeting_date: str,
                              from_date: Optional[str], to_date: Optional[str],
                              records: List[Dict]) -> int:
        """Fetch a plenary meeting's English transcript export and parse contributions.

        record.senedd.wales/XMLExport/Download?meetingID=N&xmlDownloadType=EnglishTranscript
        returns a flat <dataroot> of <XML_Plenary-*_English> rows (one per spoken
        contribution) carrying Member_name_English, Contribution_English, MeetingDate
        and Agenda_item_english. Rows are matched by structure so the parser stays
        agnostic across Seneddau. Returns the number of records added.
        """
        url = f"{_RECORD}/XMLExport/Download"
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/xml,text/xml,*/*;q=0.8",
        })
        resp = self._get(url, params={"meetingID": meeting_id,
                                      "xmlDownloadType": "EnglishTranscript"}, timeout=90)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0
        ct = resp.headers.get("Content-Type", "")
        if "xml" not in ct and not resp.text.lstrip()[:20].lower().startswith("<?xml"):
            return 0
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            logger.warning(f"[Welsh Parliament] Transcript XML parse error meeting {meeting_id}: {e}")
            return 0
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]

        def _txt(parent, tag: str) -> str:
            e = parent.find(tag)
            return (e.text or "").strip() if e is not None and e.text else ""

        before = len(records)
        for row in root:
            # A contribution row carries Contribution_English (the element name
            # encodes the Senedd number: ...SixthSenedd_English / ...SeventhSenedd_English).
            text = self._strip_html(_txt(row, "Contribution_English"))
            if not text or len(text) < 3:
                continue
            v_date = (_txt(row, "MeetingDate") or meeting_date or "")[:10]
            if from_date and v_date and v_date < from_date:
                continue
            if to_date and v_date and v_date > to_date:
                continue
            records.append(self._make_record(
                data_type="plenary_speech",
                member={"id": _txt(row, "Member_Id"), "name": _txt(row, "Member_name_English"),
                        "party": "", "constituency": "", "role": "MS"},
                date=v_date,
                text=text,
                title=_txt(row, "Agenda_item_english"),
                metadata={"meeting_id": meeting_id,
                          "contribution_type": _txt(row, "contribution_type"),
                          "source_format": "xml"},
                source_url=f"{url}?meetingID={meeting_id}&xmlDownloadType=EnglishTranscript",
            ))
        added = len(records) - before
        if added:
            logger.info(f"[Welsh Parliament] Meeting {meeting_id}: {added} plenary contributions")
        return added

    def fetch_plenary_business(self, from_date: Optional[str] = None,
                               to_date: Optional[str] = None) -> List[Dict]:
        """Plenary proceedings via the Senedd's XML transcript export.

        Enumerate plenary meetings from the XMLExport listing, then parse each
        meeting's English transcript into per-speaker contributions — the same
        reliable structured source used for votes, instead of scraping the
        JS-rendered Record-of-Proceedings pages (which yielded malformed speaker
        names and dates).
        """
        records: List[Dict] = []
        meetings = self._fetch_meeting_ids_wales(from_date, to_date, votes_only=False)
        if not meetings:
            logger.warning("[Welsh Parliament] No plenary meetings found for transcripts")
            return records
        logger.info(f"[Welsh Parliament] Fetching transcripts for {len(meetings)} plenary meetings...")
        hits = 0
        for i, m in enumerate(meetings):
            if i and i % 10 == 0:
                logger.info(f"[Welsh Parliament] Plenary: {i}/{len(meetings)} meetings "
                            f"processed ({len(records)} records so far)")
            if self._fetch_transcript_xml(m["id"], m.get("date", ""), from_date, to_date, records):
                hits += 1
        logger.info(f"[Welsh Parliament] {hits}/{len(meetings)} meetings had transcripts; "
                    f"{len(records)} plenary records fetched")
        return records

    def _fetch_meeting_ids_wales(self, from_date: Optional[str] = None,
                                 to_date: Optional[str] = None,
                                 votes_only: bool = True,
                                 max_pages: int = 200) -> List[Dict]:
        """Enumerate plenary meetings across the full historical archive.

        The plain XMLExport filter form (SelectedCommitteeID=908 for the current
        Plenary committee) always caps out at that committee's most-recent ~15
        rows, no matter what Start/End dates are sent — the 908 ID is reissued
        fresh every Senedd term, so it only ever has the current term's history.

        The site's own "See More" button (record.senedd.wales/XMLExport/SeeMore)
        is real, working pagination, though: it walks the *unfiltered* listing
        (all committees, ~2,900+ meetings as of 2026) 16 rows at a time, newest
        first, and does not require any session/cookie state — confirmed live
        2026-09-05. Filtering by committee **name** containing "Plenary" (rather
        than by ID) is what actually reaches multiple terms' worth of Plenary
        history, since each term's Plenary sits under a different ID but is
        always named "Plenary" / "Plenary - Sixth Senedd" / etc.

        Each listing row carries the meeting date and one download link per
        export type, so a row that links xmlDownloadType=Votes is a plenary
        meeting that actually held divisions.

        Returns [{"id", "date", "has_votes"}] newest-first. With votes_only=True
        (the votes path) only division-bearing meetings are returned; with False
        (the plenary path) every plenary meeting is returned. Paging stops once
        a whole page's oldest row predates `from_date` (default: 2021-05-06,
        the start of the 6th Senedd), the site reports no more pages, or
        `max_pages` is hit (a full since-2021 pull is ~185 pages).
        """
        effective_from = from_date or "2021-05-06"    # start of the 6th Senedd
        seen: set = set()
        all_meetings: List[Dict] = []
        page = 1
        hit_cap = False
        while True:
            resp = self._get(
                f"{_RECORD}/XMLExport/SeeMore",
                params={"Committee": "0", "Start": "0001-01-01", "End": "0001-01-01",
                        "Page": page, "_": int(time.time() * 1000)},
                timeout=30,
            )
            if not resp or not resp.ok:
                break
            try:
                payload = resp.json()
            except ValueError:
                logger.warning(f"[Welsh Parliament] XMLExport/SeeMore page {page}: non-JSON response")
                break
            html_fragment = payload.get("Html", "")
            if not html_fragment.strip():
                break

            soup = BeautifulSoup(f"<table>{html_fragment}</table>", "lxml")
            for m in self._parse_meeting_rows(soup, effective_from, to_date):
                if m["id"] not in seen:
                    seen.add(m["id"])
                    all_meetings.append(m)

            # The unfiltered listing is globally date-sorted across every committee,
            # so the oldest row on this page (any committee, not just Plenary) tells
            # us whether paging further could still be within range.
            row_dates = []
            for tr in soup.find_all("tr"):
                dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", tr.get_text(" ", strip=True))
                if dm:
                    row_dates.append(f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}")
            oldest_on_page = min(row_dates) if row_dates else None

            if page % 20 == 0:
                logger.info(f"[Welsh Parliament] XMLExport/SeeMore: page {page}, "
                            f"{len(all_meetings)} Plenary meetings so far "
                            f"(oldest row seen: {oldest_on_page})")

            if not payload.get("MoreToShow"):
                break
            if oldest_on_page and oldest_on_page < effective_from:
                break
            if page >= max_pages:
                hit_cap = True
                break
            page += 1

        if hit_cap:
            logger.warning(f"[Welsh Parliament] XMLExport/SeeMore: hit the {max_pages}-page "
                           f"safety cap before reaching {effective_from}")

        all_meetings.sort(key=lambda m: m["date"], reverse=True)
        result = [m for m in all_meetings if m["has_votes"]] if votes_only else all_meetings
        if all_meetings:
            logger.info(f"[Welsh Parliament] XMLExport/SeeMore: {len(all_meetings)} plenary "
                        f"meetings found across {page} page(s) "
                        f"({sum(1 for m in all_meetings if m['has_votes'])} with divisions); "
                        f"returning {len(result)}")
        else:
            logger.warning(f"[Welsh Parliament] XMLExport/SeeMore returned no plenary meetings "
                           f"in range {effective_from}–{to_date or '(today)'}")
        return result

    @staticmethod
    def _parse_meeting_rows(soup, from_date: Optional[str] = None,
                            to_date: Optional[str] = None) -> List[Dict]:
        """Parse XMLExport listing <tr> rows into {id, date, has_votes} (Plenary only).

        A row looks like:
          24/06/2026 13:30 Plenary ... <a href="...meetingID=16077&xmlDownloadType=Votes">Votes</a>
        so the date is the leading DD/MM/YYYY and has_votes is the presence of a
        Votes download link.
        """
        if not soup:
            return []
        out: List[Dict] = []
        seen: set = set()
        for tr in soup.find_all("tr"):
            links = tr.find_all("a", href=re.compile(r"meetingID=\d+", re.I))
            if not links:
                continue
            row_text = tr.get_text(" ", strip=True)
            if "Plenary" not in row_text or "Business Committee" in row_text:
                continue
            mid = re.search(r"meetingID=(\d+)", links[0]["href"], re.I).group(1)
            if mid in seen:
                continue
            seen.add(mid)
            dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", row_text)
            iso = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else ""
            if from_date and iso and iso < from_date:
                continue
            if to_date and iso and iso > to_date:
                continue
            has_votes = any("xmlDownloadType=Votes" in a.get("href", "") for a in links)
            out.append({"id": mid, "date": iso, "has_votes": has_votes})
        return sorted(out, key=lambda m: m["date"], reverse=True)

    def _form_post(self, url: str, data: Dict):
        """POST a form with browser headers; return BeautifulSoup or None."""
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        resp = None
        try:
            resp = self.session.post(url, data=data, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            logger.warning(f"[Welsh Parliament] XMLExport POST failed: {type(e).__name__}: {e}")
        finally:
            self.session.headers.clear()
            self.session.headers.update(saved)
        if not resp or not resp.ok:
            return None
        return BeautifulSoup(resp.text, "lxml")

    def _fetch_votes_xml_export(self, meeting_id: str, meeting_date: str,
                                 from_date: Optional[str], records: List[Dict],
                                 to_date: Optional[str] = None) -> int:
        """Fetch and parse a meeting's division votes from the Senedd Votes export.

        URL: record.senedd.wales/XMLExport/Download?meetingID=N&xmlDownloadType=Votes
        The XML is a flat <dataroot> of <XML_Plenary-SixthSenedd_Vote> rows, one per
        member per division, each carrying the motion text (Vote_Name_English), the
        member's result (Results_Result: For/Against/Abstain/DidNotVote), the running
        totals, and the overall outcome (Vote_Result_English).  Returns the number of
        vote records added.

        (The older EnglishTranscript export carries the spoken proceedings, not the
        divisions — votes are exposed only via xmlDownloadType=Votes.)
        """
        url = f"{_RECORD}/XMLExport/Download"
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/xml,text/xml,*/*;q=0.8",
        })
        resp = self._get(url, params={"meetingID": meeting_id, "xmlDownloadType": "Votes"},
                         timeout=60)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0

        ct = resp.headers.get("Content-Type", "")
        body = resp.text
        if "xml" not in ct and not body.lstrip()[:20].lower().startswith("<?xml"):
            # Error page or empty body -> this meeting has no votes export
            return 0
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            logger.warning(f"[Welsh Parliament] Votes XML parse error for meeting {meeting_id}: {e}")
            return 0

        # Strip namespace prefixes so element lookups are simple
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]

        def _txt(parent, tag: str) -> str:
            e = parent.find(tag)
            return e.text.strip() if e is not None and e.text else ""

        before = len(records)
        # Vote rows are the repeated children of <dataroot>; the element name
        # encodes the Senedd number (...-SixthSenedd_Vote, ...-SeventhSenedd_Vote),
        # so match by structure (a Member_name_English child) to stay agnostic.
        for row in root:
            if row.find("Member_name_English") is None:
                continue
            name = _txt(row, "Member_name_English")
            if not name:
                continue
            v_date = (_txt(row, "MeetingDate") or meeting_date or "")[:10]
            if from_date and v_date and v_date < from_date:
                continue
            if to_date and v_date and v_date > to_date:
                continue
            raw_dir = _txt(row, "Results_Result")
            direction = _WALES_VOTE_DIR.get(raw_dir, (raw_dir or "").lower())
            motion = _txt(row, "Vote_Name_English") or _txt(row, "Vote_Name")
            records.append(self._make_record(
                data_type="vote",
                member={"id": _txt(row, "Member_Id"), "name": name, "party": "",
                        "constituency": "", "role": "MS"},
                date=v_date,
                text=f"Voted {direction} on: {motion}",
                title=motion,
                metadata={
                    "vote_direction": direction,
                    "division_result": _txt(row, "Vote_Result_English"),
                    "meeting_id": meeting_id,
                    "division_id": _txt(row, "Contribution_ID"),
                    "ayes": _txt(row, "VotesTotalFor"),
                    "noes": _txt(row, "VotesTotalAgainst"),
                    "abstentions": _txt(row, "VotesTotalAbstain"),
                    "agenda_item": _txt(row, "Agenda_item_english"),
                },
                source_url=f"{url}?meetingID={meeting_id}&xmlDownloadType=Votes",
            ))
        added = len(records) - before
        if added:
            logger.info(f"[Welsh Parliament] Meeting {meeting_id}: {added} vote records")
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

    def fetch_votes_on_division(self, from_date: Optional[str] = None,
                                to_date: Optional[str] = None) -> List[Dict]:
        records: List[Dict] = []

        # Primary path: enumerate division-bearing plenary meetings from the
        # XMLExport listing, then parse each meeting's Votes export.
        meetings = self._fetch_meeting_ids_wales(from_date, to_date)
        if meetings:
            logger.info(f"[Welsh Parliament] Fetching votes for {len(meetings)} "
                        f"division-bearing plenary meetings...")
            hits = 0
            for i, m in enumerate(meetings):
                if i and i % 10 == 0:
                    logger.info(f"[Welsh Parliament] Votes: {i}/{len(meetings)} meetings "
                                f"processed ({len(records)} records so far)")
                added = self._fetch_votes_xml_export(m["id"], m.get("date", ""),
                                                     from_date, records, to_date)
                if added:
                    hits += 1
            logger.info(f"[Welsh Parliament] {hits}/{len(meetings)} meetings yielded votes; "
                        f"{len(records)} vote records fetched")
            if records:
                return records

        # Fallback: the record.assembly.wales/Search division filter (kept for
        # resilience; the SPA usually returns nothing).
        search_records = self._fetch_votes_search(from_date)
        if search_records:
            logger.info(f"[Welsh Parliament] {len(search_records)} vote records via Search page")
            return search_records

        logger.warning("[Welsh Parliament] No vote records found")
        return records
