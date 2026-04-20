"""GOV.UK SEND topic pages — HTML content discovered via the gov.uk search API.

URL discovery uses gov.uk's public search API (`/api/search.json`) across a
curated set of SEND-related queries. Pages are fetched polite (small delay
between requests, cached on disk) and parsed with BeautifulSoup. H2/H3 are
used as section anchors; page-level H1 becomes the title.

Licence: OGL-3.0 (gov.uk content is Crown copyright under the Open Government
Licence v3.0 — attribution required; attributions doc carries this).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ..hashing import doc_id, hash_text
from ..models import Document, Section, SourceMetadata
from .base import SourceAdapter

log = logging.getLogger(__name__)

SEARCH_API = "https://www.gov.uk/api/search.json"
BASE = "https://www.gov.uk"
USER_AGENT = "uk-sen-guide/0.1 (take-home assessment research)"

DEFAULT_QUERIES: tuple[str, ...] = (
    "special educational needs",
    "SEND code of practice",
    "EHCP education health care plan",
    "SEN school support",
    "SEND tribunal appeal",
    "special needs children disability",
    "SEN coordinator SENCO",
    "education needs assessment",
    "statement special educational needs",
    "SEND local authority",
    "SEN mediation",
    "post-16 SEND transition",
    "disabled children education",
    "home education SEN",
    "SEN exclusion school",
)

# Skip URL prefixes that aren't content pages
_SKIP_PREFIXES: tuple[str, ...] = (
    "/guidance/contact-",
    "/find-a-job",
    "/contact-",
    "/search",
    "/help",
    "/log-in",
)

# Any of these substrings in the body is sufficient evidence the page is about SEN/SEND.
# Tuned for precision — occasional off-topic pages slip through gov.uk search for broad
# queries (passport, driving licence etc.); this filter keeps the corpus clean.
_SEN_MARKERS: tuple[str, ...] = (
    "special educational need",
    "ehc plan",
    "ehcp",
    "senco",
    "education, health and care",
    "sen support",
    "sen coordinator",
    "send tribunal",
    "send code of practice",
    "local offer",
    "statement of sen",
)


def _is_sen_relevant(body: str) -> bool:
    body_lower = body.lower()
    return any(marker in body_lower for marker in _SEN_MARKERS)


class GovUkSendAdapter(SourceAdapter):
    source = "gov.uk/send"
    licence = "OGL-3.0"

    def __init__(
        self,
        queries: tuple[str, ...] | None = None,
        max_results_per_query: int = 30,
        request_delay_s: float = 0.25,
        max_docs: int = 200,
    ):
        self.queries = queries or DEFAULT_QUERIES
        self.max_results_per_query = max_results_per_query
        self.request_delay_s = request_delay_s
        self.max_docs = max_docs

    def documents(self, cache_dir: Path) -> Iterable[Document]:
        html_cache = cache_dir / "gov-uk-send"
        html_cache.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            timeout=60,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            urls = self._discover_urls(client)
            log.info("discovered %d unique gov.uk SEND pages", len(urls))

            n = 0
            for url in sorted(urls):
                if n >= self.max_docs:
                    break
                doc = self._fetch_and_parse(client, url, html_cache)
                if doc is not None:
                    yield doc
                    n += 1
            log.info("yielded %d gov.uk SEND documents", n)

    def _discover_urls(self, client: httpx.Client) -> set[str]:
        urls: set[str] = set()
        for query in self.queries:
            log.debug("search: %s", query)
            try:
                r = client.get(
                    SEARCH_API,
                    params={
                        "q": query,
                        "count": self.max_results_per_query,
                        "fields": "link,title,content_store_document_type",
                    },
                )
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("search failed for %r: %s", query, exc)
                continue

            data = r.json()
            for item in data.get("results", []):
                link = item.get("link", "")
                if not link:
                    continue
                # Skip non-content paths
                if any(link.startswith(pref) for pref in _SKIP_PREFIXES):
                    continue
                if link.startswith("/"):
                    urls.add(f"{BASE}{link}")
                elif link.startswith("http"):
                    urls.add(link)
            time.sleep(self.request_delay_s)
        return urls

    def _fetch_and_parse(
        self, client: httpx.Client, url: str, cache: Path
    ) -> Document | None:
        cache_name = re.sub(r"[^a-zA-Z0-9]+", "_", url.split("://", 1)[-1])[:200]
        cache_path = cache / f"{cache_name}.html"

        if cache_path.exists():
            html = cache_path.read_text()
        else:
            try:
                r = client.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("fetch %s failed: %s", url, exc)
                return None
            html = r.text
            cache_path.write_text(html)
            time.sleep(self.request_delay_s)

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            log.warning("parse %s failed: %s", url, exc)
            return None

        h1 = soup.find("h1")
        page_title = soup.find("title")
        title = (
            (h1.get_text(strip=True) if h1 else None)
            or (page_title.get_text(strip=True) if page_title else None)
            or url
        )

        # Scope content extraction to <main> to skip site chrome
        main = soup.find("main") or soup.find(id="content") or soup.body
        if main is None:
            log.debug("no main content for %s", url)
            return None

        body, sections = self._extract(main)
        # Require meaningful content
        if len(body.strip()) < 200:
            log.debug("skipping thin page (%d chars): %s", len(body.strip()), url)
            return None

        # SEN relevance filter — gov.uk search ranks some off-topic pages highly
        # for broad queries (e.g., passport pages turning up for "SEN school").
        if not _is_sen_relevant(body):
            log.debug("skipping off-topic page: %s", url)
            return None

        source_id = url.replace(f"{BASE}/", "")
        meta = SourceMetadata(
            source=self.source,
            source_id=source_id,
            fetched_at=datetime.now(UTC),
            url=url,
            licence=self.licence,
            extras={
                "doc_type": "guidance",
                "domain": "gov.uk",
                "format": "html",
            },
        )
        did = doc_id(self.source, source_id)
        return Document(
            doc_id=did,
            title=title[:300],
            body=body,
            sections=sections,
            metadata=meta,
            content_hash=hash_text(body, salt=did),
        )

    @staticmethod
    def _extract(main) -> tuple[str, list[Section]]:
        """Extract clean body text from a <main> node and derive sections from h2/h3."""
        # Drop known non-content nodes before text extraction
        for bad in main.find_all(["nav", "script", "style", "noscript", "aside"]):
            bad.decompose()

        body = main.get_text(separator="\n", strip=True)

        headings: list[tuple[int, str, int]] = []
        for h in main.find_all(["h2", "h3"]):
            text = h.get_text(strip=True)
            if not text or len(text) > 200:
                continue
            pos = body.find(text)
            if pos < 0:
                continue
            depth = 2 if h.name == "h2" else 3
            headings.append((pos, text, depth))

        headings.sort(key=lambda x: x[0])
        sections: list[Section] = []
        for i, (pos, text, depth) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else len(body)
            sections.append(
                Section(
                    ref=text[:80],
                    heading=text,
                    start_char=pos,
                    end_char=end,
                    depth=depth,
                )
            )
        return body, sections
