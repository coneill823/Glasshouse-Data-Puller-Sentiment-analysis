"""
Scottish Parliament scraper.

Members are fetched from the public OData API at https://data.parliament.scot/api.
All other entity endpoints on that API return 404; interests, questions, plenary,
and votes are scraped from https://www.parliament.scot with a browser User-Agent.
"""
import logging
import re
from datetime import date, timedelta
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
            # Party not available in the Members OData entity — may be populated via PersonParties
            party = (
                m.get("PartyName") or m.get("Party") or m.get("PartyAbbreviation")
                or m.get("PartyGroupName") or m.get("PoliticalGroupName") or ""
            )
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
        """Try to look up party membership via adjacent OData entities and fill in party field."""
        id_lookup = {m["id"]: m for m in members if m["id"]}
        for entity in ["PersonParties", "Parties", "MemberParties", "MSPParties"]:
            rows = self._odata_get(entity)
            if not rows:
                continue
            if not hasattr(self, "_party_entity_logged"):
                self._party_entity_logged = True
                logger.warning(f"[Scottish Parliament] {entity} fields: {list(rows[0].keys())} | sample={rows[0]!r:.300}")
            for row in rows:
                pid = str(row.get("PersonID") or row.get("PersonId") or row.get("MemberID") or "")
                party = (row.get("PartyName") or row.get("Party") or row.get("PartyAbbreviation")
                         or row.get("Name") or "")
                if pid and party and pid in id_lookup and not id_lookup[pid].get("party"):
                    id_lookup[pid]["party"] = party
            logger.info(f"[Scottish Parliament] Party enrichment via {entity}: done")
            break

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
        soup = None
        url = ""
        for candidate in interest_candidates:
            resp_soup = self._html_get(candidate)
            if not resp_soup:
                logger.warning(f"[Scottish Parliament] Could not load interests page: {candidate}")
                continue
            # Check the MAIN CONTENT area only — the site nav always contains
            # "About the Register of Interests" which would cause a false-positive match.
            main_el = (resp_soup.find("main")
                       or resp_soup.find("div", class_=re.compile(r"\bmain\b|\bcontent\b", re.I))
                       or resp_soup.find("body"))
            text_lower = main_el.get_text(separator=" ", strip=True).lower() if main_el else ""
            # Strip the nav — parliament.scot puts <nav> inside <main>
            for nav in (main_el.find_all("nav") if main_el else []):
                nav_text = nav.get_text(separator=" ", strip=True).lower()
                text_lower = text_lower.replace(nav_text, "")
            if any(kw in text_lower for kw in ("registered interest", "financial interest", "shareholding", "heritable property", "nature of interest", "category of interest")):
                soup = resp_soup
                url = candidate
                logger.info(f"[Scottish Parliament] Loaded interests page with content: {candidate}")
                break
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
                logger.info(f"[Scottish Parliament] Following interest sub-links from {candidate}: {sub_links[:5]}")
                for sub_href in sub_links[:5]:
                    sub_url = sub_href if sub_href.startswith("http") else f"{_WEB}{sub_href}"
                    if sub_url in interest_candidates:
                        continue  # already tried
                    sub_soup = self._html_get(sub_url)
                    if not sub_soup:
                        continue
                    sub_text = sub_soup.get_text(separator=" ", strip=True).lower()
                    if any(kw in sub_text for kw in ("register of interests", "registered interest", "financial interest", "category")):
                        soup = sub_soup
                        url = sub_url
                        logger.info(f"[Scottish Parliament] Found interests content at sub-link: {sub_url}")
                        break
                if soup:
                    break

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

    def _scrape_or_detail(self, full_url: str, date_str: str,
                          records: List[Dict], from_date: Optional[str]) -> int:
        """Scrape a single Official Report page and append any speeches to records.
        Returns the number of records added."""
        if from_date and date_str and date_str[:10] < from_date:
            return 0
        detail = self._html_get(full_url)
        if not detail:
            return 0
        if not date_str:
            date_el = detail.select_one("time[datetime], time, .date, h1")
            date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
        # Log CSS classes only once (first page) to diagnose selector gaps without flooding the log
        if not hasattr(self, "_or_css_logged"):
            all_cls = sorted({c for el in detail.select("[class]") for c in el.get("class", [])})
            logger.info(f"[Scottish Parliament] OR page CSS classes (first hit): {all_cls[:40]}")
            self._or_css_logged = True
        before = len(records)
        for contrib in detail.select(
            ".contribution, .speech, [class*='contribution'], [class*='speech'], "
            ".or-row, .or-report-row, .member-speech, .chamber-row, "
            ".qna-item, .member-contribution, tr, article, .content-row"
        ):
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
        added = len(records) - before
        if added == 0:
            body = detail.find("body")
            snippet = body.get_text(separator=" ", strip=True)[:300] if body else ""
            logger.warning(f"[Scottish Parliament] 0 contribs at {full_url} — snippet: {snippet[:200]}")
        return added

    def _fetch_meeting_ids(self, from_date: Optional[str] = None) -> List[Dict]:
        """Fetch meeting IDs from the Scottish Parliament OData events endpoint.

        Returns list of dicts with keys: id, date, title.
        """
        params: Dict = {"$format": "json", "$orderby": "EventDate desc", "$top": 200}
        if from_date:
            params["$filter"] = f"EventDate ge datetime'{from_date}T00:00:00'"
        meetings = []
        for entity in ["Events", "Meetings", "PlenaryMeetings", "ChamberMeetings", "SittingDays"]:
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
            if not soup:
                continue
            all_hrefs = [a["href"] for a in soup.select("a[href]")
                         if a.get("href", "").startswith(("/", "http"))]
            links = [h for h in all_hrefs
                     if re.search(r"\d{4}-\d{2}-\d{2}|/or-\d", h, re.I)
                     and not any(s in h for s in _SKIP_SUBNAV)]
            if not links:
                logger.warning(
                    f"[Scottish Parliament] No OR links at {url} — "
                    f"sample hrefs: {all_hrefs[:10]}"
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
        for iso_date in self._recent_sitting_dates(60):
            y, mo, d = iso_date.split("-")
            slug = f"official-report-{int(d)}-{month_names[int(mo) - 1]}-{y}"
            url = (f"{_WEB}/chamber-and-committees/official-report/"
                   f"what-was-said-in-parliament/{slug}")
            added = self._scrape_or_detail(url, iso_date, records, from_date)
            tried += 1
            if added > 0:
                hit += 1
        if tried:
            logger.info(
                f"[Scottish Parliament] Date-URL probe: {tried} dates tried, "
                f"{hit} had content, {len(records)} total records"
            )

        logger.info(f"[Scottish Parliament] {len(records)} plenary records fetched")
        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def _scrape_motion_vote_page(self, motion_ref: str, records: List[Dict],
                                  from_date: Optional[str]) -> int:
        """Scrape a single S6M-NNNN votes-and-motions page. Returns records added."""
        url = f"{_WEB}/chamber-and-committees/votes-and-motions/{motion_ref}"
        detail = self._html_get(url)
        if not detail:
            return 0
        date_el = detail.select_one("time[datetime], time, .date, [class*='date']")
        date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
        if not date_str:
            # Try parsing date from page text with regex
            body_text = detail.get_text(separator=" ", strip=True)
            dm = re.search(r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}", body_text)
            date_str = dm.group(0) if dm else ""
        if from_date and date_str and len(date_str) >= 10 and date_str[:10] < from_date:
            return 0
        title_el = detail.select_one("h1, h2, .title, .motion-title")
        div_title = title_el.get_text(strip=True) if title_el else motion_ref

        before = len(records)
        for direction, sel_list in [
            ("aye", [".ayes li", ".for li", "[class*='aye'] li", "[class*='for'] li",
                     "table tr td:nth-child(1)", "ul.ayes li"]),
            ("no", [".noes li", ".against li", "[class*='no'] li", "[class*='against'] li",
                    "table tr td:nth-child(2)", "ul.noes li"]),
            ("abstain", [".abstentions li", ".abstain li", "[class*='abstain'] li"]),
        ]:
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
        added = len(records) - before
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
        soup = self._html_get(index_url)
        if not soup:
            logger.warning(f"[Scottish Parliament] Could not load motions index: {index_url}")
            return 0

        # Collect motion refs from all links on the index page
        motion_refs = []
        seen = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"(S\d+M-\d+)", href, re.I)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                motion_refs.append(m.group(1))

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
            if not soup:
                continue

            links = [a["href"] for a in soup.select("a[href]")
                     if a.get("href", "").startswith(("/", "http"))
                     and re.search(r"/division|/vote|\d{4}-\d{2}-\d{2}|/\d+|S\d+M-\d+",
                                   a.get("href", ""), re.I)]

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
