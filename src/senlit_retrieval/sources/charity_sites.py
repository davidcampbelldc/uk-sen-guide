"""Charity-sector SEN guidance — IPSEA + Contact via sitemap.xml.

IPSEA (Independent Provider of Special Education Advice) and Contact
(contact.org.uk) are the two most-cited UK parent-facing charities in the
SEN space. Both publish advisory articles under terms that permit
reproduction with attribution (see ATTRIBUTIONS.md).

IPSEA is SEN-focused throughout, so we use relevance check without URL
filters. Contact covers wider disability territory, so URL filters restrict
to SEN-relevant paths.
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

USER_AGENT = "senlit-retrieval/0.1 (take-home assessment research)"


@dataclass(frozen=True)
class CharityConfig:
    name: str
    sitemap_url: str
    url_filters: tuple[str, ...] = ()     # empty = use relevance check only


CHARITY_CONFIGS: tuple[CharityConfig, ...] = (
    CharityConfig(
        name="IPSEA",
        sitemap_url="https://www.ipsea.org.uk/sitemap.xml",
        url_filters=(),
    ),
    CharityConfig(
        name="Contact",
        sitemap_url="https://contact.org.uk/sitemap.xml",
        url_filters=("/send", "/sen", "/ehcp", "/education", "/school",
                     "/disability", "/statutory-assessment", "/learning-difficulties"),
    ),
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
    "learning difficult",
)


def _is_sen_relevant(body: str) -> bool:
    b = body.lower()
    return any(m in b for m in _SEN_MARKERS)


class CharitySitesAdapter(SourceAdapter):
    source = "charity-site"
    licence = "attribution"

    def __init__(
        self,
        configs: tuple[CharityConfig, ...] = CHARITY_CONFIGS,
        max_docs_per_site: int = 400,
        request_delay_s: float = 0.3,
    ):
        self.configs = configs
        self.max_docs_per_site = max_docs_per_site
        self.request_delay_s = request_delay_s

    def documents(self, cache_dir: Path) -> Iterable[Document]:
        root = cache_dir / "charity-sites"
        root.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            timeout=45,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for config in self.configs:
                site_dir = root / _slug(config.name)
                site_dir.mkdir(exist_ok=True)
                urls = self._discover_urls(client, config)
                log.info("%s — %d candidate URLs", config.name, len(urls))
                n = 0
                for url in urls:
                    if n >= self.max_docs_per_site:
                        break
                    doc = self._fetch_and_parse(client, config, url, site_dir)
                    if doc is not None:
                        yield doc
                        n += 1
                log.info("%s — yielded %d documents", config.name, n)

    def _discover_urls(
        self, client: httpx.Client, config: CharityConfig
    ) -> list[str]:
        try:
            r = client.get(config.sitemap_url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("sitemap unreachable %s: %s", config.name, exc)
            return []
        time.sleep(self.request_delay_s)

        urls: list[str] = []
        try:
            soup = BeautifulSoup(r.text, "xml")
        except Exception as exc:
            log.warning("sitemap parse %s: %s", config.name, exc)
            return []

        # Sitemap index → follow children
        for smap in soup.find_all("sitemap"):
            loc = smap.find("loc")
            if loc and loc.text:
                urls.extend(self._follow_child(client, loc.text.strip()))

        # Direct urlset
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if loc and loc.text:
                urls.append(loc.text.strip())

        seen: set[str] = set()
        filtered: list[str] = []
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            if config.url_filters:
                lower = url.lower()
                if not any(f in lower for f in config.url_filters):
                    continue
            filtered.append(url)
        return filtered

    def _follow_child(self, client: httpx.Client, url: str) -> list[str]:
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError:
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
        config: CharityConfig,
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
        except Exception:
            return None

        h1 = soup.find("h1")
        page_title = soup.find("title")
        title = (
            (h1.get_text(strip=True) if h1 else None)
            or (page_title.get_text(strip=True) if page_title else None)
            or url
        )

        main = (
            soup.find("main")
            or soup.find(id="content")
            or soup.find(id="main-content")
            or soup.find(role="main")
            or soup.find("article")
            or soup.body
        )
        if main is None:
            return None

        for bad in main.find_all(["nav", "script", "style", "noscript", "aside", "footer", "header", "form"]):
            bad.decompose()

        body = main.get_text(separator="\n", strip=True)
        if len(body.strip()) < 250:
            return None
        if not _is_sen_relevant(body):
            return None

        sections = self._extract_sections(main, body)

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
                "doc_type": "charity-guidance",
                "charity": config.name,
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

    @staticmethod
    def _extract_sections(main, body: str) -> list[Section]:
        raw: list[tuple[int, str, int]] = []
        for h in main.find_all(["h2", "h3"]):
            text = h.get_text(strip=True)
            if not text or len(text) > 200:
                continue
            pos = body.find(text)
            if pos < 0:
                continue
            depth = 2 if h.name == "h2" else 3
            raw.append((pos, text, depth))
        raw.sort(key=lambda t: t[0])
        out: list[Section] = []
        for i, (pos, text, depth) in enumerate(raw):
            end = raw[i + 1][0] if i + 1 < len(raw) else len(body)
            out.append(Section(
                ref=text[:80],
                heading=text,
                start_char=pos,
                end_char=end,
                depth=depth,
            ))
        return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
