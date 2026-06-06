"""
NI Assembly scraper using the official Open Data web services.
Service root: http://data.niassembly.gov.uk/

Available services:
  members.asmx   — MLAs
  register.asmx  — Register of Interests
  questions.asmx — Oral & Written Questions
  hansard.asmx   — Official Report (plenary speeches)
  plenary.asmx   — Divisions / Votes

For methods with date-range parameters the SOAP binding consistently returns
HTTP 500 (the service likely has it disabled).  The fallback chain is:
  1. SOAP POST (tried with common ASP.NET namespaces)
  2. HTTP GET with query-string params (ASMX HTTP-GET binding)
  3. AIMS public portal HTML scraping at https://aims.niassembly.gov.uk/
"""
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from typing import Dict, Generator, List, Optional, Tuple


def _extract_ni_speaker(text: str) -> str:
    """Extract speaker name from NI Assembly ComponentText.

    Official Report components don't carry a separate MemberName field —
    the speaker is embedded at the start of ComponentText in the form:
      "Mr Smith: speech text"
      "Mrs O'Neill (Constituency): text"
      "The Speaker: procedural text"
    Returns empty string for procedure/header lines that have no attribution.
    """
    if not text or ":" not in text:
        return ""
    prefix = text.split(":", 1)[0].strip()
    if not prefix or len(prefix) > 70:
        return ""
    # Accept if it starts with a recognised title
    if re.match(
        r"^(?:Mr|Mrs|Ms|Dr|Prof|Rev|Lord|Lady|Sir|Dame|The\s+(?:Speaker|Presiding Officer|Deputy Speaker|Minister|Principal Deputy Speaker))\b",
        prefix,
    ):
        return prefix
    # Or two or more words all starting with a capital (e.g. "John Smith")
    words = prefix.split()
    if len(words) >= 2 and all(w and w[0].isupper() for w in words):
        return prefix
    return ""

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import PARLIAMENTS

logger = logging.getLogger(__name__)

_CFG = PARLIAMENTS["ni_assembly"]
_BASE = _CFG["api_base"]          # http://data.niassembly.gov.uk
_AIMS = "https://aims.niassembly.gov.uk"
_HISTORY_START = date(2007, 1, 1)  # AIMS data begins ~2007


def _date_chunks(from_date: Optional[str] = None,
                 chunk_months: int = 6) -> Generator[Tuple[str, str], None, None]:
    """Yield (start, end) pairs in ISO YYYY-MM-DD format covering from_date to today."""
    start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else _HISTORY_START
    end = date.today()
    current = start
    delta = timedelta(days=chunk_months * 30)
    while current < end:
        chunk_end = min(current + delta, end)
        yield current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        current = chunk_end + timedelta(days=1)


