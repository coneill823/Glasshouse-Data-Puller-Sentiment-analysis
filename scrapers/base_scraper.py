import re
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import (REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF_BASE, RATE_LIMIT_DELAY,
                    CIRCUIT_DEGRADE_AT, CIRCUIT_OPEN_THRESHOLD, CIRCUIT_FAST_TIMEOUT,
                    CIRCUIT_COOLDOWN)

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    def __init__(self, parliament_name: str):
        self.parliament_name = parliament_name
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "GlasshouseDataPuller/1.0 (Parliamentary Sentiment Analysis Research)",
        })
        self._last_request_time = 0.0
        # Circuit breaker state, per hostname.
        self._consecutive_host_failures: Dict[str, int] = {}
        self._circuit_open_until: Dict[str, float] = {}
        # Set True whenever a request is fast-failed/skipped because a host's
        # circuit is open. fetch_all resets this before each data type and reads
        # it after, so a data type cut short by an outage is recorded incomplete.
        self._degraded = False
        # Members fetched once at the start of a run, reused by register/questions.
        self._members_for_run: List[Dict] = []
        # Lazily-launched headless browser for JS-rendered (single-page-app) pages.
        # Most sites are plain HTML and never touch this — see _browser_get().
        self._browser = None
        self._playwright = None
        self._browser_unavailable = False

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: Optional[Dict] = None, accept: Optional[str] = None,
             timeout: Optional[int] = None) -> Optional[requests.Response]:
        host = urlparse(url).netloc or url

        # Circuit breaker: if this host has been failing hard, fast-fail without
        # hammering it. Once the cooldown elapses we let a single probe through
        # (half-open) to test recovery.
        open_until = self._circuit_open_until.get(host, 0.0)
        if open_until:
            if time.time() < open_until:
                self._degraded = True
                logger.debug(f"[{self.parliament_name}] circuit open for {host} "
                             f"({open_until - time.time():.0f}s left) — skipping {url}")
                return None
            # Cooldown elapsed: clear the flag and probe once below.
            logger.info(f"[{self.parliament_name}] {host}: cooldown elapsed — probing recovery")
            self._circuit_open_until.pop(host, None)

        self._rate_limit()
        headers = {}
        if accept:
            headers["Accept"] = accept
        effective_timeout = timeout if timeout is not None else REQUEST_TIMEOUT

        # Once a host is clearly struggling, stop spending the full retry budget /
        # 30s timeout on each item — fail fast so the circuit opens promptly
        # instead of the run crawling at ~96s per dead request.
        degrading = self._consecutive_host_failures.get(host, 0) >= CIRCUIT_DEGRADE_AT
        attempts = 1 if degrading else MAX_RETRIES
        if degrading:
            effective_timeout = min(effective_timeout, CIRCUIT_FAST_TIMEOUT)

        def _note_failure():
            n = self._consecutive_host_failures.get(host, 0) + 1
            self._consecutive_host_failures[host] = n
            if n >= CIRCUIT_OPEN_THRESHOLD:
                self._circuit_open_until[host] = time.time() + CIRCUIT_COOLDOWN
                self._degraded = True
                logger.warning(
                    f"[{self.parliament_name}] {host}: {n} consecutive failures — opening "
                    f"circuit for {CIRCUIT_COOLDOWN}s. Further requests fast-fail; this data "
                    f"type will be recorded incomplete and retried on a later run."
                )

        for attempt in range(attempts):
            try:
                resp = self.session.get(url, params=params, timeout=effective_timeout, headers=headers)
                resp.raise_for_status()
                self._consecutive_host_failures[host] = 0
                self._circuit_open_until.pop(host, None)  # recovered → close circuit
                return resp
            except requests.exceptions.HTTPError:
                code = resp.status_code
                if code == 429 or code >= 500:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(f"HTTP {code} from {url}. Waiting {wait}s.")
                    time.sleep(wait)
                else:
                    # 4xx (not 429): client error, not a host outage — don't count it.
                    logger.error(f"HTTP {code} from {url} — skipping.")
                    return None
            except requests.exceptions.RequestException as e:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Request error (attempt {attempt + 1}/{attempts}): {e}. Retry in {wait}s.")
                time.sleep(wait)
            except Exception as e:
                # Malformed URLs (e.g. urllib3 LocationParseError from a bad scraped
                # href) raise outside the requests exception hierarchy. Retrying
                # won't help and one bad link must never kill a whole pull — and it
                # isn't a host outage, so it doesn't count toward the circuit.
                logger.error(f"Unfetchable URL {url}: {type(e).__name__}: {e} — skipping.")
                return None
        logger.error(f"All {attempts} attempts failed for {url}")
        _note_failure()
        return None

    def _paginate(self, url: str, params: Dict, page_size: int = 100,
                  skip_key: str = "skip", take_key: str = "take",
                  results_key: str = None) -> List[Dict]:
        """Generic paginator for APIs that use skip/take pagination."""
        all_results = []
        skip = 0
        while True:
            page_params = {**params, skip_key: skip, take_key: page_size}
            resp = self._get(url, params=page_params)
            if not resp:
                break
            data = resp.json()
            if results_key:
                items = data.get(results_key, [])
            elif isinstance(data, list):
                items = data
            else:
                # Try common key names
                for key in ("items", "results", "value", "data"):
                    if key in data:
                        items = data[key]
                        break
                else:
                    items = []
            if not items:
                break
            all_results.extend(items)
            if len(items) < page_size:
                break
            skip += page_size
        return all_results

    def _get_browser(self):
        """Lazily launch (and cache) a headless Chromium instance via Playwright.

        Returns None — without raising — if Playwright isn't installed or the
        browser can't be launched, so callers can simply fall back to whatever
        the plain-HTTP path already produced.
        """
        if self._browser is not None:
            return self._browser
        if self._browser_unavailable:
            return None
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            logger.warning(
                f"[{self.parliament_name}] Playwright unavailable ({type(e).__name__}: {e}) — "
                "JS-rendered pages will be skipped. Install with: pip install playwright && playwright install chromium"
            )
            self._browser_unavailable = True
            return None
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info(f"[{self.parliament_name}] Headless browser launched for JS-rendered pages")
            return self._browser
        except Exception as e:
            logger.warning(
                f"[{self.parliament_name}] Could not launch headless browser ({type(e).__name__}: {e}) — "
                "JS-rendered pages will be skipped. Run: playwright install chromium"
            )
            self._browser_unavailable = True
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            return None

    def _browser_get(self, url: str, wait_selector: Optional[str] = None,
                     wait_ms: int = 2500, timeout: Optional[int] = None) -> Optional[BeautifulSoup]:
        """Render `url` in a headless browser and return the resulting HTML as soup.

        Several public parliament pages are single-page apps that return near-empty
        HTML to plain HTTP clients — the real content is injected by JS after load.
        This renders the page fully and waits either for `wait_selector` to appear
        or for `wait_ms` of idle time, then returns the live DOM as BeautifulSoup.

        Returns None if Playwright is unavailable or the page fails to render —
        callers should treat that the same as any other failed fetch.
        """
        browser = self._get_browser()
        if browser is None:
            return None

        self._rate_limit()
        effective_timeout = (timeout if timeout is not None else REQUEST_TIMEOUT) * 1000
        page = None
        try:
            page = browser.new_page(user_agent=self.session.headers.get(
                "User-Agent", "GlasshouseDataPuller/1.0 (Parliamentary Sentiment Analysis Research)"))
            page.goto(url, timeout=effective_timeout, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=max(wait_ms * 2, 5000))
                except Exception:
                    pass
            else:
                page.wait_for_timeout(wait_ms)
            html = page.content()
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"[{self.parliament_name}] Browser render failed for {url}: {type(e).__name__}: {e}")
            return None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def _close_browser(self):
        """Tear down the headless browser, if one was launched."""
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # Layered date patterns for pulling a registration/received date out of
    # free-text register-of-interests entries (e.g. PDF-extracted text like
    # "(Registered 12 May 2024)", "02/06/2024", "12.05.2024").
    _DATE_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
    _DATE_DMY_SLASH_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
    _DATE_DMONTHY_RE = re.compile(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|"
        r"August|September|October|November|December)\s+(\d{4})\b", re.I)

    def _extract_date_from_text(self, text: str) -> str:
        """Pull the first recognisable date out of free text, normalised to YYYY-MM-DD.

        Tries ISO (YYYY-MM-DD), then DD/MM/YYYY or DD.MM.YYYY, then "DD Month YYYY".
        Returns "" if nothing matches.
        """
        m = self._DATE_ISO_RE.search(text)
        if m:
            return m.group(0)
        m = self._DATE_DMY_SLASH_RE.search(text)
        if m:
            try:
                return datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        m = self._DATE_DMONTHY_RE.search(text)
        if m:
            try:
                return datetime.strptime(m.group(0), "%d %B %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        return ""

    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip HTML tags from API-supplied text, preserving the readable content.

        Hansard's ContributionTextFull (and some statement bodies) embed markup —
        empty <span class="column-number"> markers, <em>/<i> emphasis, etc. — that
        is pure noise for sentiment analysis. Returns the text unchanged if it has
        no angle brackets (the common case) or if parsing fails.
        """
        if not text or "<" not in text:
            return text
        try:
            return BeautifulSoup(text, "lxml").get_text()
        except Exception:
            return text

    def _make_record(self, data_type: str, member: Dict, date: str,
                     text: str, title: str = "", metadata: Optional[Dict] = None,
                     source_url: str = "") -> Dict:
        """Build a normalised record ready for sentiment analysis."""
        return {
            "parliament": self.parliament_name,
            "data_type": data_type,
            "member": member,
            "date": date,
            "text": text.strip() if text else "",
            "title": title.strip() if title else "",
            "metadata": metadata or {},
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
        }

    @abstractmethod
    def fetch_members(self) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_register_of_interests(self, members: List[Dict]) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_questions(self, from_date: Optional[str] = None,
                        to_date: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_plenary_business(self, from_date: Optional[str] = None,
                               to_date: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_votes_on_division(self, from_date: Optional[str] = None,
                                to_date: Optional[str] = None) -> List[Dict]:
        pass

    @staticmethod
    def _filter_to_date(records: List[Dict], to_date: Optional[str]) -> List[Dict]:
        """Drop records dated after to_date. Undated records are kept — we can't
        tell when they're from, and dropping them would silently lose data."""
        if not to_date:
            return records
        kept = [r for r in records
                if not str(r.get("date", ""))[:10] or str(r.get("date", ""))[:10] <= to_date]
        dropped = len(records) - len(kept)
        if dropped:
            logger.info(f"Filtered out {dropped} records dated after {to_date}")
        return kept

    def fetch_all(self, from_date: Optional[str] = None,
                  to_date: Optional[str] = None,
                  on_data_type: Optional["Callable[[str, List[Dict], bool], None]"] = None,
                  should_skip: Optional["Callable[[str], bool]"] = None
                  ) -> Dict[str, List[Dict]]:
        """Pull every data type for this parliament.

        If ``on_data_type`` is given it is called as ``(data_type, records,
        complete)`` immediately after each type is fetched, so callers can persist
        results incrementally — a later type stalling or crashing never loses the
        earlier ones. ``complete`` is False when a host's circuit opened mid-fetch
        (data was skipped), so the caller can mark that type for retry.

        If ``should_skip(data_type)`` returns True, that type is not fetched (used
        to skip types already pulled today). ``members`` is always fetched because
        ``register_of_interests`` depends on it.
        """
        range_str = f"{from_date or 'all history'} → {to_date or 'today'}"
        logger.info(f"[{self.parliament_name}] Starting full data pull ({range_str})")

        def _safe(label, fn) -> List[Dict]:
            # One data type crashing must not lose the others' results.
            try:
                return fn()
            except Exception as e:
                logger.error(f"[{self.parliament_name}] {label} fetch failed: "
                             f"{type(e).__name__}: {e}", exc_info=True)
                return []

        results: Dict[str, List[Dict]] = {}

        def _emit(dtype, records):
            if on_data_type:
                on_data_type(dtype, records, not self._degraded)
            results[dtype] = records

        # Scrapers bound the fetch server-side where the source supports it; the
        # post-filter guarantees the to_date bound holds everywhere else.
        specs = [
            ("register_of_interests", lambda: self.fetch_register_of_interests(self._members_for_run), False),
            ("questions", lambda: self.fetch_questions(from_date, to_date), True),
            ("plenary_business", lambda: self.fetch_plenary_business(from_date, to_date), True),
            ("votes_on_division", lambda: self.fetch_votes_on_division(from_date, to_date), True),
        ]

        try:
            # members is always fetched (cheap, and register/questions depend on it)
            self._degraded = False
            self._members_for_run = _safe("members", self.fetch_members)
            logger.info(f"[{self.parliament_name}] {len(self._members_for_run)} members found")
            _emit("members", self._members_for_run)

            for dtype, fn, needs_filter in specs:
                if should_skip and should_skip(dtype):
                    logger.info(f"[{self.parliament_name}] {dtype}: skipped (already pulled today)")
                    continue
                self._degraded = False           # reset per type for the circuit signal
                recs = _safe(dtype, fn)
                if needs_filter:
                    recs = self._filter_to_date(recs, to_date)
                _emit(dtype, recs)

            totals = {k: len(v) for k, v in results.items()}
            logger.info(f"[{self.parliament_name}] Pull complete: {totals}")
            return results
        finally:
            self._close_browser()
