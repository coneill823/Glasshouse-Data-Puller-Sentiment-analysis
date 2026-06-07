import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF_BASE, RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)

# After this many consecutive failures from the same host, sleep before retrying.
# Set high enough that it only fires for genuinely persistent outages (not transient blips
# or expected rate-limiting runs like NI Assembly ~report 450).
_CONSECUTIVE_FAIL_THRESHOLD = 20
_CONSECUTIVE_FAIL_SLEEP = 30  # seconds


class BaseScraper(ABC):
    def __init__(self, parliament_name: str):
        self.parliament_name = parliament_name
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "GlasshouseDataPuller/1.0 (Parliamentary Sentiment Analysis Research)",
        })
        self._last_request_time = 0.0
        # Track consecutive failures per hostname to avoid hammering rate-limited servers
        self._consecutive_host_failures: Dict[str, int] = {}
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
        self._rate_limit()
        headers = {}
        if accept:
            headers["Accept"] = accept
        effective_timeout = timeout if timeout is not None else REQUEST_TIMEOUT

        host = urlparse(url).netloc or url
        consec = self._consecutive_host_failures.get(host, 0)
        if consec >= _CONSECUTIVE_FAIL_THRESHOLD:
            logger.warning(
                f"[{self.parliament_name}] {host} has failed {consec}× consecutively — "
                f"sleeping {_CONSECUTIVE_FAIL_SLEEP}s before retrying"
            )
            time.sleep(_CONSECUTIVE_FAIL_SLEEP)
            self._consecutive_host_failures[host] = 0

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=effective_timeout, headers=headers)
                resp.raise_for_status()
                self._consecutive_host_failures[host] = 0
                return resp
            except requests.exceptions.HTTPError:
                code = resp.status_code
                if code == 429 or code >= 500:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(f"HTTP {code} from {url}. Waiting {wait}s.")
                    time.sleep(wait)
                else:
                    logger.error(f"HTTP {code} from {url} — skipping.")
                    return None
            except requests.exceptions.RequestException as e:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Request error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retry in {wait}s.")
                time.sleep(wait)
        logger.error(f"All {MAX_RETRIES} attempts failed for {url}")
        # Use current dict value, not stale `consec` — the sleep above may have reset it to 0
        self._consecutive_host_failures[host] = self._consecutive_host_failures.get(host, 0) + 1
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
    def fetch_questions(self, from_date: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_plenary_business(self, from_date: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    def fetch_votes_on_division(self, from_date: Optional[str] = None) -> List[Dict]:
        pass

    def fetch_all(self, from_date: Optional[str] = None) -> Dict[str, List[Dict]]:
        logger.info(f"[{self.parliament_name}] Starting full data pull")
        try:
            members = self.fetch_members()
            logger.info(f"[{self.parliament_name}] {len(members)} members found")
            results = {
                "members": members,
                "register_of_interests": self.fetch_register_of_interests(members),
                "questions": self.fetch_questions(from_date),
                "plenary_business": self.fetch_plenary_business(from_date),
                "votes_on_division": self.fetch_votes_on_division(from_date),
            }
            totals = {k: len(v) for k, v in results.items()}
            logger.info(f"[{self.parliament_name}] Pull complete: {totals}")
            return results
        finally:
            self._close_browser()
