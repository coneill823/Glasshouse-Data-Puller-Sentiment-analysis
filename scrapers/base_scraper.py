import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Optional

import requests

from config import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF_BASE, RATE_LIMIT_DELAY

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

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: Optional[Dict] = None, accept: Optional[str] = None) -> Optional[requests.Response]:
        self._rate_limit()
        headers = {}
        if accept:
            headers["Accept"] = accept
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, headers=headers)
                resp.raise_for_status()
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
            "pulled_at": datetime.now(datetime.UTC).isoformat(),
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
