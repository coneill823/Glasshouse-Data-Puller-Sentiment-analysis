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
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS, MAX_SCOTTISH_QUESTION_PAGES

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["scottish_parliament"]
_API = _CFG["api_base"]          # https://data.parliament.scot/api
_WEB = "https://www.parliament.scot"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_OR_SEARCH = f"{_WEB}/chamber-and-committees/official-report/search-what-was-said-in-parliament"
_OR_MEDIA = f"{_WEB}/api/sitecore/CustomMedia/OfficialReport"
_MAX_OR_PAGES = 60   # safety cap on Official Report search pagination


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
                    logger.debug(f"[Scottish Parliament] Members?$expand=MemberParties sample MemberParties={mp!r:.200}")
        except Exception:
            pass
        rows = expand_rows or self._odata_get("Members")
        if rows:
            logger.debug(f"[Scottish Parliament] Members OData sample fields: {list(rows[0].keys())} | sample={dict(list(rows[0].items())[:8])!r:.400}")
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
            self._enrich_msp_constituencies(members)
            self._label_office_holders(members)
        logger.info(f"[Scottish Parliament] {len(members)} MSPs fetched")
        return members

    def _label_office_holders(self, members: List[Dict]) -> None:
        """Show the office instead of a bare "No Party Affiliation".

        The Presiding Officer relinquishes party allegiance while in the chair
        and is recorded by the Parliament as "No Party Affiliation" (the two
        Deputy Presiding Officers keep their party, so only the PO is recorded
        this way). Relabel current such members so the party column reads the
        office rather than an unhelpful "No Party Affiliation".
        """
        for m in members:
            if (m.get("status") == "current"
                    and (m.get("party") or "").strip().lower() == "no party affiliation"):
                m["party"] = "Presiding Officer"

    # Current-role line on a parliament.scot MSP profile page reads
    # "MSP for <Area> (Constituency)" or "... (Region)". Former roles are
    # prefixed "Former MSP for ..." and must be skipped.
    _PROFILE_ROLE_RE = re.compile(r"(Former )?MSP for (.+?) \((Constituency|Region)\)")

    def _enrich_msp_constituencies(self, members: List[Dict]) -> None:
        """Fill each CURRENT MSP's constituency (or region, for list MSPs).

        data.parliament.scot exposes no member->area link, but its Websites
        entity gives each member's parliament.scot profile URL, whose current
        role line reads 'MSP for <Area> (Constituency|Region)'. We fetch that
        page per current MSP and take the first non-'Former' match, so a
        regional (list) MSP gets their region and a constituency MSP their
        constituency — both being the electoral "area" a voter is graded on.
        Only current MSPs are enriched (historical ones are kept for attributing
        old records but don't need an area for the app).
        """
        current = [m for m in members if m.get("status") == "current" and m.get("id")]
        if not current:
            return
        web_rows = self._odata_get("Websites") or []
        profile_by_id: Dict[str, str] = {}
        for w in web_rows:
            pid = str(w.get("PersonID") or "")
            url = w.get("WebURL") or w.get("WebUrl") or ""
            if pid and "parliament.scot/msps" in url.lower():
                if pid not in profile_by_id or w.get("IsDefault"):
                    profile_by_id[pid] = url
        if not profile_by_id:
            logger.warning("[Scottish Parliament] Websites gave no MSP profile URLs — "
                           "cannot enrich constituencies")
            return
        filled = 0
        for i, m in enumerate(current):
            url = profile_by_id.get(m["id"])
            if not url:
                continue
            if i and i % 25 == 0:
                logger.info(f"[Scottish Parliament] Constituency enrichment: {i}/{len(current)} "
                            f"profiles processed ({filled} filled)")
            soup = self._html_get(url)
            if not soup:
                continue
            text = soup.get_text(" ", strip=True)
            for former, area, _kind in self._PROFILE_ROLE_RE.findall(text):
                if former:
                    continue  # skip historical roles
                m["constituency"] = area.strip()
                filled += 1
                break
        logger.info(f"[Scottish Parliament] Constituency enrichment: filled "
                    f"{filled}/{len(current)} current MSPs from profile pages")

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
            logger.debug(f"[Scottish Parliament] Parties fields: {list(party_rows[0].keys())} | sample={party_rows[0]!r:.300}")
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
            logger.debug(f"[Scottish Parliament] MemberParties fields: {list(mp_rows[0].keys())} | sample={mp_rows[0]!r:.300}")

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

    # A question-search result card carries its reference, asker and answerer as
    # labelled lines (parsed in _parse_question_card):
    #   Question reference: S7W-00729
    #   Asked by: Alexander Burnett, MSP for Aberdeenshire West, Scottish Conservative...
    #   Current Status: Answered by Angela Constance on 16 June 2026
    _Q_REF_RE = re.compile(r"Question reference:\s*(S\d+\w-\d+)", re.I)
    _Q_ANSWERED_BY_RE = re.compile(
        r"Answered by\s+(.+?)\s+on\s+(\d{1,2}\s+\w+\s+\d{4})", re.I)

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

    # The questions-and-answers page is server-side rendered: submitting the
    # search form is a plain GET back to the page itself. The date-range control
    # carries a "<token>|<from>|<to>" value; the server parses the two date
    # strings (the leading token is a stable, range-agnostic prefix) and renders
    # 10 result cards per page, each card holding the full question + answer
    # inline — so we bound the fetch by date and page through, parsing cards
    # directly (no per-question detail fetch needed).
    _QUESTIONS_URL = f"{_WEB}/chamber-and-committees/questions-and-answers"
    _Q_DATE_SELECT_TOKEN = "acfe09e8571447b6ac663f6362a20f42"
    _Q_PAGE_SIZE = 10
    _Q_MAX_PAGES = MAX_SCOTTISH_QUESTION_PAGES   # safety cap (config-tunable)
    _SCOTTISH_PARLIAMENT_EPOCH = "1999-05-12"  # opening of the Scottish Parliament
    _Q_REF_IN_HREF_RE = re.compile(r"ref=(S\d+\w-\d+)", re.I)

    @staticmethod
    def _format_q_date(iso: str) -> str:
        """YYYY-MM-DD -> the 'Weekday, Mon D, YYYY' string the date control sends."""
        from datetime import datetime as _dt
        d = _dt.strptime(iso, "%Y-%m-%d")
        # %-d (no leading zero) isn't portable across platforms; build it by hand.
        return f"{d.strftime('%A, %b')} {d.day}, {d.year}"

    def _card_ref(self, card) -> str:
        a = card.select_one("a[href*='ref=']")
        if a:
            m = self._Q_REF_IN_HREF_RE.search(a.get("href", ""))
            if m:
                return m.group(1).upper()
        m = self._Q_REF_RE.search(card.get_text(" ", strip=True))
        return m.group(1).upper() if m else ""

    def _parse_question_card(self, card, ref: str, from_date: Optional[str],
                             records: List[Dict]) -> int:
        """Parse one div.content-list__block search-result card.

        Emits a record for the question (attributed to the asking MSP, with
        party/constituency lifted off the 'Asked by' line) and, when answered,
        one for the answer (attributed to the responding minister). Returns the
        number of records added.
        """
        def _li(label: str) -> str:
            for li in card.select("ul.contents-nav li"):
                t = li.get_text(" ", strip=True)
                if t.lower().startswith(label.lower()):
                    return t
            return ""

        asker_name = asker_party = asker_constit = ""
        asked_m = re.search(r"Asked by:\s*(.+)", _li("Asked by:"), re.I)
        if asked_m:
            asker_name, asker_party, asker_constit = self._split_asker(asked_m.group(1))

        date_lodged = self._extract_date_from_text(_li("Date lodged:"))
        if from_date and date_lodged and date_lodged < from_date:
            return 0

        answered_m = self._Q_ANSWERED_BY_RE.search(_li("Current Status:"))
        answerer = answered_m.group(1).strip() if answered_m else ""
        answer_date = (self._extract_date_from_text(answered_m.group(2))
                       if answered_m else date_lodged)

        # Question prose = the card's direct <p> children (skip the empty lead
        # <p>); the answer lives in the hidden .waanswer.rich-text panel.
        q_text = " ".join(
            t for t in (p.get_text(" ", strip=True)
                        for p in card.find_all("p", recursive=False)) if t).strip()
        ans_el = (card.select_one("div.waanswer.rich-text")
                  or card.select_one("div.waanswer"))
        a_text = ans_el.get_text(" ", strip=True) if ans_el else ""

        url = f"{self._QUESTIONS_URL}/question?ref={ref}"
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
                source_url=url,
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
                source_url=url,
            ))
            added += 1
        return added

    def fetch_questions(self, from_date: Optional[str] = None,
                        to_date: Optional[str] = None) -> List[Dict]:
        start = from_date or self._SCOTTISH_PARLIAMENT_EPOCH
        end = to_date or date.today().isoformat()
        try:
            date_select = (f"{self._Q_DATE_SELECT_TOKEN}|"
                           f"{self._format_q_date(start)}|{self._format_q_date(end)}")
        except ValueError:
            # Unparseable dates — fall back to the full-history range.
            date_select = (f"{self._Q_DATE_SELECT_TOKEN}|"
                           f"{self._format_q_date(self._SCOTTISH_PARLIAMENT_EPOCH)}|"
                           f"{self._format_q_date(date.today().isoformat())}")
        base = {"msp": "", "qry": "", "qryref": "", "dateSelect": date_select}

        records: List[Dict] = []
        seen: set = set()
        page = 0
        for page in range(1, self._Q_MAX_PAGES + 1):
            params = dict(base)
            if page > 1:
                params["page"] = page
            soup = self._html_get(self._QUESTIONS_URL, params=params)
            cards = soup.select("div.content-list__block") if soup else []
            if not cards:
                break
            new_refs = 0
            for card in cards:
                ref = self._card_ref(card)
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                new_refs += 1
                self._parse_question_card(card, ref, from_date, records)
            # Paging past the last page re-serves page 1 (all-seen) or an empty
            # list; either way no new refs means we're done.
            if new_refs == 0:
                break
            if len(cards) < self._Q_PAGE_SIZE:
                break
        else:
            logger.warning(
                f"[Scottish Parliament] Questions: hit the {self._Q_MAX_PAGES}-page "
                f"cap ({len(seen)} questions) — narrow the date range or raise _Q_MAX_PAGES"
            )

        logger.info(f"[Scottish Parliament] {len(records)} question records fetched "
                    f"from {len(seen)} questions across {page} page(s) "
                    f"({start} → {end})")
        return records

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

    def _fetch_meeting_ids(self, from_date: Optional[str] = None,
                           to_date: Optional[str] = None) -> List[Dict]:
        """Fetch meeting IDs from the Scottish Parliament OData events endpoint.

        Returns list of dicts with keys: id, date, title.
        """
        params: Dict = {"$format": "json", "$orderby": "EventDate desc", "$top": 200}
        filter_parts = []
        if from_date:
            filter_parts.append(f"EventDate ge datetime'{from_date}T00:00:00'")
        if to_date:
            filter_parts.append(f"EventDate le datetime'{to_date}T23:59:59'")
        if filter_parts:
            params["$filter"] = " and ".join(filter_parts)
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
            logger.debug(f"[Scottish Parliament] Events fields: {list(items[0].keys())} | sample={items[0]!r:.300}")
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

    # ------------------------------------------------------------------
    # Plenary Official Report — browser-discovered meetings + PDF parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_or_meetings(html: str) -> Dict[str, str]:
        """meeting_id -> DD-MM-YYYY for plenary result links in OR search HTML."""
        out: Dict[str, str] = {}
        for m in re.finditer(
                r"search-what-was-said-in-parliament/([\w-]+?)-(\d{2}-\d{2}-\d{4})\?meeting=(\d+)", html):
            if m.group(1) == "meeting-of-parliament":   # plenary, not a committee
                out[m.group(3)] = m.group(2)
        return out

    def _dismiss_or_cookies(self, page) -> None:
        """The Civic Cookie Control banner overlays the page and intercepts clicks —
        accept it if a button is present, else strip the nodes."""
        for sel in ["#ccc-recommended-settings", "#ccc-notify-accept", ".ccc-accept-button"]:
            loc = page.locator(sel)
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    page.wait_for_timeout(300)
                    return
            except Exception:
                pass
        try:
            page.evaluate("() => { document.querySelectorAll('[id^=ccc],.ccc-overlay')"
                          ".forEach(e => e.remove()); }")
        except Exception:
            pass

    @staticmethod
    def _wait_or_results(page) -> None:
        """OR results render via AJAX — wait until the meeting-link count stabilises."""
        import time
        last, stable, deadline = -1, 0, time.time() + 30
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            n = len(re.findall(r"meeting=\d+", page.content()))
            if n == last and n > 0:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
            last = n

    def _discover_plenary_meetings(self, from_date: Optional[str] = None,
                                   to_date: Optional[str] = None) -> List[Dict]:
        """Discover Meeting-of-the-Parliament IDs by driving the OR search in a browser.

        parliament.scot's Official Report search is a client-side SPA — the OData
        meeting entities 404 and plain HTTP can't drive the filter. We navigate a
        headless browser to the search URL with the date range + plenary filter, let
        the results render, page through them, and collect the meeting IDs behind the
        'meeting-of-parliament-{date}?meeting={id}' links. Returns [{id, date}].
        Returns [] (logged) if Playwright is unavailable.
        """
        start = from_date or "2021-05-06"
        end = to_date or date.today().isoformat()
        params = {
            "qry": "", "msp": "", "committeeSelect": "", "dateSelect": "custom",
            "dtDateFrom": start, "dtDateTo": end,
            "showPlenary": "true", "ShowDebates": "true", "ShowFMQs": "true",
            "ShowGeneralQuestions": "true", "ShowPortfolioQuestions": "true",
            "ShowSPCBQuestions": "true", "ShowTopicalQuestions": "true",
            "ShowUrgentQuestions": "true", "ResultDisplayType": "Reports",
        }
        url = f"{_OR_SEARCH}?{urlencode(params)}"

        browser = self._get_browser()
        if browser is None:
            logger.warning("[Scottish Parliament] Playwright unavailable — cannot drive the "
                           "Official Report search; plenary discovery skipped.")
            return []

        meetings: Dict[str, str] = {}
        page = None
        try:
            page = browser.new_page(user_agent=_BROWSER_UA)
            page.set_default_timeout(25000)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            self._dismiss_or_cookies(page)
            for _ in range(_MAX_OR_PAGES):
                self._wait_or_results(page)
                meetings.update(self._extract_or_meetings(page.content()))
                nxt = page.locator("a[rel=next], a:has-text('Next')")
                if not nxt.count():
                    break
                try:
                    nxt.first.click(timeout=8000)
                    page.wait_for_timeout(1200)
                except Exception:
                    break
        except Exception as e:
            logger.warning(f"[Scottish Parliament] OR search drive failed: {type(e).__name__}: {e}")
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

        def _iso(d: str) -> str:
            return f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if len(d) == 10 else d

        out = [{"id": mid, "date": _iso(d)} for mid, d in meetings.items()]
        out.sort(key=lambda m: m["date"], reverse=True)
        logger.info(f"[Scottish Parliament] {len(out)} plenary meetings discovered via OR "
                    f"search ({start} -> {end})")
        return out

    # Page-header/footer noise in the OR PDF: running date lines + bare column numbers.
    _OR_NOISE_RE = re.compile(r"^(\d{1,4}\s+)?\d{1,2}\s+[A-Za-z]+\s+\d{4}(\s+\d{1,4})?$")
    _OR_SPEAKER_RE = re.compile(
        r"^(The [A-Z][\w’'. -]+"
        r"|[A-Z][\w’'.-]+(?: [A-Z][\w’'.-]+)+(?: \([^)]+\))*"
        r"|[A-Z][\w’'.-]+ \([^)]+\)(?: \([^)]+\))*)"
        r":\s*(.*)$")

    @classmethod
    def _parse_or_contributions(cls, text: str):
        """Split OR PDF text into (speaker, contribution) pairs, dropping page noise."""
        contribs, name, buf, started = [], "", [], False
        for raw in text.splitlines():
            s = raw.strip()
            if not s or cls._OR_NOISE_RE.match(s):
                continue
            if not started:
                if cls._OR_SPEAKER_RE.match(s):
                    started = True
                else:
                    continue
            m = cls._OR_SPEAKER_RE.match(s)
            if m and len(m.group(1)) < 70:
                if name and buf:
                    contribs.append((name, " ".join(buf).strip()))
                name, buf = m.group(1), ([m.group(2)] if m.group(2) else [])
            elif name:
                buf.append(s)
        if name and buf:
            contribs.append((name, " ".join(buf).strip()))
        return [(n, t) for n, t in contribs if len(t) >= 10]

    def _fetch_or_via_api(self, meeting_id: str, meeting_date: str,
                          records: List[Dict], from_date: Optional[str]) -> int:
        """Fetch one plenary meeting's Official Report PDF and parse its contributions.

        parliament.scot/api/sitecore/CustomMedia/OfficialReport?meetingId=N returns
        the full Official Report as a PDF; we extract per-speaker contributions with
        PyMuPDF. Returns the number of records added.
        """
        if from_date and meeting_date and meeting_date < from_date:
            return 0
        try:
            import fitz  # PyMuPDF
        except Exception as e:
            logger.warning(f"[Scottish Parliament] PyMuPDF unavailable ({type(e).__name__}: {e}) "
                           "— OR PDF parsing skipped")
            return 0
        saved = dict(self.session.headers)
        self.session.headers.update({"User-Agent": _BROWSER_UA, "Accept": "application/pdf,*/*"})
        resp = self._get(_OR_MEDIA, params={"meetingId": meeting_id}, timeout=90)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0
        ct = resp.headers.get("Content-Type", "").lower()
        if "pdf" not in ct and resp.content[:5] != b"%PDF-":
            return 0
        try:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
            doc.close()
        except Exception as e:
            logger.warning(f"[Scottish Parliament] OR PDF parse error meeting {meeting_id}: "
                           f"{type(e).__name__}: {e}")
            return 0
        before = len(records)
        for name, body in self._parse_or_contributions(text):
            records.append(self._make_record(
                data_type="plenary_speech",
                member={"id": "", "name": name, "party": "", "constituency": "", "role": "MSP"},
                date=meeting_date,
                text=body,
                title="",
                metadata={"meeting_id": meeting_id, "source_format": "pdf"},
                source_url=f"{_OR_MEDIA}?meetingId={meeting_id}",
            ))
        added = len(records) - before
        if added:
            logger.info(f"[Scottish Parliament] OR meeting {meeting_id} ({meeting_date}): "
                        f"{added} contributions")
        return added

    def fetch_plenary_business(self, from_date: Optional[str] = None,
                               to_date: Optional[str] = None) -> List[Dict]:
        records: List[Dict] = []

        # ----------------------------------------------------------------
        # 1. Official Report PDFs via the media API, for plenary meetings
        #    discovered by driving the OR search in a headless browser.
        #    GET /api/sitecore/CustomMedia/OfficialReport?meetingId=NNNN -> PDF
        # ----------------------------------------------------------------
        meetings = self._discover_plenary_meetings(from_date, to_date)
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
        #    Reconnaissance (2026-06) confirmed this pattern now returns a
        #    byte-for-byte identical nav-only shell for EVERY date — recent and
        #    historical Session 6 sittings alike — so we probe only until a short
        #    run of empties re-confirms it's dead, rather than rendering dozens of
        #    shell pages on every run.
        # ----------------------------------------------------------------
        month_names = ["january", "february", "march", "april", "may", "june",
                       "july", "august", "september", "october", "november", "december"]
        tried = 0
        hit = 0
        consec_empty = 0
        for iso_date in self._recent_sitting_dates(90):
            y, mo, d = iso_date.split("-")
            slug = f"official-report-{int(d)}-{month_names[int(mo) - 1]}-{y}"
            url = (f"{_WEB}/chamber-and-committees/official-report/"
                   f"what-was-said-in-parliament/{slug}")
            added = self._scrape_or_detail(url, iso_date, records, from_date)
            tried += 1
            if added > 0:
                hit += 1
                consec_empty = 0
            else:
                consec_empty += 1
                if consec_empty >= 5:
                    break
        if tried:
            if hit == 0:
                logger.warning(
                    f"[Scottish Parliament] Date-URL OR probe: {tried} dates tried, 0 had content "
                    f"(aborted after a run of empty shells). The Session 7 rebuild moved the "
                    f"Official Report behind a search interface — the OData meeting entities 404, "
                    f"and the /what-was-said-in-parliament/{'{date}'} pattern serves an identical "
                    f"nav-only shell for every date, including historical Session 6 sittings. "
                    f"Scottish plenary stays at 0 until parliament.scot exposes a machine-readable "
                    f"Official Report source again (re-confirmed 2026-06)."
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

    # The votes-and-motions section is server-rendered. SearchVotes lists the
    # divisions (newest-first) and each motion page carries the per-member
    # roll-call grouped by party then For/Against/Abstained/Did-not-vote, with
    # member links to /msps/current-and-previous-msps/<slug>.
    _VOTES_SEARCH_API = f"{_WEB}/api/sitecore/VotesMotionsSearch/SearchVotes"
    _VOTES_REFERER = f"{_WEB}/chamber-and-committees/votes-and-motions"
    _VOTE_DIRECTION = {"For": "aye", "Against": "no",
                       "Abstained": "abstain", "Did not vote": "no_vote"}
    _MONTHS_RE = ("January|February|March|April|May|June|July|August|"
                  "September|October|November|December")

    @classmethod
    def _parse_vote_date(cls, text: str) -> str:
        """Pull the division date (preferring the date it was taken) -> YYYY-MM-DD."""
        from datetime import datetime as _dt
        for pat in (r"Taken in the Chamber on[^0-9]*(\d{1,2}\s+(?:%s)\s+\d{4})" % cls._MONTHS_RE,
                    r"Date lodged:[^0-9]*(\d{1,2}\s+(?:%s)\s+\d{4})" % cls._MONTHS_RE,
                    r"(\d{1,2}\s+(?:%s)\s+\d{4})" % cls._MONTHS_RE):
            m = re.search(pat, text)
            if m:
                try:
                    return _dt.strptime(m.group(1).strip(), "%d %B %Y").strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return ""

    def _search_vote_divisions(self, from_date: Optional[str], to_date: Optional[str],
                               max_pages: int = 80) -> List[Dict]:
        """List divisions from the SearchVotes API (newest-first).

        Returns [{ref, title, date, result}] within the date range, stopping once
        a whole page predates from_date.
        """
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": _BROWSER_UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self._VOTES_REFERER,
        })
        divisions: List[Dict] = []
        seen: set = set()
        try:
            for page in range(1, max_pages + 1):
                resp = self._get(self._VOTES_SEARCH_API, params={"pageNumber": page}, timeout=45)
                if not resp or not resp.ok:
                    break
                cards = BeautifulSoup(resp.text, "lxml").select("div.vm-list")
                if not cards:
                    break
                newest_on_page = None
                for card in cards:
                    ref_el = card.select_one("h2 a[href*='votes-and-motions/']")
                    if not ref_el:
                        continue
                    m = re.search(r"(S\d+M-[\w-]+)", ref_el.get("href", ""))
                    if not m or m.group(1) in seen:
                        continue
                    ref = m.group(1)
                    iso = self._parse_vote_date(card.get_text(" ", strip=True))
                    if iso and (newest_on_page is None or iso > newest_on_page):
                        newest_on_page = iso
                    if from_date and iso and iso < from_date:
                        continue
                    if to_date and iso and iso > to_date:
                        continue
                    seen.add(ref)
                    res_el = card.select_one(".vote_result--text")
                    divisions.append({
                        "ref": ref,
                        "title": ref_el.get_text(" ", strip=True),
                        "date": iso,
                        "result": res_el.get_text(" ", strip=True) if res_el else "",
                    })
                # newest-first: once an entire page predates the window, we're done
                if from_date and newest_on_page and newest_on_page < from_date:
                    break
        finally:
            self.session.headers.clear()
            self.session.headers.update(saved)
        return divisions

    def _fetch_division_rollcall(self, division: Dict, records: List[Dict]) -> int:
        """Fetch a division's motion page and emit one record per member vote."""
        ref = division["ref"]
        url = f"{_WEB}/chamber-and-committees/votes-and-motions/{ref}"
        saved = dict(self.session.headers)
        self.session.headers.update({"User-Agent": _BROWSER_UA})
        resp = self._get(url, timeout=45)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp or not resp.ok:
            return 0
        soup = BeautifulSoup(resp.text, "lxml")
        title = division.get("title") or ref
        v_date = division.get("date", "")
        result = division.get("result", "")
        before = len(records)
        # Each party panel: <h4 class="h5">For</h4><ul><li><a>member</a>…</ul>,
        # then Against/Abstained/Did-not-vote (just "0" text when none, so the
        # member <ul> is only present as the heading's immediate next tag sibling).
        # NB: the direction heading is an <h4> styled with a "h5" CSS class, not
        # an actual <h5> element — confirmed against live markup 2026-09-05.
        for h5 in soup.select("h4.h5"):
            direction = self._VOTE_DIRECTION.get(h5.get_text(strip=True))
            if not direction:
                continue
            ul = h5.find_next_sibling()
            if ul is None or ul.name != "ul":
                continue
            for a in ul.select("a[href*='/msps/current-and-previous-msps/']"):
                name = a.get_text(" ", strip=True)
                if not name:
                    continue
                slug = re.search(r"/msps/current-and-previous-msps/([\w-]+)", a.get("href", ""))
                records.append(self._make_record(
                    data_type="vote",
                    member={"id": slug.group(1) if slug else "", "name": name,
                            "party": "", "constituency": "", "role": "MSP"},
                    date=v_date,
                    text=f"Voted {direction} on: {title}",
                    title=title,
                    metadata={"vote_direction": direction, "division_result": result,
                              "motion_ref": ref},
                    source_url=url,
                ))
        return len(records) - before

    def fetch_votes_on_division(self, from_date: Optional[str] = None,
                                to_date: Optional[str] = None) -> List[Dict]:
        records: List[Dict] = []
        divisions = self._search_vote_divisions(from_date, to_date)
        if not divisions:
            logger.warning("[Scottish Parliament] SearchVotes returned no divisions in range")
            return records
        logger.info(f"[Scottish Parliament] {len(divisions)} divisions from SearchVotes — "
                    f"fetching per-member roll-calls...")
        hits = 0
        for i, d in enumerate(divisions):
            if i and i % 20 == 0:
                logger.info(f"[Scottish Parliament] Votes: {i}/{len(divisions)} divisions "
                            f"processed ({len(records)} records so far)")
            if self._fetch_division_rollcall(d, records):
                hits += 1
        logger.info(f"[Scottish Parliament] {hits}/{len(divisions)} divisions had roll-calls; "
                    f"{len(records)} vote records fetched")
        return records
