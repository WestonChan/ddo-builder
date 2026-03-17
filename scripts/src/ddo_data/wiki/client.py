"""HTTP client for DDO Wiki MediaWiki API with rate limiting and disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DDO_WIKI_API = "https://ddowiki.com/api.php"
_DEFAULT_CACHE_DIR = Path(".wiki-cache")
_REQUEST_DELAY = 0.6  # ~1.7 req/s, polite rate limit


class WikiClient:
    """Rate-limited, caching HTTP client for the DDO Wiki API."""

    def __init__(
        self,
        cache_dir: Path = _DEFAULT_CACHE_DIR,
        use_cache: bool = True,
        delay: float = _REQUEST_DELAY,
    ) -> None:
        self.cache_dir = cache_dir
        self.use_cache = use_cache
        self.delay = delay
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "ddo-data/0.1 (DDO Build Planner)"
        self._last_request_time = 0.0

    def get_wikitext(self, page_title: str) -> str | None:
        """Fetch raw wikitext for a page. Returns None if page doesn't exist."""
        if self.use_cache:
            cached = self._read_cache(page_title)
            if cached is not None:
                return cached

        params = {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "format": "json",
        }
        data = self._api_get(params)
        if data is None or "parse" not in data:
            logger.warning("No parse result for %s", page_title)
            return None

        wikitext = data["parse"].get("wikitext", {}).get("*")
        if wikitext is None:
            logger.warning("No wikitext in response for %s", page_title)
            return None

        if self.use_cache:
            self._write_cache(page_title, wikitext)

        return wikitext

    def iter_namespace_pages(
        self, namespace: int, *, limit: int = 0,
    ) -> Iterator[str]:
        """Yield all page titles in a namespace via allpages API."""
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": namespace,
            "aplimit": "500",
            "apfilterredir": "nonredirects",
            "format": "json",
        }
        count = 0
        while True:
            data = self._api_get(params)
            if data is None:
                return

            for page in data.get("query", {}).get("allpages", []):
                yield page["title"]
                count += 1
                if 0 < limit <= count:
                    return

            cont = data.get("continue")
            if cont and "apcontinue" in cont:
                params["apcontinue"] = cont["apcontinue"]
            else:
                return

    def iter_category_members(
        self,
        category: str,
        *,
        namespace: int | None = None,
        limit: int = 0,
    ) -> Iterator[str]:
        """Yield page titles in a category via categorymembers API."""
        params: dict = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": "500",
            "format": "json",
        }
        if namespace is not None:
            params["cmnamespace"] = namespace
        count = 0
        while True:
            data = self._api_get(params)
            if data is None:
                return

            for page in data.get("query", {}).get("categorymembers", []):
                yield page["title"]
                count += 1
                if 0 < limit <= count:
                    return

            cont = data.get("continue")
            if cont and "cmcontinue" in cont:
                params["cmcontinue"] = cont["cmcontinue"]
            else:
                return

    def _api_get(self, params: dict) -> dict | None:
        """Make a rate-limited GET request to the wiki API."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        try:
            resp = self._session.get(DDO_WIKI_API, params=params, timeout=30)
            resp.raise_for_status()
            self._last_request_time = time.monotonic()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("API request failed: %s", exc)
            self._last_request_time = time.monotonic()
            return None

    def _cache_path(self, key: str) -> Path:
        """Return filesystem path for a cache entry."""
        digest = hashlib.md5(key.encode()).hexdigest()  # noqa: S324
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, key: str) -> str | None:
        """Read cached wikitext, or None if not cached."""
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data.get("wikitext")
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, key: str, content: str) -> None:
        """Write wikitext to disk cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(key)
        path.write_text(json.dumps({"title": key, "wikitext": content}))
