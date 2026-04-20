"""SEND Code of Practice (0-25 years), January 2015 — statutory guidance, OGL-3.0.

Single canonical PDF. Resolved from the gov.uk landing page on first fetch,
cached thereafter. Section detection uses the document's numbered-section
convention (e.g. "1.1", "11.45") as structural anchors for the heading
boundary chunker.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pypdf import PdfReader

from ..hashing import doc_id, hash_text
from ..models import Document, Section, SourceMetadata
from .base import SourceAdapter

log = logging.getLogger(__name__)

GOV_UK_LANDING = "https://www.gov.uk/government/publications/send-code-of-practice-0-to-25"
USER_AGENT = "uk-sen-guide/0.1 (take-home assessment research)"

# Numbered-section pattern: "1.1", "11.45", "A1.2", ... at start of a line.
# Heading must start with a capital and be reasonably short (< ~120 chars).
_SECTION_RE = re.compile(
    r"^\s*(?P<ref>[A-Z]?\d{1,3}\.\d{1,3})\s+(?P<heading>[A-Z][^\n]{3,120})\s*$",
    re.MULTILINE,
)


class SendCopAdapter(SourceAdapter):
    source = "gov.uk/send-cop"
    licence = "OGL-3.0"

    def __init__(self, override_pdf_url: str | None = None):
        self.override_pdf_url = override_pdf_url

    def documents(self, cache_dir: Path) -> Iterable[Document]:
        cache_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = cache_dir / "send-cop-2015.pdf"

        with httpx.Client(
            timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            if not pdf_path.exists():
                pdf_url = self.override_pdf_url or self._resolve_pdf_url(client)
                log.info("Downloading SEND CoP PDF from %s", pdf_url)
                r = client.get(pdf_url)
                r.raise_for_status()
                pdf_path.write_bytes(r.content)
                log.info("Cached to %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
            else:
                log.info("Using cached SEND CoP at %s", pdf_path)

        body, sections = self._parse_pdf(pdf_path)

        title = "Special educational needs and disability code of practice: 0 to 25 years"
        source_id = "send-cop-2015"
        meta = SourceMetadata(
            source=self.source,
            source_id=source_id,
            fetched_at=datetime.now(UTC),
            url=self.override_pdf_url or GOV_UK_LANDING,
            licence=self.licence,
            extras={
                "doc_type": "statutory-guidance",
                "issuing_body": "Department for Education; Department of Health",
                "publication_year": 2015,
            },
        )
        did = doc_id(self.source, source_id)

        yield Document(
            doc_id=did,
            title=title,
            body=body,
            sections=sections,
            metadata=meta,
            content_hash=hash_text(body, salt=did),
        )

    def _resolve_pdf_url(self, client: httpx.Client) -> str:
        """Scrape the gov.uk landing page for the current PDF URL."""
        r = client.get(GOV_UK_LANDING)
        r.raise_for_status()
        candidates = re.findall(
            r'https://assets\.publishing\.service\.gov\.uk/[^"\s]+\.pdf',
            r.text,
        )
        for url in candidates:
            lower = url.lower()
            if "code" in lower and "practice" in lower:
                return url
        if candidates:
            return candidates[0]
        raise RuntimeError("Could not find SEND CoP PDF link on gov.uk landing page")

    def _parse_pdf(self, path: Path) -> tuple[str, list[Section]]:
        reader = PdfReader(str(path))
        pages_text: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                pages_text.append(page.extract_text() or "")
            except Exception as exc:
                log.warning("page %d extract failed: %s", i, exc)
                pages_text.append("")
        body = "\n".join(pages_text)
        sections = self._detect_sections(body)
        log.info("parsed %d pages, %d chars, %d sections", len(pages_text), len(body), len(sections))
        return body, sections

    def _detect_sections(self, body: str) -> list[Section]:
        matches = list(_SECTION_RE.finditer(body))
        sections: list[Section] = []
        for i, m in enumerate(matches):
            ref = m.group("ref")
            heading = m.group("heading").strip()
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            depth = 1 if ref.count(".") == 1 else 2
            sections.append(
                Section(
                    ref=ref,
                    heading=heading,
                    start_char=start,
                    end_char=end,
                    depth=depth,
                )
            )
        return sections
