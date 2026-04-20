"""Local Authority Local Offer crawler — one adapter, N LAs via config.

The SEND Code of Practice requires each Local Authority (LA) to publish a
"Local Offer" — SEN services available in the area. LAs publish on their own
domains in their own formats (no common schema). We sample a handful of LAs
with accessible `/sitemap.xml` and filter for SEN-relevant URL paths.

This is the production value-add for UK SEN Guide V2: generalising across 152 LAs.
For the assessment we ship a representative sample and document the variance
as a finding (see the arch doc / write-up).

LA robots.txt and sitemap.xml are publicly available. We fetch politely
(small delay between requests) with a clearly-identified User-Agent. LA
guidance content is typically Open Government Licence v3.0; pages that
redirect or 404 are skipped gracefully.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ..hashing import doc_id, hash_text
from ..models import Document, Section, SourceMetadata
from .base import SourceAdapter

log = logging.getLogger(__name__)

USER_AGENT = "uk-sen-guide/0.1 (take-home assessment research)"


@dataclass(frozen=True)
class LaConfig:
    name: str
    region: str
    sitemap_url: str
    url_prefix_filters: tuple[str, ...] = ()      # only URLs matching one of these


# Representative sample: mix of urban / rural / regional. All chosen for
# publicly accessible sitemap.xml. Filter patterns picked to target SEN
# content; LAs whose sitemaps don't surface SEN paths will yield few pages.
_COMMON_FILTERS: tuple[str, ...] = (
    "local-offer", "localoffer", "send", "sen-support", "sen/",
    "ehcp", "special-educational", "disability", "disabled-children",
    "educational-needs",
)

LA_CONFIGS: tuple[LaConfig, ...] = (
    LaConfig("Birmingham",  "West Midlands",  "https://www.birmingham.gov.uk/sitemap.xml", _COMMON_FILTERS),
    LaConfig("Manchester",  "North West",     "https://www.manchester.gov.uk/sitemap.xml", _COMMON_FILTERS),
    LaConfig("Leeds",       "Yorkshire",      "https://www.leeds.gov.uk/sitemap.xml",      _COMMON_FILTERS),
    LaConfig("Hackney",     "Inner London",   "https://www.hackney.gov.uk/sitemap.xml",    _COMMON_FILTERS),
    LaConfig("Newcastle",   "North East",     "https://www.newcastle.gov.uk/sitemap.xml",  _COMMON_FILTERS),
    LaConfig("Croydon",     "Outer London",   "https://www.croydon.gov.uk/sitemap.xml",    _COMMON_FILTERS),
    LaConfig("Sheffield",   "Yorkshire",      "https://www.sheffield.gov.uk/sitemap.xml",  _COMMON_FILTERS),
    LaConfig("Brighton",    "South East",     "https://www.brighton-hove.gov.uk/sitemap.xml", _COMMON_FILTERS),
    LaConfig("Oxfordshire", "South East",     "https://www.oxfordshire.gov.uk/sitemap.xml",   _COMMON_FILTERS),
    LaConfig("Bath-NES",    "South West",     "https://www.bathnes.gov.uk/sitemap.xml",    _COMMON_FILTERS),
    LaConfig("Bradford",    "Yorkshire",      "https://www.bradford.gov.uk/sitemap.xml",   _COMMON_FILTERS),
    LaConfig("Islington",   "Inner London",   "https://www.islington.gov.uk/sitemap.xml",  _COMMON_FILTERS),
    LaConfig("Lewisham",    "Inner London",   "https://www.lewisham.gov.uk/sitemap.xml",   _COMMON_FILTERS),
    LaConfig("Southwark",   "Inner London",   "https://www.southwark.gov.uk/sitemap.xml",  _COMMON_FILTERS),
    LaConfig("Leicester",   "East Midlands",  "https://www.leicester.gov.uk/sitemap.xml",  _COMMON_FILTERS),
    LaConfig("Stockport",   "North West",     "https://www.stockport.gov.uk/sitemap.xml",  _COMMON_FILTERS),
)

_SEN_MARKERS: tuple[str, ...] = (
    "special educational need",
    "ehc plan",
    "ehcp",
    "senco",
    "education, health and care",
    "sen support",
    "local offer",
    "disability",
    "send tribunal",
    "autism",
)


def _is_sen_relevant(body: str) -> bool:
    b = body.lower()
    return any(m in b for m in _SEN_MARKERS)


class LaLocalOfferAdapter(SourceAdapter):
    source = "la/local-offer"
    licence = "OGL-3.0"

    def __init__(
        self,
        configs: tuple[LaConfig, ...] = LA_CONFIGS,
        max_docs_per_la: int = 80,
        request_delay_s: float = 0.3,
    ):
        self.configs = configs
        self.max_docs_per_la = max_docs_per_la
        self.request_delay_s = request_delay_s

    def documents(self, cache_dir: Path) -> Iterable[Document]:
        la_cache = cache_dir / "la-local-offer"
        la_cache.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            timeout=45,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for config in self.configs:
                la_dir = la_cache / _slug(config.name)
                la_dir.mkdir(exist_ok=True)
                urls = self._discover_urls(client, config)
                log.info("%s — %d candidate URLs matched filters", config.name, len(urls))
                n = 0
                for url in urls:
                    if n >= self.max_docs_per_la:
                        break
                    doc = self._fetch_and_parse(client, config, url, la_dir)
                    if doc is not None:
                        yield doc
                        n += 1
                log.info("%s — yielded %d SEN documents", config.name, n)

    def _discover_urls(
        self, client: httpx.Client, config: LaConfig
    ) -> list[str]:
        try:
            r = client.get(config.sitemap_url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("sitemap unreachable for %s: %s", config.name, exc)
            return []
        time.sleep(self.request_delay_s)

        # Parse XML sitemap (or sitemap index — follow child sitemaps one level)
        urls: list[str] = []
        try:
            soup = BeautifulSoup(r.text, "xml")
        except Exception as exc:
            log.warning("sitemap parse failed for %s: %s", config.name, exc)
            return []

        # Handle sitemap index (points to child sitemaps)
        for smap in soup.find_all("sitemap"):
            loc = smap.find("loc")
            if loc and loc.text:
                child_urls = self._follow_child_sitemap(client, loc.text.strip())
                urls.extend(child_urls)

        # Handle urlset (direct list of URLs)
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if loc and loc.text:
                urls.append(loc.text.strip())

        # Filter by path prefixes (SEN-relevant paths)
        filtered: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            lower = url.lower()
            if any(pref in lower for pref in config.url_prefix_filters):
                filtered.append(url)
        return filtered

    def _follow_child_sitemap(self, client: httpx.Client, url: str) -> list[str]:
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("child sitemap %s failed: %s", url, exc)
            return []
        time.sleep(self.request_delay_s)
        out: list[str] = []
        try:
            soup = BeautifulSoup(r.text, "xml")
        except Exception:
            return []
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if loc and loc.text:
                out.append(loc.text.strip())
        return out

    def _fetch_and_parse(
        self,
        client: httpx.Client,
        config: LaConfig,
        url: str,
        cache: Path,
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
                log.debug("fetch %s failed: %s", url, exc)
                return None
            html = r.text
            cache_path.write_text(html)
            time.sleep(self.request_delay_s)

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            log.debug("parse %s failed: %s", url, exc)
            return None

        h1 = soup.find("h1")
        page_title = soup.find("title")
        title = (
            (h1.get_text(strip=True) if h1 else None)
            or (page_title.get_text(strip=True) if page_title else None)
            or url
        )

        main = soup.find("main") or soup.find(id="content") or soup.find(role="main") or soup.body
        if main is None:
            return None

        # Strip chrome before extraction
        for bad in main.find_all(["nav", "script", "style", "noscript", "aside", "footer", "header"]):
            bad.decompose()
        body = main.get_text(separator="\n", strip=True)

        if len(body.strip()) < 250:
            return None
        if not _is_sen_relevant(body):
            return None

        sections: list[Section] = []
        for h in main.find_all(["h2", "h3"]):
            text = h.get_text(strip=True)
            if not text or len(text) > 200:
                continue
            pos = body.find(text)
            if pos < 0:
                continue
            depth = 2 if h.name == "h2" else 3
            sections.append(Section(
                ref=text[:80],
                heading=text,
                start_char=pos,
                end_char=pos,  # end fixed up below
                depth=depth,
            ))
        sections.sort(key=lambda s: s.start_char)
        for i in range(len(sections)):
            sections[i] = Section(
                ref=sections[i].ref,
                heading=sections[i].heading,
                start_char=sections[i].start_char,
                end_char=sections[i + 1].start_char if i + 1 < len(sections) else len(body),
                depth=sections[i].depth,
            )

        # Stable source_id: strip protocol + host from URL
        m = re.match(r"https?://[^/]+(/.*)?$", url)
        path_part = (m.group(1) if m else url) or "/"
        source_id = f"{_slug(config.name)}::{path_part}"

        meta = SourceMetadata(
            source=self.source,
            source_id=source_id,
            fetched_at=datetime.now(UTC),
            url=url,
            licence=self.licence,
            extras={
                "doc_type": "local-offer",
                "local_authority": config.name,
                "region": config.region,
                "domain": url.split("/")[2] if "://" in url else "",
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


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