def _first_list(data) -> List:
    """Dig out the first list value from an arbitrarily nested JSON response."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            result = _first_list(v)
            if result is not None:
                return result
    return []


class NIAssemblyScraper(BaseScraper):
    def __init__(self):
        super().__init__("NI Assembly")

    # Try common ASP.NET ASMX namespaces in order.
    _SOAP_NAMESPACES = [
        "http://tempuri.org/",
        "http://niassembly.gov.uk/webservices/",
        "http://niassembly.gov.uk/",
    ]

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    def _parse_asmx_response(self, resp, url_hint: str):
        """Parse a raw ASMX response (JSON or SOAP XML) into a Python object."""
        ct = resp.headers.get("Content-Type", "")
        if "json" in ct:
            try:
                return resp.json()
            except Exception:
                pass
        try:
            root = ET.fromstring(resp.content)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag.endswith("Result") and elem.text:
                    try:
                        return json.loads(elem.text)
                    except Exception:
                        return elem.text
        except ET.ParseError:
            pass
        try:
            return json.loads(resp.text)
        except Exception:
            logger.warning(f"[NI Assembly] Could not parse response from {url_hint}")
            return None

    def _asmx(self, service: str, method: str, params: Optional[Dict] = None):
        """Call an ASMX method with automatic fallback from SOAP to HTTP GET."""
        url = f"{_BASE}/{service}.asmx"

        if not params:
            resp = self._get(f"{url}/{method}")
        else:
            # 1. Try SOAP POST
            resp = self._soap_post(url, method, params)
            if resp is None:
                # 2. Fall back to HTTP GET with query-string params
                get_params = {
                    k: (f"{v}T00:00:00" if k.lower().endswith("date") and "T" not in str(v) else v)
                    for k, v in params.items()
                }
                resp = self._get(f"{url}/{method}", params=get_params)
                if resp:
                    logger.debug(f"[NI Assembly] HTTP GET succeeded for {service}/{method}")

        if not resp:
            return None
        return self._parse_asmx_response(resp, f"{url}/{method}")

    def _soap_post(self, url: str, method: str, params: Dict):
        """Send a SOAP 1.1 POST request, probing common ASP.NET namespaces."""
        import time as _time

        def _envelope(ns: str) -> bytes:
            params_xml = "".join(
                f"<{k}>{v}T00:00:00</{k}>" if k.lower().endswith("date") else f"<{k}>{v}</{k}>"
                for k, v in params.items()
            )
            return (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                "<soap:Body>"
                f'<{method} xmlns="{ns}">'
                f"{params_xml}"
                f"</{method}>"
                "</soap:Body>"
                "</soap:Envelope>"
            ).encode("utf-8")

        self._rate_limit()
        for ns in self._SOAP_NAMESPACES:
            for attempt in range(2):
                try:
                    resp = self.session.post(
                        url,
                        data=_envelope(ns),
                        headers={
                            "Content-Type": "text/xml; charset=utf-8",
                            "SOAPAction": f'"{ns}{method}"',
                        },
                        timeout=30,
                    )
                    if resp.status_code >= 500:
                        logger.debug(f"[NI Assembly] HTTP {resp.status_code} ns={ns!r}, trying next")
                        break
                    if not resp.ok:
                        logger.error(f"[NI Assembly] HTTP {resp.status_code} from {url}/{method}")
                        return None
                    return resp
                except Exception as e:
                    if attempt == 0:
                        _time.sleep(2)
                        continue
                    logger.warning(f"[NI Assembly] SOAP error: {e}")
                    break

        return None  # all namespaces tried — caller will try HTTP GET

    def _aims_html(self, path: str, params: Optional[Dict] = None) -> Optional[BeautifulSoup]:
        """Fetch an AIMS portal HTML page with browser-like headers to avoid 403."""
        url = f"{_AIMS}{path}" if not path.startswith("http") else path
        # Temporarily override User-Agent — AIMS blocks the default bot UA
        saved = dict(self.session.headers)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Referer": _AIMS,
        })
        resp = self._get(url, params=params)
        self.session.headers.clear()
        self.session.headers.update(saved)
        if not resp:
            return None
        return BeautifulSoup(resp.text, "lxml")

    def _discover_asmx_methods(self, service: str) -> List[str]:
        """Fetch the ASMX service listing page and extract available method names.

        ASMX services return an HTML page at their root URL that lists every
        web method as a link like <a href="hansard.asmx?op=MethodName">.
        """
        resp = self._get(f"{_BASE}/{service}.asmx")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        methods = []
        for link in soup.find_all("a", href=re.compile(r"\?op=")):
            m = re.search(r"\?op=(.+)", link.get("href", ""))
            if m:
                methods.append(m.group(1))
        if methods:
            logger.debug(f"[NI Assembly] {service}.asmx methods: {methods}")
        return methods



    def fetch_members(self) -> List[Dict]:
        # GetAllCurrentMembers_JSON is the primary method; fall back to alternates
        # if the first call flakes (the endpoint occasionally returns empty on a
        # cold connection — register/questions on the same host work seconds later).
        rows = []
        for method in ("GetAllCurrentMembers_JSON", "GetAllMembers_JSON",
                       "GetMembers_JSON", "GetAllMembersList_JSON"):
            rows = _first_list(self._asmx("members", method))
            if rows:
                if method != "GetAllCurrentMembers_JSON":
                    logger.warning(f"[NI Assembly] fetched members via fallback method {method}")
                break
        members = []
        for m in rows:
            members.append({
                "id": str(m.get("PersonId", m.get("MemberId", ""))),
                "name": m.get("MemberName", m.get("FullDisplayName", "")),
                "party": m.get("PartyName", m.get("Party", "")),
                "constituency": m.get("ConstituencyName", m.get("Constituency", "")),
                "role": "MLA",
                "status": "current",
            })
        # Last-resort fallback: derive a partial member roster from the register
        # of interests (which exposes PersonId + MemberName) so a transient members
        # outage doesn't zero out the whole correlation cache.
        if not members:
            logger.warning("[NI Assembly] members endpoint returned 0 — deriving roster from register of interests")
            seen = set()
            for entry in _first_list(self._asmx("register", "GetAllRegisteredInterests_JSON")):
                pid = str(entry.get("PersonId", ""))
                name = entry.get("MemberName", "")
                if pid and pid not in seen and name:
                    seen.add(pid)
                    members.append({
                        "id": pid, "name": name, "party": "",
                        "constituency": "", "role": "MLA", "status": "current",
                    })
        logger.info(f"[NI Assembly] {len(members)} MLAs fetched")
        return members

    def _member_lookup(self, members: List[Dict]) -> Dict[str, Dict]:
        return {m["id"]: m for m in members}

    # ------------------------------------------------------------------
    # Register of interests
    # ------------------------------------------------------------------

    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        records = self._fetch_interests_asmx(members)
        if not records:
            logger.info("[NI Assembly] ASMX register returned 0 — trying AIMS portal HTML")
            records = self._fetch_interests_aims(members)
        logger.info(f"[NI Assembly] {len(records)} interest records fetched")
        return records

    def _fetch_interests_asmx(self, members: List[Dict]) -> List[Dict]:
        known_interest_methods = [
            "GetAllRegisteredInterests_JSON",
            "GetCurrentMembersRegisteredInterests_JSON",
            "GetAllMemberInterests_JSON",
            "GetAllCurrentMemberInterests_JSON",
            "GetMemberInterests_JSON",
            "GetRegisterOfInterests_JSON",
            "GetAllInterests_JSON",
            "GetAllRegisteredInterests",
            "GetCurrentMembersRegisteredInterests",
        ]
        discovered = self._discover_asmx_methods("register")
        interest_methods = list(dict.fromkeys(
            known_interest_methods + [m for m in discovered if "interest" in m.lower()]
        ))

        rows = []
        used_url = f"{_BASE}/register.asmx"
        for method in interest_methods:
            # The NI Assembly register.asmx service is HTTP-only (not HTTPS).
            # Build both HTTP and HTTPS variants so the correct one is tried first.
            http_url = f"http://data.niassembly.gov.uk/register.asmx/{method}"
            https_url = f"{_BASE}/register.asmx/{method}"
            for url in (http_url, https_url):
                resp = self._get(url)
                if not resp:
                    continue
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct or method.endswith("_JSON"):
                    try:
                        rows = _first_list(resp.json())
                        if rows:
                            used_url = url
                            logger.info(f"[NI Assembly] Register: got {len(rows)} rows from {url}")
                            break
                    except Exception:
                        pass
                try:
                    root = ET.fromstring(resp.text)
                    for elem in root.iter():
                        if "}" in elem.tag:
                            elem.tag = elem.tag.split("}", 1)[1]
                    xml_rows = []
                    for interest in root.iter("RegisteredInterest"):
                        xml_rows.append({k.tag: k.text for k in interest})
                    if xml_rows:
                        rows = xml_rows
                        used_url = url
                        logger.info(f"[NI Assembly] Register: got {len(rows)} XML rows from {url}")
                        break
                except ET.ParseError:
                    pass
            if rows:
                break

        if not rows:
            logger.warning("[NI Assembly] All register.asmx methods returned 0 rows")
            return []

        if rows:
            logger.warning(f"[NI Assembly] Register sample fields: {list(rows[0].keys())} | sample={dict(list(rows[0].items())[:6])!r:.300}")

        lookup = self._member_lookup(members)
        records = []
        for item in rows:
            pid = str(item.get("PersonId", item.get("MemberId", "")))
            member = lookup.get(pid, {
                "id": pid,
                "name": item.get("MemberName", ""),
                "party": item.get("PartyName", ""),
                "constituency": "",
                "role": "MLA",
            })
            # Confirmed field name from API: RegisterEntry (not InterestDescription/Description)
            desc = (item.get("RegisterEntry") or item.get("InterestDescription")
                    or item.get("Description") or item.get("Interest") or "")
            if not desc:
                continue
            # Confirmed: RegisterCategory, RegisterCategoryId, RegisterEntryStartDate
            cat = (item.get("RegisterCategory") or item.get("CategoryName")
                   or item.get("Category") or "")
            cat_id = str(item.get("RegisterCategoryId") or item.get("InterestId")
                        or item.get("Id") or "")
            reg_date = (item.get("RegisterEntryStartDate") or item.get("RegisteredDate")
                        or item.get("Date") or "")
            records.append(self._make_record(
                data_type="register_of_interests",
                member=member,
                date=reg_date,
                text=desc,
                title=cat,
                metadata={
                    "category": cat,
                    "interest_id": cat_id,
                },
                source_url=used_url,
            ))
        return records

    def _fetch_interests_aims(self, members: List[Dict]) -> List[Dict]:
        """Scrape register of interests from the AIMS public portal.

        URL: https://aims.niassembly.gov.uk/mlas/registerofinterests.aspx
        The page lists interests grouped by MLA with collapsible sections.
        """
        records = []
        lookup_name = {m["name"].lower(): m for m in members}
        lookup_id = {m["id"]: m for m in members}

        for path in [
            "/mlas/registerofinterests.aspx",
            "/mlas/register.aspx",
            "/mlas/interests.aspx",
            "/mlas/registeredinterests.aspx",
        ]:
            soup = self._aims_html(path)
            if not soup:
                logger.warning(f"[NI Assembly] Register AIMS: could not load {_AIMS}{path}")
                continue

            body_text = soup.get_text(separator=" ", strip=True).lower()
            if not any(kw in body_text for kw in ("interest", "register", "category")):
                logger.warning(f"[NI Assembly] Register AIMS: no interest keywords at {_AIMS}{path}")
                continue

            logger.info(f"[NI Assembly] Register AIMS: loaded {_AIMS}{path}")

            # The AIMS portal typically renders each MLA's interests in a panel/accordion.
            # Selectors cover GridView rows, panel groups, and definition lists.
            current_member: Dict = {}
            current_category = ""

            for el in soup.select("h2, h3, h4, tr, li, p, .panel-heading, .accordion-heading, dt, dd"):
                tag = el.name
                text = el.get_text(strip=True)
                if not text:
                    continue

                # Detect MLA name headings
                if tag in ("h2", "h3", "h4") or "panel-heading" in " ".join(el.get("class", [])):
                    # Check if this matches a known member name
                    cand = lookup_name.get(text.lower())
                    if cand:
                        current_member = cand
                        current_category = ""
                        continue
                    # Also try PersonId embedded in anchor href
                    link = el.select_one("a[href]")
                    if link:
                        m_id_match = re.search(r"[Pp]erson[Ii][Dd]=(\d+)|/(\d+)", link.get("href", ""))
                        if m_id_match:
                            pid = m_id_match.group(1) or m_id_match.group(2)
                            cand = lookup_id.get(pid)
                            if cand:
                                current_member = cand
                                current_category = ""
                                continue
                    # Treat as a category heading if we already have a member
                    if current_member and len(text) < 100:
                        current_category = text
                    continue

                # Category rows in table cells
                if tag == "tr":
                    cols = [td.get_text(strip=True) for td in el.find_all("td")]
                    if len(cols) >= 2:
                        # Try to identify member / category / interest columns
                        possible_member = cols[0]
                        m_cand = lookup_name.get(possible_member.lower())
                        if m_cand:
                            current_member = m_cand
                        possible_cat = cols[1] if len(cols) > 1 else ""
                        possible_desc = cols[2] if len(cols) > 2 else cols[-1]
                        if not possible_desc:
                            continue
                        if possible_cat and len(possible_cat) < 80:
                            current_category = possible_cat
                        if current_member and possible_desc and len(possible_desc) > 3:
                            records.append(self._make_record(
                                data_type="register_of_interests",
                                member=current_member,
                                date="",
                                text=possible_desc,
                                title=current_category,
                                metadata={"category": current_category, "source": "aims_portal"},
                                source_url=f"{_AIMS}{path}",
                            ))
                    continue

                # List items and definition terms/descriptions
                if tag in ("li", "dd", "p") and current_member and len(text) > 5:
                    if tag == "dt" and len(text) < 100:
                        current_category = text
                        continue
                    records.append(self._make_record(
                        data_type="register_of_interests",
                        member=current_member,
                        date="",
                        text=text,
                        title=current_category,
                        metadata={"category": current_category, "source": "aims_portal"},
                        source_url=f"{_AIMS}{path}",
                    ))

            if records:
                logger.info(f"[NI Assembly] Register AIMS: {len(records)} records from {_AIMS}{path}")
                break

        if not records:
            logger.warning("[NI Assembly] Register AIMS: 0 records parsed from all paths")
        return records

    # ------------------------------------------------------------------
    # Questions (oral + written)
    # ------------------------------------------------------------------

    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        records = self._fetch_questions_asmx(from_date)
        if not records:
            logger.info("[NI Assembly] ASMX questions returned 0 — trying AIMS portal")
            records = self._fetch_questions_aims(from_date)
        logger.info(f"[NI Assembly] {len(records)} question records fetched")
        return records

    def _fetch_questions_asmx(self, from_date: Optional[str] = None) -> List[Dict]:
        # Skip SOAP (consistently 500 for date params) — use HTTP GET directly.
        records = []
        endpoints = {
            "oral": "GetQuestionsForOralAnswer_TabledInRange_JSON",
            "written": "GetQuestionsForWrittenAnswer_TabledInRange_JSON",
        }
        for q_type, method in endpoints.items():
            chunks = list(_date_chunks(from_date))
            for chunk_idx, (start, end) in enumerate(chunks):
                if chunk_idx % 5 == 0:
                    logger.info(f"[NI Assembly] Questions ({q_type}): chunk {chunk_idx + 1}/{len(chunks)} ({start} → {end}), {len(records)} records so far")
                url = f"{_BASE}/questions.asmx/{method}"
                resp = self._get(url, params={
                    "startDate": f"{start}T00:00:00",
                    "endDate": f"{end}T00:00:00",
                })
                if not resp:
                    continue
                data = self._parse_asmx_response(resp, url)
                items = _first_list(data)
                if items and not records:
                    logger.warning(f"[NI Assembly] Question sample fields ({q_type}): {list(items[0].keys())} | sample={dict(list(items[0].items())[:6])!r:.300}")
                for q in items:
                    q_text = q.get("QuestionText", q.get("Text", ""))
                    answer = q.get("AnswerText", q.get("Answer", ""))
                    combined = f"Question: {q_text}\n\nAnswer: {answer}" if answer else q_text
                    records.append(self._make_record(
                        data_type="question",
                        member={
                            "id": str(q.get("TablerPersonId") or q.get("PersonId") or q.get("MemberId") or ""),
                            "name": (q.get("TablerName") or q.get("MemberName") or q.get("Member") or ""),
                            "party": q.get("PartyName") or q.get("Party") or "",
                            "constituency": q.get("ConstituencyName") or q.get("Constituency") or "",
                            "role": "MLA",
                        },
                        date=q.get("TabledDate") or q.get("RaisedDate") or q.get("Date") or "",
                        text=combined,
                        title=q.get("Reference") or q.get("SubjectTitle") or q.get("Subject") or q.get("Title") or "",
                        metadata={
                            "question_id": str(q.get("DocumentId") or q.get("QuestionId") or q.get("Id") or ""),
                            "question_type": q_type,
                            "minister": q.get("MinisterTitle") or q.get("MinisterName") or q.get("AnsweredBy") or "",
                            "department": q.get("Department") or q.get("DepartmentName") or "",
                            "status": q.get("Status") or "",
                            "answer_text": answer,
                        },
                        source_url=f"{_BASE}/questions.asmx/{method}",
                    ))
        return records

    def _fetch_questions_aims(self, from_date: Optional[str] = None) -> List[Dict]:
        """Scrape questions from the AIMS public portal."""
        records = []
        for q_type, path in [
            ("written", "/questions/writtenresults.aspx"),
            ("oral", "/questions/oralresults.aspx"),
        ]:
            page = 1
            while page <= 50:  # cap pages per type
                soup = self._aims_html(path, params={"pg": page})
                if not soup:
                    break

                # AIMS uses ASP.NET GridView — look for any data table
                table = (
                    soup.find("table", id=re.compile(r"Grid|grid|results|Results"))
                    or soup.find("table", class_=re.compile(r"grid|table|results", re.I))
                    or soup.find("table", attrs={"cellpadding": True})
                )
                if not table:
                    break

                rows = table.find_all("tr")[1:]  # skip header
                if not rows:
                    break

                for row in rows:
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cols) < 2:
                        continue
                    # Common column orders: Date | Member | Subject | [Dept]
                    # or: QuestionNo | Member | Date | Subject
                    date_str = ""
                    member_name = ""
                    subject = ""
                    text = ""
                    for i, col in enumerate(cols):
                        if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", col) or re.match(r"\d{4}-\d{2}-\d{2}", col):
                            date_str = col
                        elif i == len(cols) - 1:
                            text = col
                        elif not member_name and re.search(r"[A-Z][a-z]+ [A-Z]", col):
                            member_name = col
                        elif not subject and len(col) > 10:
                            subject = col

                    # Try to get full question text from detail link
                    detail_link = row.find("a", href=True)
                    if detail_link:
                        detail_href = detail_link["href"]
                        detail_url = (detail_href if detail_href.startswith("http")
                                      else f"{_AIMS}{detail_href}")
                        detail_soup = self._aims_html(
                            detail_href if not detail_href.startswith("http") else detail_href.replace(_AIMS, "")
                        )
                        if detail_soup:
                            # Full question text is usually in a div/span with the question
                            for sel in ["#lblQuestionText", ".question-text", "div.question", "td.question"]:
                                el = detail_soup.select_one(sel)
                                if el:
                                    text = el.get_text(strip=True)
                                    break
                            if not date_str:
                                for sel in ["#lblTabledDate", ".tabled-date", "span.date"]:
                                    el = detail_soup.select_one(sel)
                                    if el:
                                        date_str = el.get_text(strip=True)
                                        break
                            if not member_name:
                                for sel in ["#lblMemberName", ".member-name", "span.member"]:
                                    el = detail_soup.select_one(sel)
                                    if el:
                                        member_name = el.get_text(strip=True)
                                        break

                    if not text and subject:
                        text = subject
                    if not text:
                        continue

                    if from_date and date_str and len(date_str) >= 10:
                        try:
                            q_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                            if q_date < datetime.strptime(from_date, "%Y-%m-%d").date():
                                continue
                        except ValueError:
                            pass

                    records.append(self._make_record(
                        data_type="question",
                        member={"id": "", "name": member_name, "party": "",
                                "constituency": "", "role": "MLA"},
                        date=date_str,
                        text=text,
                        title=subject,
                        metadata={"question_type": q_type},
                        source_url=f"{_AIMS}{path}",
                    ))

                # Check for next page
                next_link = soup.find("a", string=re.compile(r"Next|next|›|»"))
                if not next_link:
                    break
                page += 1

        return records

    # ------------------------------------------------------------------
    # Plenary business (Official Report / Hansard)
    # ------------------------------------------------------------------

    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        records = self._fetch_plenary_asmx(from_date)
        if not records:
            logger.info("[NI Assembly] ASMX plenary returned 0 — trying AIMS portal")
            records = self._fetch_plenary_aims(from_date)
        logger.info(f"[NI Assembly] {len(records)} plenary records fetched")
        return records

    def _fetch_plenary_asmx(self, from_date: Optional[str] = None) -> List[Dict]:
        # Discover actual method names from the ASMX service listing page,
        # then try known candidates and any "report" methods we find.
        known = ["GetAllHansardReports_JSON", "GetHansardReports_JSON",
                 "GetAllPlenaryReports_JSON"]
        discovered = self._discover_asmx_methods("hansard")
        candidates = list(dict.fromkeys(
            known + [m for m in discovered if "report" in m.lower() and m.endswith("_JSON")]
        ))

        reports = []
        for method in candidates:
            data = self._asmx("hansard", method)
            reports = _first_list(data)
            if reports:
                logger.info(f"[NI Assembly] {method} returned {len(reports)} reports")
                break
            logger.debug(f"[NI Assembly] {method} returned no reports")
        if not reports:
            return []

        if from_date:
            cutoff = datetime.strptime(from_date, "%Y-%m-%d").date()
            filtered = []
            for r in reports:
                r_date_str = r.get("PlenaryDate", r.get("Date", ""))
                try:
                    if datetime.strptime(r_date_str[:10], "%Y-%m-%d").date() >= cutoff:
                        filtered.append(r)
                except ValueError:
                    filtered.append(r)
            reports = filtered

        # Log first report's keys so we can see the actual field names in the run log
        if reports:
            logger.info(f"[NI Assembly] Sample report fields: {list(reports[0].keys())}")
            logger.info(f"[NI Assembly] Sample report data: {reports[0]}")

        logger.info(f"[NI Assembly] Plenary: fetching speeches for {len(reports)} reports — this may take several minutes...")
        records = []
        for i, report in enumerate(reports):
            if i % 50 == 0:
                logger.info(f"[NI Assembly] Plenary: {i}/{len(reports)} reports processed ({len(records)} speeches so far)")
            # NI Assembly uses HansardReportId; fall back to generic names
            report_id = str(
                report.get("ReportDocId",          # actual field name from API
                report.get("HansardReportId",
                report.get("ReportId",
                report.get("reportId",
                report.get("Id", report.get("id", ""))))))
            )
            report_date = report.get("PlenaryDate", report.get("Date", report.get("date", "")))
            if not report_id:
                continue
            comp_url = f"{_BASE}/hansard.asmx/GetHansardComponentsByReportId_JSON"
            # "reportId" is confirmed as the correct parameter name; try it first.
            # Other names are fallbacks in case the service changes.
            comp_resp = (
                self._get(comp_url, params={"reportId": report_id})
                or self._get(comp_url, params={"ReportDocId": report_id})
                or self._get(comp_url, params={"HansardReportId": report_id})
                or self._get(comp_url, params={"id": report_id})
            )
            comp_data = self._parse_asmx_response(comp_resp, comp_url) if comp_resp else None
            comp_items = _first_list(comp_data)
            if i == 0:
                if comp_items:
                    logger.warning(f"[NI Assembly] Plenary component fields: {list(comp_items[0].keys())} | sample={comp_items[0]!r:.400}")
                else:
                    logger.warning(f"[NI Assembly] Component fetch for first report_id={report_id!r} returned 0 items (comp_resp={bool(comp_resp)})")

            # Track speaker across components: many components are continuation paragraphs
            # with no attribution — carry the last known speaker forward so those lines
            # are attributed rather than left blank.
            current_name = ""
            current_id = ""

            for item in comp_items:
                text = item.get("ComponentText", item.get("Text", item.get("Speech", "")))
                if not text or len(text.strip()) < 10:
                    continue
                # NI Assembly API has no separate MemberName field in component records.
                # Try ComponentHeader (often the speaker name for speech contributions),
                # filtering out time-of-day strings like "10:30".
                comp_header = item.get("ComponentHeader", "")
                header_is_time = bool(re.match(r"^\d{1,2}:\d{2}", comp_header.strip())) if comp_header else True
                speaker_from_header = comp_header if (comp_header and not header_is_time and len(comp_header) < 80) else ""
                name = (item.get("MemberName") or item.get("Speaker")
                        or speaker_from_header or _extract_ni_speaker(text) or "")
                member_id = str(item.get("PersonId", item.get("MemberId", "")))

                if name:
                    # New speaker detected — update carry-forward state
                    current_name = name
                    current_id = member_id
                elif current_name:
                    # Continuation paragraph — use last known speaker
                    name = current_name
                    if not member_id:
                        member_id = current_id

                # Reset carry-forward on procedural items (ComponentType indicates agenda headers)
                comp_type = item.get("ComponentType", "")
                if comp_type and re.search(r"Head|Agenda|Procedur|Title|Item", comp_type, re.I):
                    current_name = ""
                    current_id = ""

                records.append(self._make_record(
                    data_type="plenary_speech",
                    member={
                        "id": member_id,
                        "name": name,
                        "party": item.get("PartyName", item.get("Party", "")),
                        "constituency": item.get("ConstituencyName", ""),
                        "role": "MLA",
                    },
                    date=report_date,
                    text=text,
                    title=item.get("ComponentTitle", item.get("AgendaItem", "")),
                    metadata={
                        "report_id": report_id,
                        "component_id": str(item.get("ComponentId", item.get("Id", ""))),
                    },
                    source_url=f"{_BASE}/hansard.asmx",
                ))
        return records

    def _fetch_plenary_aims(self, from_date: Optional[str] = None) -> List[Dict]:
        """Scrape Official Report index from AIMS portal."""
        records = []
        for path in [
            "/officialreport/officialreports.aspx",
            "/officialreport/report.aspx",
            "/officialreport/",
        ]:
            soup = self._aims_html(path)
            if not soup:
                continue

            # Find links to individual report pages
            report_links = []
            for link in soup.find_all("a", href=re.compile(r"report.*id=|reportId=|\d{4}-\d{2}-\d{2}", re.I)):
                href = link.get("href", "")
                report_links.append(href if href.startswith("http") else f"{_AIMS}{href}")

            if not report_links:
                continue

            for report_url in report_links[:100]:  # cap per run
                report_soup = self._aims_html(
                    report_url.replace(_AIMS, "") if report_url.startswith(_AIMS) else report_url
                )
                if not report_soup:
                    continue

                date_el = report_soup.find(id=re.compile(r"date|Date")) or report_soup.find("h1")
                report_date = date_el.get_text(strip=True) if date_el else ""

                if from_date and report_date:
                    try:
                        parsed = datetime.strptime(report_date[:10], "%Y-%m-%d").date()
                        if parsed < datetime.strptime(from_date, "%Y-%m-%d").date():
                            continue
                    except ValueError:
                        pass

                for contrib in report_soup.select(".contribution, .speech, tr.contribution"):
                    speaker_el = contrib.select_one(".speaker, .member, strong, b")
                    text_el = contrib.select_one(".text, .speech-text, p, td.speech")
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
                            "role": "MLA",
                        },
                        date=report_date,
                        text=text,
                        title="",
                        metadata={"source": "aims_portal"},
                        source_url=report_url,
                    ))
            break  # used the first path that worked

        return records

    # ------------------------------------------------------------------
    # Votes on division
    # ------------------------------------------------------------------

    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        records = self._fetch_votes_asmx(from_date)
        if not records:
            logger.info("[NI Assembly] ASMX votes returned 0 — trying AIMS portal")
            records = self._fetch_votes_aims(from_date)
        logger.info(f"[NI Assembly] {len(records)} vote records fetched")
        return records

    def _parse_member_votes(self, member_votes, div_id: str, div_title: str,
                            div_date: str, div_result: str, div_type: str,
                            source_url: str) -> List[Dict]:
        """Convert a list of MemberVoting dicts into vote records."""
        records = []
        for mv in member_votes:
            if not isinstance(mv, dict):
                continue
            mv_dir = str(mv.get("VoteType") or mv.get("Vote") or mv.get("Decision")
                         or mv.get("VotedFor") or "").lower()
            if mv_dir in ("aye", "yes", "for", "1", "true"):
                direction = "aye"
            elif mv_dir in ("no", "noe", "noes", "against", "2", "false"):
                direction = "no"
            else:
                direction = mv_dir or "unknown"
            records.append(self._make_record(
                data_type="vote",
                member={
                    "id": str(mv.get("PersonID") or mv.get("PersonId") or mv.get("MemberId") or mv.get("MemberID") or ""),
                    "name": mv.get("MemberName") or mv.get("Name") or mv.get("DisplayName") or "",
                    "party": mv.get("PartyName") or mv.get("Party") or "",
                    "constituency": mv.get("ConstituencyName") or mv.get("Constituency") or "",
                    "role": "MLA",
                },
                date=div_date,
                text=f"Voted {direction} on: {div_title}",
                title=div_title,
                metadata={
                    "division_id": div_id,
                    "vote_direction": direction,
                    "division_result": div_result,
                    "division_type": div_type,
                },
                source_url=source_url,
            ))
        return records

    def _fetch_votes_asmx(self, from_date: Optional[str] = None) -> List[Dict]:
        # Skip SOAP (consistently 500 for date params) — use HTTP GET directly.
        # Discover available plenary methods so we can try per-division endpoints
        # when the bulk GetVotesOnDivision_JSON returns empty MemberVoting lists.
        if not hasattr(self, "_plenary_methods"):
            self._plenary_methods = self._discover_asmx_methods("plenary")
            if self._plenary_methods:
                logger.warning(f"[NI Assembly] plenary.asmx methods: {self._plenary_methods}")
        # Per-division member vote methods — confirmed working method first to avoid 500-storm
        _CONFIRMED = [
            ("GetDivisionMemberVoting_JSON", "DocumentId"),
        ]
        _FALLBACK_METHODS = [
            "GetMemberVotingByEventId_JSON",
            "GetMembersVotingByEventId_JSON",
            "GetMemberVotesForEvent_JSON",
            "GetVotingByEventId_JSON",
            "GetMemberVotingByDocumentId_JSON",
            "GetMembersVotingByDocumentId_JSON",
        ] + [m for m in getattr(self, "_plenary_methods", [])
             if re.search(r"member.*vot|vot.*member", m, re.I)
             and m not in ("GetVotesOnDivision_JSON", "GetDivisionMemberVoting_JSON")]

        records = []
        for start, end in _date_chunks(from_date):
            url = f"{_BASE}/plenary.asmx/GetVotesOnDivision_JSON"
            resp = self._get(url, params={
                "startDate": f"{start}T00:00:00",
                "endDate": f"{end}T00:00:00",
            })
            if not resp:
                continue
            data = self._parse_asmx_response(resp, url)
            vote_items = _first_list(data)
            if vote_items and not records:
                logger.warning(f"[NI Assembly] Vote sample fields: {list(vote_items[0].keys())} | sample={dict(list(vote_items[0].items())[:6])!r:.300}")
            for division in vote_items:
                div_id = str(division.get("EventID") or division.get("DocumentID") or division.get("DivisionId") or "")
                div_title = division.get("DivisionSubject") or division.get("MotionText") or division.get("DivisionTitle") or ""
                div_date = division.get("DivisionDate") or division.get("Date") or ""
                div_result = division.get("DivisionResult") or division.get("Result") or ""
                div_type = division.get("DivisonType") or division.get("DivisionType") or ""

                member_votes = division.get("MemberVoting") or []
                if isinstance(member_votes, dict):
                    member_votes = next(iter(member_votes.values()), []) if member_votes else []
                if not isinstance(member_votes, list):
                    member_votes = []

                if member_votes and not hasattr(self, "_vote_member_fields_logged"):
                    self._vote_member_fields_logged = True
                    sample_mv = member_votes[0] if member_votes else {}
                    logger.warning(f"[NI Assembly] MemberVoting[0]: type={type(sample_mv).__name__} | {sample_mv!r:.300}")

                doc_id = str(division.get("DocumentID") or division.get("DocumentId") or div_id)
                if not member_votes and div_id:
                    # MemberVoting is empty in the bulk response — try per-division endpoints.
                    # Try confirmed working method (GetDivisionMemberVoting_JSON + DocumentId) first
                    # to avoid the thundering-herd of HTTP-500 retries from other candidates.
                    if not hasattr(self, "_per_div_method_found"):
                        # Try confirmed pairs first
                        for method, id_param in _CONFIRMED:
                            id_val = doc_id if id_param.lower().startswith("document") else div_id
                            per_url = f"{_BASE}/plenary.asmx/{method}"
                            per_resp = self._get(per_url, params={id_param: id_val})
                            if not per_resp:
                                continue
                            per_data = self._parse_asmx_response(per_resp, per_url)
                            candidate = _first_list(per_data)
                            if candidate and isinstance(candidate[0], dict):
                                member_votes = candidate
                                self._per_div_method_found = method
                                self._per_div_method_param = id_param
                                logger.warning(f"[NI Assembly] Per-division method found: {method} (param={id_param}) → {len(member_votes)} votes | sample={member_votes[0]!r:.300}")
                                break
                        # If confirmed methods failed, try fallbacks
                        if not member_votes:
                            for method in _FALLBACK_METHODS:
                                per_url = f"{_BASE}/plenary.asmx/{method}"
                                for id_param, id_val in [
                                    ("EventId", div_id), ("eventId", div_id),
                                    ("DocumentId", doc_id), ("documentId", doc_id),
                                ]:
                                    per_resp = self._get(per_url, params={id_param: id_val})
                                    if not per_resp:
                                        continue
                                    per_data = self._parse_asmx_response(per_resp, per_url)
                                    candidate = _first_list(per_data)
                                    if candidate and isinstance(candidate[0], dict):
                                        member_votes = candidate
                                        self._per_div_method_found = method
                                        self._per_div_method_param = id_param
                                        logger.warning(f"[NI Assembly] Per-division fallback found: {method} (param={id_param}) → {len(member_votes)} votes | sample={member_votes[0]!r:.300}")
                                        break
                                if member_votes:
                                    break
                        if not member_votes:
                            self._per_div_method_found = None  # mark as not found
                    elif getattr(self, "_per_div_method_found", None):
                        # Re-use the working method with correct param value
                        method = self._per_div_method_found
                        param = self._per_div_method_param
                        id_val = doc_id if param.lower().startswith("document") else div_id
                        per_url = f"{_BASE}/plenary.asmx/{method}"
                        per_resp = self._get(per_url, params={param: id_val})
                        if per_resp:
                            per_data = self._parse_asmx_response(per_resp, per_url)
                            candidate = _first_list(per_data)
                            if candidate and isinstance(candidate[0], dict):
                                member_votes = candidate

                if not member_votes:
                    records.append(self._make_record(
                        data_type="vote",
                        member={"id": "", "name": "", "party": "", "constituency": "", "role": "MLA"},
                        date=div_date,
                        text=f"Division: {div_title}",
                        title=div_title,
                        metadata={"division_id": div_id, "division_result": div_result, "division_type": div_type},
                        source_url=f"{_BASE}/plenary.asmx",
                    ))
                else:
                    records.extend(self._parse_member_votes(
                        member_votes, div_id, div_title, div_date,
                        div_result, div_type, f"{_BASE}/plenary.asmx",
                    ))
        return records

    def _fetch_votes_aims(self, from_date: Optional[str] = None) -> List[Dict]:
        """Scrape division results from the AIMS public portal."""
        records = []
        soup = self._aims_html("/plenary/divisions.aspx")
        if not soup:
            return records

        # Find links to individual division pages
        for link in soup.find_all("a", href=re.compile(r"division|Division", re.I)):
            href = link.get("href", "")
            detail_url = href if href.startswith("http") else f"{_AIMS}{href}"
            detail_path = href if not href.startswith("http") else href.replace(_AIMS, "")

            # Get division date and title from the list row
            row = link.find_parent("tr") or link.find_parent("li")
            div_title = link.get_text(strip=True)
            div_date = ""
            if row:
                cols = row.find_all("td")
                for col in cols:
                    text = col.get_text(strip=True)
                    if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text) or re.match(r"\d{4}-\d{2}-\d{2}", text):
                        div_date = text
                        break

            if from_date and div_date:
                try:
                    parsed = datetime.strptime(div_date[:10], "%Y-%m-%d").date()
                    if parsed < datetime.strptime(from_date, "%Y-%m-%d").date():
                        continue
                except ValueError:
                    pass

            detail_soup = self._aims_html(detail_path)
            if not detail_soup:
                continue

            # Extract title and date from detail page if not found on listing
            if not div_title or not div_date:
                h1 = detail_soup.find("h1") or detail_soup.find("h2")
                if h1 and not div_title:
                    div_title = h1.get_text(strip=True)
                for id_pat in ["lblDate", "divDate", "date"]:
                    el = detail_soup.find(id=re.compile(id_pat, re.I))
                    if el and not div_date:
                        div_date = el.get_text(strip=True)
                        break

            # Common AIMS division detail patterns for voter lists
            for direction, patterns in [
                ("aye", [r"aye|for|in favour", r"Aye|For"]),
                ("no", [r"no|against|noe", r"No|Against"]),
                ("abstain", [r"abstain", r"Abstain"]),
            ]:
                # Try heading-based approach: find heading then siblings
                heading_found = None
                for tag in detail_soup.find_all(["h2", "h3", "h4", "strong", "th"]):
                    tag_text = tag.get_text(strip=True).lower()
                    if any(re.search(p, tag_text) for p in patterns):
                        heading_found = tag
                        break

                voter_names = []
                if heading_found:
                    # Collect names from following sibling list items or table cells
                    for sibling in heading_found.find_next_siblings():
                        if sibling.name in ("h2", "h3", "h4", "strong") and sibling != heading_found:
                            break  # next section
                        for name_el in sibling.find_all(["li", "td", "span", "a"]):
                            name = name_el.get_text(strip=True)
                            if name and len(name) > 3 and re.search(r"[A-Z][a-z]", name):
                                voter_names.append(name)
                        if sibling.name == "li":
                            voter_names.append(sibling.get_text(strip=True))

                for name in voter_names:
                    records.append(self._make_record(
                        data_type="vote",
                        member={"id": "", "name": name, "party": "",
                                "constituency": "", "role": "MLA"},
                        date=div_date,
                        text=f"Voted {direction} on: {div_title}",
                        title=div_title,
                        metadata={
                            "vote_direction": direction,
                            "division_result": "",
                            "source": "aims_portal",
                        },
                        source_url=detail_url,
                    ))

        return records
