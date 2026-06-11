"""
Scottish Parliament scraper.

Members are fetched from the public OData API at https://data.parliament.scot/api.
All other entity endpoints on that API return 404; interests, questions, plenary,
and votes are scraped from https://www.parliament.scot with a browser User-Agent.
"""
import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS, MAX_QUESTION_DETAIL_PAGES

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
        # Try expanding MemberParties navigation property inline
        expand_rows = []
        try:
            url = f"{_API}/Members"
            resp = self._get(url, params={"$format": "json", "$top": 1000,
                                           "$expand": "MemberParties"})
            if resp and resp.ok:
                data = resp.json()
                expand_rows = data if isinstance(data, list) else data.get("value", [])
                if expand_rows and not hasattr(self, "_expand_logged"):
                    self._expand_logged = True
                    sample = expand_rows[0]
                    mp = sample.get("MemberParties")
                    logger.warning(f"[Scottish Parliament] Members?$expand=MemberParties sample MemberParties={mp!r:.200}")
        except Exception:
            pass
        rows = expand_rows or self._odata_get("Members")
        if rows:
            logger.warning(f"[Scottish Parliament] Members OData sample fields: {list(rows[0].keys())} | sample={dict(list(rows[0].items())[:8])!r:.400}")
        members = []
        for m in rows:
            member_id = str(
                m.get("PersonID") or m.get("PersonId") or m.get("MemberID")
                or m.get("MemberId") or m.get("Id") or m.get("id") or ""
            )
            # ParliamentaryName is "Surname, Forename" — reverse to "Forename Surname"
            parl_name = m.get("ParliamentaryName") or ""
            if parl_name and "," in parl_name:
                surname, _, forename = parl_name.partition(",")
                full_name = f"{forename.strip()} {surname.strip()}"
            else:
                full_name = (parl_name or m.get("PreferredName") or m.get("DisplayName")
                             or m.get("MemberName") or m.get("Name") or "")
            # Party — try inline expanded MemberParties first, then direct fields
            party = (
                m.get("PartyName") or m.get("Party") or m.get("PartyAbbreviation")
                or m.get("PartyGroupName") or m.get("PoliticalGroupName") or ""
            )
            if not party:
                mp_list = m.get("MemberParties")
                if isinstance(mp_list, list) and mp_list:
                    latest = max(mp_list, key=lambda x: str(x.get("ValidFromDate") or ""))
                    party = (latest.get("PartyName") or latest.get("Party")
                             or latest.get("PartyAbbreviation") or latest.get("Name") or "")
                elif isinstance(mp_list, dict):
                    party = (mp_list.get("PartyName") or mp_list.get("Party")
                             or mp_list.get("Name") or "")
            constituency = (
                m.get("ConstituencyName") or m.get("RegionName")
                or m.get("Constituency") or m.get("Region") or ""
            )
            members.append({
                "id": member_id,
                "name": full_name,
                "party": party,
                "constituency": constituency,
                "role": "MSP",
                "status": "current" if m.get("IsCurrent") else "historical",
            })
        # Attempt to enrich party info from the PersonParties / Parties OData entities
        if members:
            self._enrich_msp_parties(members)
        logger.info(f"[Scottish Parliament] {len(members)} MSPs fetched")
        return members

    def _enrich_msp_parties(self, members: List[Dict]) -> None:
        """Fill in MSP party by joining the MemberParties and Parties OData entities.

        data.parliament.scot exposes:
          - MemberParties: ID, PersonID, PartyID, ValidFromDate, ValidUntilDate
          - Parties:       ID, (Party)Name  — the human-readable party name

        MemberParties only carries a numeric PartyID, so we build a PartyID→name
        map from Parties first, then assign each member their CURRENT party (the
        membership row with no/future ValidUntilDate, else the latest ValidFromDate).
        """
        id_lookup = {m["id"]: m for m in members if m["id"]}

        # 1. Build PartyID -> party name map from the Parties entity.
        party_rows = self._odata_get("Parties")
        if not party_rows:
            logger.warning("[Scottish Parliament] Parties entity returned no rows — cannot enrich parties")
            return
        if not hasattr(self, "_parties_logged"):
            self._parties_logged = True
            logger.warning(f"[Scottish Parliament] Parties fields: {list(party_rows[0].keys())} | sample={party_rows[0]!r:.300}")
        party_name_by_id: Dict[str, str] = {}
        for pr in party_rows:
            pid = str(pr.get("ID") or pr.get("Id") or pr.get("PartyID") or "")
            name = (pr.get("PartyName") or pr.get("Name")
                    or pr.get("ActualPartyName") or pr.get("PreferredName")
                    or pr.get("PartyAbbreviation") or "")
            if pid and name:
                party_name_by_id[pid] = name

        # 2. Pull MemberParties (PersonID + PartyID + validity) and pick current party.
        mp_rows = self._odata_get("MemberParties")
        if not mp_rows:
            logger.warning("[Scottish Parliament] MemberParties returned no rows — cannot enrich parties")
            return
        if not hasattr(self, "_memberparties_logged"):
            self._memberparties_logged = True
            logger.warning(f"[Scottish Parliament] MemberParties fields: {list(mp_rows[0].keys())} | sample={mp_rows[0]!r:.300}")

        # Group membership rows per person so we can choose the most recent/current.
        per_person: Dict[str, list] = {}
        for row in mp_rows:
            pid = str(row.get("PersonID") or row.get("PersonId") or row.get("MemberID") or "")
            if pid:
                per_person.setdefault(pid, []).append(row)

        def _sort_key(r: Dict):
            # Current memberships (no ValidUntilDate) sort highest; then by ValidFromDate.
            until = str(r.get("ValidUntilDate") or "")
            is_current = 1 if not until else 0
            return (is_current, str(r.get("ValidFromDate") or ""))

        filled = 0
        for pid, rows in per_person.items():
            if pid not in id_lookup or id_lookup[pid].get("party"):
                continue
            best = max(rows, key=_sort_key)
            party_id = str(best.get("PartyID") or best.get("PartyId") or "")
            name = party_name_by_id.get(party_id, "")
            if name:
                id_lookup[pid]["party"] = name
                filled += 1
        logger.info(
            f"[Scottish Parliament] Party enrichment via MemberParties⋈Parties: "
            f"{filled}/{len(id_lookup)} members filled ({len(party_name_by_id)} parties)"
        )

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests — scraped from parliament.scot
    # (data.parliament.scot/api does not expose this entity publicly)
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        records = []

        # 1. Try OData API first — endpoints that might expose interests data
        odata_interest_candidates = [
            "RegisteredInterests", "MemberInterests", "Interests",
            "MSPInterests", "RegisterOfInterests", "MemberRegisteredInterests",
        ]
        rows, endpoint = self._odata_try(odata_interest_candidates)
        if rows:
            member_lookup_id = {m["id"]: m for m in members}
            member_lookup_name = {m["name"].lower(): m for m in members}
            for row in rows:
                member_id = str(row.get("PersonId", row.get("MemberID", row.get("MemberId", ""))))
                member_name = row.get("MemberName", row.get("Name", ""))
                member = (member_lookup_id.get(member_id)
                          or member_lookup_name.get(member_name.lower(), {
                              "id": member_id, "name": member_name,
                              "party": "", "constituency": "", "role": "MSP",
                          }))
                text = row.get("Interest", row.get("Description", row.get("Text", "")))
                if not text:
                    continue
                records.append(self._make_record(
                    data_type="register_of_interests",
                    member=member,
                    date=row.get("DateRegistered", row.get("Date", "")),
                    text=text,
                    title=row.get("Category", row.get("CategoryName", "")),
                    source_url=f"{_API}/{endpoint}",
                ))
            logger.info(f"[Scottish Parliament] {len(records)} interest records fetched via OData")
            return records

        # 2. Scrape from parliament.scot.  URL structure has changed across sessions;
        #    try all known patterns, loading each and checking for actual interest content.
        interest_candidates = [
            f"{_WEB}/msps/register-of-members-interests/",
            f"{_WEB}/msps/register-of-members-interests",
            f"{_WEB}/msps/interests/",
            f"{_WEB}/msps/interests",
            f"{_WEB}/msps/members-interests-and-lobbying/register-of-interests",
            f"{_WEB}/msps/members-interests-and-lobbying/",
            f"{_WEB}/msps/members-interests-and-lobbying",
            f"{_WEB}/msps/members-interests/",
            f"{_WEB}/msps/members-interests",
            f"{_WEB}/msps/members-interests/register-of-interests",
            f"{_WEB}/msps/members-interests/register-of-interests/",
            f"{_WEB}/msps/register-of-interests",
            f"{_WEB}/msps/",
        ]

        # The current Register of Interests is published as a single consolidated
        # PDF covering every MSP (the same pattern the Senedd uses for Wales) —
        # e.g. ".../previous-register-of-interests-pdfs/register-of-interests-
        # for-the-parliamentary-year-13-may-2025-to-8-april-2026.pdf". The landing
        # page links the *current* register alongside an archive of every previous
        # year, so pick the link whose year is newest (the archive's oldest entry
        # is 2016 — taking the first match in DOM order grabbed that by mistake).
        def _find_interest_pdf_link(s: BeautifulSoup) -> str:
            best_href, best_year = "", -1
            for a in s.select("a[href*='.pdf']"):
                href = a.get("href", "")
                haystack = f"{href} {a.get_text(strip=True)}".lower()
                if "interest" not in haystack or "register" not in haystack:
                    continue
                years = [int(y) for y in re.findall(r"20\d{2}", haystack)]
                year = max(years) if years else 0
                if year > best_year:
                    best_href, best_year = href, year
            return best_href

        for candidate in interest_candidates:
            cand_soup = self._html_get(candidate)
            if not cand_soup:
                continue
            pdf_href = _find_interest_pdf_link(cand_soup)
            if pdf_href:
                pdf_url = pdf_href if pdf_href.startswith("http") else urljoin(_WEB, pdf_href)
                logger.info(f"[Scottish Parliament] Register of interests is a PDF — downloading and parsing: {pdf_url}")
                return self._parse_interests_pdf(pdf_url, members)

        def _has_interest_content(s: BeautifulSoup) -> bool:
            # Check the MAIN CONTENT area only — the site nav always contains
            # "About the Register of Interests" which would cause a false-positive match.
            main_el = (s.find("main")
                       or s.find("div", class_=re.compile(r"\bmain\b|\bcontent\b", re.I))
                       or s.find("body"))
            text_lower = main_el.get_text(separator=" ", strip=True).lower() if main_el else ""
            # Strip the nav — parliament.scot puts <nav> inside <main>
            for nav in (main_el.find_all("nav") if main_el else []):
                nav_text = nav.get_text(separator=" ", strip=True).lower()
                text_lower = text_lower.replace(nav_text, "")
            return any(kw in text_lower for kw in (
                "registered interest", "financial interest", "shareholding",
                "heritable property", "nature of interest", "category of interest"))

        def _try_load(fetch_fn, label: str):
            """Walk interest_candidates (and their sub-links) using `fetch_fn`,
            returning (soup, url) for the first page with real interest content."""
            for candidate in interest_candidates:
                resp_soup = fetch_fn(candidate)
                if not resp_soup:
                    if not label:
                        logger.warning(f"[Scottish Parliament] Could not load interests page: {candidate}")
                    continue
                if _has_interest_content(resp_soup):
                    logger.info(f"[Scottish Parliament] Loaded interests page with content{label}: {candidate}")
                    return resp_soup, candidate
                if not label:
                    body = resp_soup.find("body")
                    snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
                    logger.warning(f"[Scottish Parliament] Loaded {candidate} but no interest keywords — snippet: {snippet}")
                # Even if it's a general page, follow links whose href OR visible text
                # mentions interests/register so we reach the actual register page.
                sub_links = []
                for a in resp_soup.select("a[href]"):
                    href = a.get("href", "")
                    if not href or not (href.startswith("/") or href.startswith("http")):
                        continue
                    link_text = a.get_text(strip=True).lower()
                    if re.search(r"interest|register", href, re.I) or re.search(r"interest|register", link_text):
                        sub_links.append(href)
                if sub_links:
                    logger.info(f"[Scottish Parliament] Following interest sub-links{label} from {candidate}: {sub_links[:5]}")
                    for sub_href in sub_links[:5]:
                        sub_url = sub_href if sub_href.startswith("http") else f"{_WEB}{sub_href}"
                        if sub_url in interest_candidates:
                            continue  # already tried
                        sub_soup = fetch_fn(sub_url)
                        if sub_soup and _has_interest_content(sub_soup):
                            logger.info(f"[Scottish Parliament] Found interests content{label} at sub-link: {sub_url}")
                            return sub_soup, sub_url
            return None, ""

        soup, url = _try_load(self._html_get, "")

        if not soup:
            # The site is built on a JS framework (React/Angular-style SPA) — plain
            # HTTP often returns an empty shell with the real content injected
            # client-side. Re-walk the same candidates through a headless browser.
            logger.info("[Scottish Parliament] No interest content via plain HTTP — retrying with headless browser render")
            soup, url = _try_load(
                lambda u: self._browser_get(u, wait_selector="main, details, .member-interests, article, section"),
                " (rendered)")

        if not soup:
            logger.warning("[Scottish Parliament] All interest page candidates failed")
            logger.info(f"[Scottish Parliament] {len(records)} interest records fetched")
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
            # The page passed the keyword check (it IS an interests page) but our
            # section/name selectors found nothing — dump its real structure so
            # the selectors can be targeted at the actual markup next time.
            sections = soup.select("details, .member-interests, article, section")
            all_cls = sorted({c for el in soup.select("[class]") for c in el.get("class", [])})
            sample_links = [a.get("href", "") for a in soup.select("a[href]")
                            if re.search(r"msp|member|interest", a.get("href", ""), re.I)][:10]
            logger.warning(
                f"[Scottish Parliament] Interests page structure dump {url}: "
                f"{len(sections)} candidate sections | css_classes(first 40)={all_cls[:40]} | "
                f"msp/interest-ish links={sample_links}"
            )
        logger.info(f"[Scottish Parliament] {len(records)} interest records fetched")
        return records

    # Section headings in the consolidated register read e.g. "Category 1:
    # Remuneration" or "1. Remuneration" — match either, same shape as Welsh's.
    _PDF_CATEGORY_RE = re.compile(r"^\s*(?:category\s*)?(\d{1,2})[.):]\s+(.{3,120})$", re.I)
    # Each MSP's section is introduced by a "Member's Name: <name>" heading. The
    # PDF uses a *typographic* apostrophe (U+2019) in "Member's", so the
    # apostrophe class must cover the curly/modifier variants, not just U+0027 —
    # matching only the straight quote silently failed to find any member at all.
    # The name may sit on the same line after the colon, or on the next line.
    _PDF_MEMBER_HEADING_RE = re.compile(
        r"^member['‘’ʼ]?s?\s*name\s*:?\s*(.*)$", re.I)
    # Running page headers/footers (the document title, bare page numbers) get
    # interleaved into the extracted text — drop them so they don't pollute the
    # free-text entries we accumulate.
    _PDF_BOILERPLATE_RE = re.compile(
        r"^(register of members['‘’ʼ]?\s*interests|page\s*\d+|\d+)$", re.I)

    def _parse_interests_pdf(self, pdf_url: str, members: List[Dict]) -> List[Dict]:
        """Download the consolidated register-of-interests PDF and parse it with PyMuPDF.

        Layout (per the published register): each MSP's section opens with a
        "Member's Name: <name>" heading, followed by numbered/categorised
        headings ("1. Remuneration...", "Category 2: ...", etc.), each followed
        by free-text entries (or "I have no relevant interests to declare"). We
        walk the extracted text line-by-line, switching the "current member"
        whenever a heading line names one (or a line exactly matches a known
        roster name, as a fallback), and the "current category" whenever a line
        matches the numbered-heading pattern.
        """
        records: List[Dict] = []
        full_url = pdf_url if pdf_url.startswith("http") else urljoin(_WEB, pdf_url)

        try:
            import fitz  # PyMuPDF
        except Exception as e:
            logger.warning(
                f"[Scottish Parliament] PyMuPDF unavailable ({type(e).__name__}: {e}) — "
                "register-of-interests PDF parsing skipped. Install with: pip install pymupdf"
            )
            return records

        resp = self._get(full_url, accept="application/pdf,*/*", timeout=90)
        if not resp:
            logger.warning(f"[Scottish Parliament] Could not download interests PDF: {full_url}")
            return records

        try:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception as e:
            logger.warning(f"[Scottish Parliament] Could not parse interests PDF {full_url}: {type(e).__name__}: {e}")
            return records

        if not text.strip():
            logger.warning(f"[Scottish Parliament] Interests PDF {full_url} produced no extractable text")
            return records

        member_by_name = {m["name"].strip().lower(): m for m in members if m.get("name")}

        def _resolve_member(name: str) -> Dict:
            return member_by_name.get(name.strip().lower(), {
                "id": "", "name": name.strip(), "party": "",
                "constituency": "", "role": "MSP",
            })

        current_member: Optional[Dict] = None
        current_category = ""
        buffer: List[str] = []

        def flush():
            if current_member is None or not buffer:
                return
            entry_text = " ".join(b for b in buffer if b).strip()
            if len(entry_text) >= 5:
                records.append(self._make_record(
                    data_type="register_of_interests",
                    member=current_member,
                    date=self._extract_date_from_text(entry_text),
                    text=entry_text,
                    title=current_category,
                    metadata={"source_format": "pdf"},
                    source_url=full_url,
                ))

        def _same_member(name: str) -> bool:
            return bool(current_member) and \
                current_member.get("name", "").strip().lower() == name.strip().lower()

        # "Member's Name:" repeats as a running page header throughout each MSP's
        # section, and the name sometimes lands on the line *after* the label —
        # so track whether we're waiting for a name, and ignore a heading that
        # just re-announces the member we're already inside.
        awaiting_name = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if awaiting_name:
                awaiting_name = False
                if not _same_member(line):
                    flush()
                    buffer = []
                    current_member = _resolve_member(line)
                    current_category = ""
                continue

            heading_match = self._PDF_MEMBER_HEADING_RE.match(line)
            if heading_match:
                name = heading_match.group(1).strip()
                if not name:
                    awaiting_name = True  # name is on the next line
                elif not _same_member(name):
                    flush()
                    buffer = []
                    current_member = _resolve_member(name)
                    current_category = ""
                continue

            # Fallback: a line that exactly matches a known roster name (covers
            # any section that omits the "Member's Name:" label entirely).
            matched_member = member_by_name.get(line.lower())
            if matched_member is not None:
                if not _same_member(line):
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

            if self._PDF_BOILERPLATE_RE.match(line):
                continue

            buffer.append(line)

        flush()

        if not records:
            logger.warning(
                f"[Scottish Parliament] 0 interest records parsed from PDF {full_url} "
                f"({len(text)} chars extracted, {len(member_by_name)} known member names) — "
                f"text sample: {text[:400]!r}"
            )
        logger.info(f"[Scottish Parliament] {len(records)} interest records parsed from PDF")
        return records

    # ------------------------------------------------------------------
    # Questions — scraped from parliament.scot
    # ------------------------------------------------------------------

    # A real question-detail link points at the question viewer or carries a
    # question reference (S6W-12345 written, S6O- portfolio, S6T- topical, plus
    # the new session-7 S7* equivalents). The previous "any href with /\d+ or a
    # date" rule matched generic site navigation, so we ended up following links
    # into landing pages and harvesting their boilerplate <p> text as "questions".
    _QUESTION_HREF_RE = re.compile(
        r"questions?-and-answers/question\b|[?&](?:reference|ref|uri|qref)=|S\d+[WTOFR]-\d+", re.I)
    _QUESTION_HREF_EXCLUDE_RE = re.compile(
        r"/about\b|general-questions|guidance|standing-orders|how-parliament-works|/help\b|/glossary\b",
        re.I)

    def _question_links(self, soup: BeautifulSoup) -> List[str]:
        out: List[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href.startswith(("/", "http")):
                continue
            if self._QUESTION_HREF_RE.search(href) and not self._QUESTION_HREF_EXCLUDE_RE.search(href):
                out.append(href)
        return out

    # A rendered question-detail page (e.g. ?ref=S7W-00729) carries NO .question /
    # .answer CSS hooks — just generic "basic-content" blocks. The content is laid
    # out as labelled fields instead, so we parse by label rather than by selector:
    #   Question reference: S7W-00729
    #   Asked by: Alexander Burnett, MSP for Aberdeenshire West, Scottish Conservative...
    #   Date lodged: 2 June 2026
    #   Current status: Answered by Angela Constance on 16 June 2026
    #   Question  <question prose>
    #   Answer    <answer prose>
    _Q_REF_RE = re.compile(r"Question reference:\s*(S\d+\w-\d+)", re.I)
    _Q_ASKED_BY_RE = re.compile(r"Asked by:\s*(.+?)\s+Date lodged:", re.I)
    _Q_DATE_LODGED_RE = re.compile(r"Date lodged:\s*(\d{1,2}\s+\w+\s+\d{4})", re.I)
    _Q_ANSWERED_BY_RE = re.compile(
        r"Answered by\s+(.+?)\s+on\s+(\d{1,2}\s+\w+\s+\d{4})", re.I)
    # Footer/nav lines that can trail the answer prose once the SPA has rendered.
    _Q_FOOTER_RE = re.compile(
        r"^(back to top|share|related|previous|next|search|all questions|"
        r"current and previous|sign up|©|cookie|this website|contact us|"
        r"copyright|follow us|accessibility|other questions)", re.I)

    @staticmethod
    def _split_asker(s: str) -> Tuple[str, str, str]:
        """Split 'Name, MSP for Constituency, Party' into (name, party, constituency)."""
        parts = [p.strip() for p in s.split(",") if p.strip()]
        name = parts[0] if parts else ""
        party, constituency = "", ""
        for p in parts[1:]:
            m = re.match(r"msp\s+for\s+(.+)", p, re.I)
            if m:
                constituency = m.group(1).strip()
            elif not re.fullmatch(r"msp", p, re.I):
                party = p  # the remaining non-MSP fragment is the party
        return name, party, constituency

    def _parse_question_detail(self, soup: BeautifulSoup, full_url: str,
                               from_date: Optional[str], records: List[Dict]) -> int:
        """Parse a rendered question-detail page by its field labels.

        Produces one record for the question (attributed to the asking MSP, with
        party/constituency lifted straight off the page) and, when present, one
        for the answer (attributed to the responding minister). Returns the count
        added, or 0 if the page carried no recognisable question reference.
        """
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup
        # Collapse each text node to a single line so the "Question"/"Answer"
        # headings stand alone and metadata fields keep their trailing labels.
        lines = [re.sub(r"\s+", " ", ln).strip()
                 for ln in main.get_text("\n", strip=True).split("\n")]
        lines = [ln for ln in lines if ln]
        flat = " ".join(lines)

        ref_m = self._Q_REF_RE.search(flat)
        if not ref_m:
            return 0
        ref = ref_m.group(1)
        body = flat[ref_m.end():]

        lodged_m = self._Q_DATE_LODGED_RE.search(body)
        date_lodged = self._extract_date_from_text(lodged_m.group(1)) if lodged_m else ""
        if from_date and date_lodged and date_lodged < from_date:
            return 0

        asker_name, asker_party, asker_constit = "", "", ""
        asked_m = self._Q_ASKED_BY_RE.search(body)
        if asked_m:
            asker_name, asker_party, asker_constit = self._split_asker(asked_m.group(1))

        answered_m = self._Q_ANSWERED_BY_RE.search(body)
        answerer = answered_m.group(1).strip() if answered_m else ""
        answer_date = (self._extract_date_from_text(answered_m.group(2))
                       if answered_m else date_lodged)

        # Locate the standalone "Question" / "Answer" heading lines and take the
        # prose that follows each, stopping at the answer heading or page footer.
        def _heading_idx(want: tuple) -> int:
            return next((i for i, l in enumerate(lines)
                         if l.lower() in want), -1)

        def _footer_idx(start: int) -> int:
            for i in range(start, len(lines)):
                if self._Q_FOOTER_RE.match(lines[i]):
                    return i
            return len(lines)

        q_idx = _heading_idx(("question", "question text"))
        a_idx = _heading_idx(("answer", "answer text"))
        q_text, a_text = "", ""
        if q_idx != -1:
            q_end = a_idx if a_idx > q_idx else _footer_idx(q_idx + 1)
            q_text = " ".join(lines[q_idx + 1:q_end]).strip()
        if a_idx != -1:
            a_end = _footer_idx(a_idx + 1)
            a_text = " ".join(lines[a_idx + 1:a_end]).strip()

        added = 0
        if len(q_text) >= 10:
            records.append(self._make_record(
                data_type="question",
                member={"id": "", "name": asker_name, "party": asker_party,
                        "constituency": asker_constit, "role": "MSP"},
                date=date_lodged,
                text=q_text,
                title=ref,
                metadata={"question_ref": ref, "qa_role": "question",
                          "answered_by": answerer},
                source_url=full_url,
            ))
            added += 1
        if len(a_text) >= 10:
            records.append(self._make_record(
                data_type="question",
                member={"id": "", "name": answerer, "party": "",
                        "constituency": "", "role": "MSP"},
                date=answer_date,
                text=a_text,
                title=ref,
                metadata={"question_ref": ref, "qa_role": "answer",
                          "asked_by": asker_name},
                source_url=full_url,
            ))
            added += 1
        return added

    def _diagnose_question_structure(self, soup: BeautifulSoup, full_url: str, rendered: bool) -> None:
        """One-shot structural dump of a question-detail page that matched no item
        selector, so the real markup can be targeted next time."""
        if hasattr(self, "_q_diag_logged"):
            return
        self._q_diag_logged = True
        all_cls = sorted({c for el in soup.select("[class]") for c in el.get("class", [])})
        tag_counts: Dict[str, int] = {}
        for el in soup.find_all(True):
            tag_counts[el.name] = tag_counts.get(el.name, 0) + 1
        common_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:15]
        iframes = [f.get("src", "") for f in soup.find_all("iframe")]
        main_el = soup.find("main") or soup.find("article") or soup.find("body")
        main_text = main_el.get_text(separator=" ", strip=True)[:600] if main_el else ""
        main_html = str(main_el)[:1000] if main_el else ""
        logger.warning(
            f"[Scottish Parliament] Question structure dump ({'rendered' if rendered else 'plain HTTP'}) "
            f"{full_url}: css_classes(first 50)={all_cls[:50]} | tag_counts={common_tags} | "
            f"iframes={iframes[:5]} | main_text_sample={main_text!r}"
        )
        logger.warning(
            f"[Scottish Parliament] Question HTML sample {full_url}: {main_html!r}"
        )

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        # Try every candidate listing and keep whichever yields the best result —
        # "best" meaning the most records with a member name attached, falling
        # back to raw record count. Breaking on the first path to return *any*
        # records is unsound here: the search SPA can render a small, sparsely
        # attributed subset while the plainer listing page yields a much larger,
        # better-attributed set (or vice versa) depending on what's JS-rendered.
        best_records: List[Dict] = []

        for path in [
            # The real, working search listing (the "/question-search" path 404s).
            "/chamber-and-committees/written-questions-and-answers",
            "/chamber-and-committees/questions-and-answers/question-search",
            "/chamber-and-committees/questions-and-answers",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)
            links = self._question_links(soup) if soup else []

            if not links:
                # parliament.scot's question search is a JS single-page app — plain
                # HTTP often returns an empty shell. Re-render it through a browser.
                rendered = self._browser_get(url, wait_selector="a[href*='question'], a[href*='answer'], main")
                if rendered:
                    rendered_links = self._question_links(rendered)
                    if rendered_links:
                        soup, links = rendered, rendered_links
                        logger.info(f"[Scottish Parliament] Found {len(links)} question links at {url} (rendered)")

            if not soup:
                continue
            if not links:
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:500] if body else ""
                logger.warning(f"[Scottish Parliament] No question links at {url} — snippet: {snippet}")
                continue

            logger.info(f"[Scottish Parliament] Found {len(links)} question links at {url}")
            if len(links) > MAX_QUESTION_DETAIL_PAGES:
                logger.warning(
                    f"[Scottish Parliament] Questions: {len(links)} links found but capped at "
                    f"{MAX_QUESTION_DETAIL_PAGES} (MAX_QUESTION_DETAIL_PAGES) — raise in config.py for full coverage"
                )
            path_records: List[Dict] = []
            for href in links[:MAX_QUESTION_DETAIL_PAGES]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                detail = self._html_get(full_url)
                added = (self._parse_question_detail(detail, full_url, from_date, path_records)
                         if detail else 0)
                rendered = None
                if added == 0:
                    # The question viewer is a JS single-page app — plain HTTP
                    # returns the nav shell. Re-render so the labelled Q&A loads.
                    rendered = self._browser_get(
                        full_url, wait_selector="main p, .basic-content, main h2")
                    if rendered:
                        added = self._parse_question_detail(rendered, full_url, from_date, path_records)
                page = rendered or detail
                if page is None:
                    continue
                if added == 0:
                    body = page.find("body")
                    snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
                    logger.warning(f"[Scottish Parliament] 0 items from question page {full_url} — snippet: {snippet}")
                    self._diagnose_question_structure(page, full_url, rendered=bool(rendered))

            def _score(recs: List[Dict]) -> Tuple[int, int]:
                named = sum(1 for r in recs if str(r.get("member", {}).get("name", "")).strip())
                return (named, len(recs))

            logger.info(f"[Scottish Parliament] {url} yielded {len(path_records)} question records "
                        f"({_score(path_records)[0]} with member names)")
            if _score(path_records) > _score(best_records):
                best_records = path_records

        logger.info(f"[Scottish Parliament] {len(best_records)} question records fetched (best of candidates)")
        return best_records

    # ------------------------------------------------------------------
    # Plenary business — Official Report from parliament.scot
    # ------------------------------------------------------------------

    def _recent_sitting_dates(self, n: int = 60) -> List[str]:
        """Return the last n weekdays as YYYY-MM-DD strings (parliament doesn't sit weekends)."""
        today = date.today()
        days = []
        d = today
        while len(days) < n:
            if d.weekday() < 5:  # Mon–Fri
                days.append(d.strftime("%Y-%m-%d"))
            d -= timedelta(days=1)
        return days

    _OR_CONTRIB_SELECTOR = (
        ".contribution, .speech, [class*='contribution'], [class*='speech'], "
        ".or-row, .or-report-row, .member-speech, .chamber-row, "
        ".qna-item, .member-contribution, tr, article, .content-row"
    )

    def _extract_or_contribs(self, detail: BeautifulSoup, full_url: str, date_str: str,
                             records: List[Dict]) -> int:
        before = len(records)
        for contrib in detail.select(self._OR_CONTRIB_SELECTOR):
            speaker_el = contrib.select_one(
                ".speaker, .msp-name, strong, b, td:first-child, "
                "[class*='speaker'], [class*='member-name'], .or-member"
            )
            text_el = contrib.select_one(".text, p, td:last-child, [class*='text'], [class*='body']")
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
        return len(records) - before

    def _diagnose_or_structure(self, soup: BeautifulSoup, full_url: str, rendered: bool) -> None:
        """One-shot structural dump of an Official Report page that matched no
        contribution selector, so the real markup can be targeted next time
        instead of guessed at blindly. Logged at WARNING so it survives the
        test harness's log-level filter."""
        if hasattr(self, "_or_diag_logged"):
            return
        main_el = soup.find("main") or soup.find("article") or soup.find("body")
        main_text_len = len(main_el.get_text(strip=True)) if main_el else 0
        if main_text_len < 500:
            # Empty SPA shell — a recess date with no report. Don't spend the
            # one-shot dump here; save it for a page that actually has content
            # our selectors fail on (that's the markup we need to see).
            if not hasattr(self, "_or_shell_logged"):
                self._or_shell_logged = True
                logger.warning(
                    f"[Scottish Parliament] OR page is an empty shell "
                    f"(main_text_len={main_text_len}) at {full_url} — structure "
                    f"dump deferred until a content-bearing page fails"
                )
            return
        self._or_diag_logged = True
        all_cls = sorted({c for el in soup.select("[class]") for c in el.get("class", [])})
        tag_counts: Dict[str, int] = {}
        for el in soup.find_all(True):
            tag_counts[el.name] = tag_counts.get(el.name, 0) + 1
        common_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:15]
        iframes = [f.get("src", "") for f in soup.find_all("iframe")]
        logger.warning(
            f"[Scottish Parliament] OR structure dump ({'rendered' if rendered else 'plain HTTP'}) "
            f"{full_url}: css_classes(first 40)={all_cls[:40]} | tag_counts={common_tags} | "
            f"iframes={iframes[:5]} | main_text_len={main_text_len}"
        )
        # The breadcrumb nav dominates the head of <main>, so a raw prefix dump
        # is mostly noise — instead show the first few *content* paragraphs with
        # their parent chains (that's what selector-writing actually needs).
        paras = [p for p in (main_el.find_all("p") if main_el else [])
                 if not p.find_parent("nav") and len(p.get_text(strip=True)) > 20][:3]
        para_info = []
        for p in paras:
            parents = [
                f"{el.name}.{'.'.join(el.get('class', []))}" if el.get("class") else el.name
                for el in p.parents
                if el.name not in ("html", "body", "[document]")
            ][:4]
            para_info.append(f"parents={parents} html={str(p)[:300]!r}")
        logger.warning(
            f"[Scottish Parliament] OR content paragraphs {full_url}: "
            + (" || ".join(para_info) if para_info else f"none found — main head: {str(main_el)[:600]!r}")
        )

    def _extract_or_paragraphs(self, soup: BeautifulSoup, full_url: str, date_str: str,
                               records: List[Dict]) -> int:
        """Fallback for OR pages whose rendered DOM carries no semantic
        contribution classes — the same SPA pattern as the question pages,
        where content sits in generic basic-content blocks. Walk the
        main-content paragraphs, treating a bold/strong prefix (or a short
        "Name:" prefix) as the speaker and carrying the speaker forward
        across continuation paragraphs.

        Guarded by a minimum main-text length so recess-date shell pages
        (~155 chars of nav) can never be harvested as junk records."""
        main = soup.find("main") or soup.find("article")
        if main is None:
            return 0
        for nav in main.find_all("nav"):
            nav.decompose()
        if len(main.get_text(strip=True)) < 2000:
            return 0
        before = len(records)
        current_name = ""
        for p in main.find_all("p"):
            text = p.get_text(" ", strip=True)
            if len(text) < 20:
                continue
            bold = p.find(["strong", "b"])
            name = bold.get_text(strip=True) if bold else ""
            if not name and ":" in text[:80]:
                prefix = text.split(":", 1)[0].strip()
                if 0 < len(prefix) <= 60 and not prefix[0].isdigit():
                    name = prefix
            if name:
                current_name = name.rstrip(":").strip()
            records.append(self._make_record(
                data_type="plenary_speech",
                member={"id": "", "name": current_name, "party": "",
                        "constituency": "", "role": "MSP"},
                date=date_str,
                text=text,
                title="",
                metadata={"extraction": "paragraph-fallback"},
                source_url=full_url,
            ))
        added = len(records) - before
        if added and not hasattr(self, "_or_para_fallback_logged"):
            self._or_para_fallback_logged = True
            first_name = records[before]["member"]["name"]
            logger.warning(
                f"[Scottish Parliament] OR paragraph-fallback engaged at {full_url}: "
                f"{added} paragraphs, first speaker={first_name!r}"
            )
        return added

    def _scrape_or_detail(self, full_url: str, date_str: str,
                          records: List[Dict], from_date: Optional[str]) -> int:
        """Scrape a single Official Report page and append any speeches to records.
        Returns the number of records added."""
        if from_date and date_str and date_str[:10] < from_date:
            return 0
        detail = self._html_get(full_url)
        if detail and not date_str:
            date_el = detail.select_one("time[datetime], time, .date, h1")
            date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""

        added = self._extract_or_contribs(detail, full_url, date_str, records) if detail else 0
        rendered_soup = None
        if added == 0:
            # The Official Report viewer renders transcripts client-side via JS —
            # plain HTTP usually returns an empty shell. Re-render through a browser.
            rendered_soup = self._browser_get(full_url, wait_selector=self._OR_CONTRIB_SELECTOR)
            if rendered_soup:
                if not date_str:
                    date_el = rendered_soup.select_one("time[datetime], time, .date, h1")
                    date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
                r_added = self._extract_or_contribs(rendered_soup, full_url, date_str, records)
                if r_added:
                    detail, added = rendered_soup, r_added
        if added == 0:
            # Neither selector set matched — try the label-free paragraph walk
            # on whichever DOM has the most content (prefer the rendered one).
            for candidate in (rendered_soup, detail):
                if candidate is None:
                    continue
                p_added = self._extract_or_paragraphs(candidate, full_url, date_str, records)
                if p_added:
                    detail, added = candidate, p_added
                    break

        if not detail:
            return 0
        if added == 0:
            # Suppress per-page noise — only log the first 3 empty-shell dates
            # so the run log isn't flooded with 60+ identical warnings. After
            # that, count silently; a summary is logged at the caller level.
            self._or_empty_count = getattr(self, "_or_empty_count", 0) + 1
            if self._or_empty_count <= 3:
                body = detail.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:200] if body else ""
                logger.warning(f"[Scottish Parliament] 0 contribs at {full_url} — snippet: {snippet}")
            self._diagnose_or_structure(rendered_soup or detail, full_url, rendered=bool(rendered_soup))
        return added

    def _fetch_meeting_ids(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch meeting IDs from the Scottish Parliament OData events endpoint.

        Returns list of dicts with keys: id, date, title.
        """
        params: Dict = {"$format": "json", "$orderby": "EventDate desc", "$top": 200}
        if from_date:
            params["$filter"] = f"EventDate ge datetime'{from_date}T00:00:00'"
        meetings = []
        # NOTE: the OData "Events" entity is deliberately excluded — it exists
        # (fields ID/Date/Title/Sponsor) but holds cross-party-group events going
        # back to 2015, not chamber sittings. Feeding its IDs to the OR media
        # API would issue hundreds of bogus requests.
        for entity in ["Meetings", "PlenaryMeetings", "ChamberMeetings", "SittingDays"]:
            url = f"{_API}/{entity}"
            resp = self._get(url, params=params)
            if not resp or not resp.ok:
                status = resp.status_code if resp else "no response"
                logger.warning(f"[Scottish Parliament] Events endpoint {entity}: HTTP {status}")
                continue
            try:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("value", [])
            except Exception:
                continue
            if not items:
                logger.warning(f"[Scottish Parliament] Events endpoint {entity}: 0 items")
                continue
            logger.warning(f"[Scottish Parliament] Events fields: {list(items[0].keys())} | sample={items[0]!r:.300}")
            for item in items:
                meeting_id = str(
                    item.get("EventId") or item.get("MeetingId") or item.get("Id") or item.get("id") or ""
                )
                event_date = str(
                    item.get("EventDate") or item.get("MeetingDate") or item.get("Date") or ""
                )
                # EventDate often comes back as "/Date(1234567890000)/" — parse it
                ts_match = re.search(r"/Date\((\d+)\)/", event_date)
                if ts_match:
                    from datetime import datetime, timezone
                    ts = int(ts_match.group(1)) // 1000
                    event_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                title = str(item.get("EventTitle") or item.get("Title") or item.get("Name") or "")
                if meeting_id:
                    meetings.append({"id": meeting_id, "date": event_date[:10], "title": title})
            if meetings:
                logger.info(f"[Scottish Parliament] {len(meetings)} meetings from {entity}")
                break
        return meetings

    def _fetch_or_via_api(self, meeting_id: str, meeting_date: str,
                           records: List[Dict], from_date: Optional[str]) -> int:
        """Fetch Official Report for one meeting via the parliament.scot media API.

        The API returns HTML with speaker contributions — parse each paragraph.
        Returns number of records added.
        """
        if from_date and meeting_date and meeting_date < from_date:
            return 0
        url = f"{_WEB}/api/sitecore/CustomMedia/OfficialReport"
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,*/*;q=0.8",
            "Referer": f"{_WEB}/chamber-and-committees/official-report/",
        })
        resp = self._get(url, params={"meetingId": meeting_id}, timeout=60)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0
        ct = resp.headers.get("Content-Type", "")
        if "json" in ct:
            try:
                payload = resp.json()
                html_content = payload.get("html") or payload.get("content") or ""
                if not html_content:
                    return 0
                soup = BeautifulSoup(html_content, "lxml")
            except Exception:
                return 0
        else:
            soup = BeautifulSoup(resp.text, "lxml")

        before = len(records)
        # Each contribution is typically <p> with speaker name bolded or in a span,
        # or structured as rows with speaker + text cells.
        for contrib in soup.select("p, .contribution, tr, .or-contribution, .speech"):
            text = contrib.get_text(strip=True)
            if len(text) < 10:
                continue
            speaker_el = contrib.select_one("strong, b, .speaker, th, td:first-child")
            name = speaker_el.get_text(strip=True) if speaker_el else ""
            # If name is embedded at start of text "Name: speech..."
            if not name and ":" in text:
                prefix = text.split(":", 1)[0].strip()
                if prefix and len(prefix) < 60:
                    name = prefix
            records.append(self._make_record(
                data_type="plenary_speech",
                member={"id": "", "name": name, "party": "", "constituency": "", "role": "MSP"},
                date=meeting_date,
                text=text,
                title="",
                source_url=f"{url}?meetingId={meeting_id}",
            ))
        added = len(records) - before
        if added == 0 and not hasattr(self, "_or_api_empty_logged"):
            self._or_api_empty_logged = True
            snippet = soup.get_text(strip=True)[:300] if soup else ""
            logger.warning(f"[Scottish Parliament] OR API meeting {meeting_id}: 0 contribs — snippet: {snippet}")
        return added

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        records: List[Dict] = []

        # ----------------------------------------------------------------
        # 1. Official Report via parliament.scot media API.
        #    GET /api/sitecore/CustomMedia/OfficialReport?meetingId=NNNN
        #    Meeting IDs come from the data.parliament.scot OData Events entity.
        # ----------------------------------------------------------------
        meetings = self._fetch_meeting_ids(from_date)
        if meetings:
            logger.info(f"[Scottish Parliament] Fetching OR for {len(meetings)} meetings via API...")
            hits = 0
            for i, m in enumerate(meetings):
                if i % 20 == 0:
                    logger.info(f"[Scottish Parliament] OR API: {i}/{len(meetings)} meetings, {len(records)} records so far")
                added = self._fetch_or_via_api(m["id"], m["date"], records, from_date)
                if added > 0:
                    hits += 1
            logger.info(f"[Scottish Parliament] OR API: {hits}/{len(meetings)} meetings had content, {len(records)} total records")
            if records:
                logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched (via OR API)")
                return records

        # ----------------------------------------------------------------
        # 2. Try RSS feed — the Scottish Parliament exposes one for the OR.
        #    Each <item> has a <link> pointing to a session transcript.
        # ----------------------------------------------------------------
        rss_candidates = [
            f"{_WEB}/rss/official-report",
            f"{_WEB}/rss/official-report/chamber",
            f"{_WEB}/feed/official-report",
            f"{_WEB}/rss",
        ]
        rss_links: List[str] = []
        for rss_url in rss_candidates:
            rss_resp = self._html_get(rss_url)
            if not rss_resp:
                continue
            items = rss_resp.find_all("item")
            if not items:
                logger.warning(f"[Scottish Parliament] RSS {rss_url}: 0 <item> elements")
                continue
            for item in items:
                link_el = item.find("link")
                href = link_el.get_text(strip=True) if link_el else ""
                if href and "official-report" in href:
                    rss_links.append(href)
            if rss_links:
                logger.info(f"[Scottish Parliament] RSS {rss_url}: {len(rss_links)} OR links")
                break

        for href in rss_links[:30]:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", href)
            date_hint = m.group(1) if m else ""
            self._scrape_or_detail(href, date_hint, records, from_date)
        if records:
            logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched (via RSS)")
            return records

        # ----------------------------------------------------------------
        # 3. Try the generic OR index pages.
        # ----------------------------------------------------------------
        _SKIP_SUBNAV = {
            "search-what-was-said-in-parliament",
            "about-the-official-report",
            "alphabetical-list-of-debates",
            "corrections-and-changes-to-the-official-report",
        }
        for path in [
            "/chamber-and-committees/official-report/what-was-said-in-parliament",
            "/chamber-and-committees/official-report",
            "/chamber-and-committees/chamber-debates",
            "/chamber-and-committees/plenary",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)

            def _or_links(s: BeautifulSoup) -> List[str]:
                hrefs = [a["href"] for a in s.select("a[href]")
                         if a.get("href", "").startswith(("/", "http"))]
                return [h for h in hrefs
                        if re.search(r"official-report-\d|\d{4}-\d{2}-\d{2}|/or-\d|meetingid=", h, re.I)
                        and not any(sub in h for sub in _SKIP_SUBNAV)]

            links = _or_links(soup) if soup else []
            if not links:
                # The OR index is a JS single-page app — plain HTTP returns only
                # the nav shell. Re-render it so the session list is populated.
                rendered = self._browser_get(url, wait_selector="a[href*='official-report-'], a[href*='meetingId']")
                if rendered:
                    links = _or_links(rendered)
                    if links:
                        soup = rendered
                        logger.info(f"[Scottish Parliament] Found {len(links)} OR links at {url} (rendered)")
            if not links:
                all_hrefs = [a["href"] for a in soup.select("a[href]")][:10] if soup else []
                logger.warning(
                    f"[Scottish Parliament] No OR links at {url} — sample hrefs: {all_hrefs}"
                )
                continue
            logger.info(f"[Scottish Parliament] Found {len(links)} OR links at {url}")
            for href in links[:50]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                m = re.search(r"(\d{4}-\d{2}-\d{2})", href)
                date_hint = m.group(1) if m else ""
                self._scrape_or_detail(full_url, date_hint, records, from_date)
            if records:
                break

        if records:
            logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched (via index pages)")
            return records

        # ----------------------------------------------------------------
        # 4. Direct date-based URL construction for recent sitting days.
        # ----------------------------------------------------------------
        month_names = ["january", "february", "march", "april", "may", "june",
                       "july", "august", "september", "october", "november", "december"]
        tried = 0
        hit = 0
        for iso_date in self._recent_sitting_dates(90):
            y, mo, d = iso_date.split("-")
            slug = f"official-report-{int(d)}-{month_names[int(mo) - 1]}-{y}"
            url = (f"{_WEB}/chamber-and-committees/official-report/"
                   f"what-was-said-in-parliament/{slug}")
            added = self._scrape_or_detail(url, iso_date, records, from_date)
            tried += 1
            if added > 0:
                hit += 1
        empty = getattr(self, "_or_empty_count", 0)
        if tried:
            if hit == 0 and empty > 3:
                logger.warning(
                    f"[Scottish Parliament] Date-URL probe: {tried} dates tried, 0 had content "
                    f"({empty} empty-shell pages, first 3 logged above) — "
                    f"parliament.scot appears to have rebuilt its OR infrastructure for Session 7; "
                    f"the /what-was-said-in-parliament/{'{date}'} URL pattern returns a nav-only "
                    f"SPA shell for all probed dates including pre-election Session 6 sittings. "
                    f"OR will become available once the new session's transcripts are published."
                )
            else:
                logger.info(
                    f"[Scottish Parliament] Date-URL probe: {tried} dates tried, "
                    f"{hit} had content, {len(records)} total records"
                )

        logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    _MOTION_VOTER_SELECTORS = [
        ("aye", [".ayes li", ".for li", "[class*='aye'] li", "[class*='for'] li",
                 "table tr td:nth-child(1)", "ul.ayes li"]),
        ("no", [".noes li", ".against li", "[class*='no'] li", "[class*='against'] li",
                "table tr td:nth-child(2)", "ul.noes li"]),
        ("abstain", [".abstentions li", ".abstain li", "[class*='abstain'] li"]),
    ]

    def _extract_motion_voters(self, detail: BeautifulSoup, url: str, motion_ref: str,
                               date_str: str, div_title: str, records: List[Dict]) -> int:
        before = len(records)
        for direction, sel_list in self._MOTION_VOTER_SELECTORS:
            voters = []
            for sel in sel_list:
                voters = detail.select(sel)
                if voters:
                    break
            for voter_el in voters:
                name = voter_el.get_text(strip=True)
                if not name or len(name) < 2:
                    continue
                records.append(self._make_record(
                    data_type="vote",
                    member={"id": "", "name": name, "party": "", "constituency": "", "role": "MSP"},
                    date=date_str,
                    text=f"Voted {direction} on: {div_title}",
                    title=div_title,
                    metadata={"vote_direction": direction, "division_result": "",
                              "motion_ref": motion_ref},
                    source_url=url,
                ))
        return len(records) - before

    def _scrape_motion_vote_page(self, motion_ref: str, records: List[Dict],
                                  from_date: Optional[str]) -> int:
        """Scrape a single S6M-NNNN votes-and-motions page. Returns records added."""
        url = f"{_WEB}/chamber-and-committees/votes-and-motions/{motion_ref}"

        def _date_and_title(s):
            date_el = s.select_one("time[datetime], time, .date, [class*='date']")
            d = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
            if not d:
                body_text = s.get_text(separator=" ", strip=True)
                dm = re.search(r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}", body_text)
                d = dm.group(0) if dm else ""
            title_el = s.select_one("h1, h2, .title, .motion-title")
            t = title_el.get_text(strip=True) if title_el else motion_ref
            return d, t

        detail = self._html_get(url)
        if not detail:
            return 0
        date_str, div_title = _date_and_title(detail)
        if from_date and date_str and len(date_str) >= 10 and date_str[:10] < from_date:
            return 0

        added = self._extract_motion_voters(detail, url, motion_ref, date_str, div_title, records)
        if added == 0:
            # Voting lists on these pages are often injected client-side via JS.
            rendered = self._browser_get(url, wait_selector=".ayes, .noes, [class*='aye'], [class*='division']")
            if rendered:
                r_date_str, r_div_title = _date_and_title(rendered)
                r_date_str = r_date_str or date_str
                r_div_title = r_div_title or div_title
                if from_date and r_date_str and len(r_date_str) >= 10 and r_date_str[:10] < from_date:
                    return 0
                r_added = self._extract_motion_voters(rendered, url, motion_ref, r_date_str, r_div_title, records)
                if r_added:
                    detail, added, date_str = rendered, r_added, r_date_str

        if added == 0:
            body = detail.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:200] if body else ""
            logger.warning(f"[Scottish Parliament] No voters at {url} — snippet: {snippet}")
        return added

    def _enumerate_motion_pages(self, from_date: Optional[str], records: List[Dict]) -> int:
        """Enumerate S6M-NNNN motion pages from the votes-and-motions index.

        The index page at /chamber-and-committees/votes-and-motions/ lists motions
        as links matching /S[0-9]+M-[0-9]+/.  We follow those and parse voter lists.
        Returns total records added.
        """
        index_url = f"{_WEB}/chamber-and-committees/votes-and-motions/"

        def _motion_refs(s):
            refs, seen = [], set()
            for a in s.select("a[href]"):
                href = a.get("href", "")
                m = re.search(r"(S\d+M-\d+)", href, re.I)
                if m and m.group(1) not in seen:
                    seen.add(m.group(1))
                    refs.append(m.group(1))
            return refs

        soup = self._html_get(index_url)
        motion_refs = _motion_refs(soup) if soup else []

        if not motion_refs:
            # The motions index lists content via a JS-driven search widget —
            # plain HTTP often returns an empty shell. Re-render through a browser.
            rendered = self._browser_get(index_url, wait_selector="a[href*='S6M-'], a[href*='S5M-'], main")
            if rendered:
                rendered_refs = _motion_refs(rendered)
                if rendered_refs:
                    soup, motion_refs = rendered, rendered_refs
                    logger.info(f"[Scottish Parliament] Found {len(motion_refs)} motion refs on index (rendered)")

        if not soup:
            logger.warning(f"[Scottish Parliament] Could not load motions index: {index_url}")
            return 0
        if not motion_refs:
            body = soup.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
            logger.warning(f"[Scottish Parliament] No motion refs on index — snippet: {snippet}")
            return 0

        logger.info(f"[Scottish Parliament] Found {len(motion_refs)} motion refs on index")
        added_total = 0
        for ref in motion_refs[:200]:
            added_total += self._scrape_motion_vote_page(ref, records, from_date)
        return added_total

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

        # Fallback: enumerate S6M-NNNN motion pages from the votes-and-motions index
        records: List[Dict] = []
        added = self._enumerate_motion_pages(from_date, records)
        if records:
            logger.info(f"[Scottish Parliament] {len(records)} vote records fetched (via motion pages)")
            return records

        # Last resort: scrape whatever division links we can find
        def _division_links(s):
            return [a["href"] for a in s.select("a[href]")
                    if a.get("href", "").startswith(("/", "http"))
                    and re.search(r"/division|/vote|\d{4}-\d{2}-\d{2}|/\d+|S\d+M-\d+",
                                  a.get("href", ""), re.I)]

        def _extract_division_voters(detail, full_url, date_str, div_title):
            added = 0
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
                    added += 1
            return added

        for path in [
            "/chamber-and-committees/votes-and-divisions/search",
            "/chamber-and-committees/votes-and-divisions",
            "/chamber-and-committees/votes-and-divisions/",
            "/chamber-and-committees/votes/",
            "/chamber-and-committees/divisions/",
            "/parliamentarybusiness/voting/",
            "/msps/voting-behaviour",
            "/msps/votes/",
        ]:
            url = f"{_WEB}{path}"
            soup = self._html_get(url)
            links = _division_links(soup) if soup else []

            if not links:
                # These index/search pages are JS single-page apps — plain HTTP
                # often returns an empty shell. Re-render through a browser.
                rendered = self._browser_get(url, wait_selector="a[href*='division'], a[href*='vote'], a[href*='S6M-'], main")
                if rendered:
                    rendered_links = _division_links(rendered)
                    if rendered_links:
                        soup, links = rendered, rendered_links
                        logger.info(f"[Scottish Parliament] Found {len(links)} division links at {url} (rendered)")

            if not soup:
                continue
            if not links:
                body = soup.find("body")
                snippet = body.get_text(separator=" ", strip=True)[:600] if body else ""
                logger.warning(f"[Scottish Parliament] No division links at {url} — snippet: {snippet}")
                continue

            logger.info(f"[Scottish Parliament] Found {len(links)} division links")
            for href in links[:200]:
                full_url = href if href.startswith("http") else f"{_WEB}{href}"
                detail = self._html_get(full_url)
                date_el = detail.select_one("time[datetime], time, .date, h1") if detail else None
                date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
                if from_date and date_str and date_str[:10] < from_date:
                    continue
                title_el = detail.select_one("h1, h2, .title, .motion") if detail else None
                div_title = title_el.get_text(strip=True) if title_el else ""
                added = _extract_division_voters(detail, full_url, date_str, div_title) if detail else 0
                if added == 0:
                    rendered = self._browser_get(full_url, wait_selector=".ayes, .noes, [class*='aye'], [class*='division']")
                    if rendered:
                        r_date_el = rendered.select_one("time[datetime], time, .date, h1")
                        r_date_str = (r_date_el.get("datetime", r_date_el.get_text(strip=True))
                                      if r_date_el else "") or date_str
                        if from_date and r_date_str and r_date_str[:10] < from_date:
                            continue
                        r_title_el = rendered.select_one("h1, h2, .title, .motion")
                        r_div_title = (r_title_el.get_text(strip=True) if r_title_el else "") or div_title
                        _extract_division_voters(rendered, full_url, r_date_str, r_div_title)
            if records:
                break

        logger.info(f"[Scottish Parliament] {len(records)} vote records fetched")
        return records
