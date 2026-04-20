"""DfE SEN statistics — tabular data (CSV + XLSX) from gov.uk statistics publications.

Modern DfE publications (post ~2022) attach tabular data as XLSX, not CSV;
the assessment asks for "CSVs" as an example of tabular data and we treat
XLSX as the real-world equivalent — each sheet becomes one Document with a
text description (title + schema + row count + sample rows).

Older pre-migration pages still serve direct CSV attachments on
`assets.publishing.service.gov.uk`; both paths are handled.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from ..hashing import doc_id, hash_text
from ..models import Document, SourceMetadata
from .base import SourceAdapter

log = logging.getLogger(__name__)

USER_AGENT = "senlit-retrieval/0.1 (take-home assessment research)"
BASE = "https://www.gov.uk"

# Gov.uk SEN statistics publication landing pages. The adapter scrapes each
# for .csv and .xlsx attachment URLs at fetch time, so broken/stale entries
# here degrade gracefully (skipped with a warning, not a crash).
SEED_STATS_PAGES: tuple[str, ...] = (
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2025",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2024",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2023",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2022",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2021",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2020",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2019",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2018",
    f"{BASE}/government/statistics/special-educational-needs-in-england-january-2017",
    f"{BASE}/government/statistics/statements-of-sen-and-ehc-plans-england-2018",
    f"{BASE}/government/statistics/statements-of-sen-and-ehc-plans-england-2017",
    f"{BASE}/government/statistics/tribunal-statistics-quarterly-july-to-september-2023",
    f"{BASE}/government/statistics/tribunal-statistics-quarterly-july-to-september-2022",
    f"{BASE}/government/statistics/tribunal-statistics-quarterly-july-to-september-2021",
    f"{BASE}/government/statistics/education-health-and-care-plans-england-2024",
    f"{BASE}/government/statistics/education-health-and-care-plans-england-2023",
)

_TABULAR_EXT: tuple[str, ...] = (".csv", ".xlsx", ".xls")


class DfeStatsTabularAdapter(SourceAdapter):
    source = "gov.uk/dfe-stats"
    licence = "OGL-3.0"

    def __init__(
        self,
        seeds: tuple[str, ...] = SEED_STATS_PAGES,
        request_delay_s: float = 0.25,
        max_files_per_page: int = 6,
    ):
        self.seeds = seeds
        self.request_delay_s = request_delay_s
        self.max_files_per_page = max_files_per_page

    def documents(self, cache_dir: Path) -> Iterable[Document]:
        file_cache = cache_dir / "dfe-stats"
        file_cache.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            timeout=60,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            total = 0
            for page_url in self.seeds:
                urls = self._discover_tabular(client, page_url)
                log.debug("%s → %d tabular files", page_url, len(urls))
                for file_url in urls[: self.max_files_per_page]:
                    docs = self._fetch_and_describe(client, page_url, file_url, file_cache)
                    for d in docs:
                        yield d
                        total += 1
            log.info("yielded %d tabular documents", total)

    def _discover_tabular(self, client: httpx.Client, page_url: str) -> list[str]:
        try:
            r = client.get(page_url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("landing page fetch failed %s: %s", page_url, exc)
            return []
        time.sleep(self.request_delay_s)

        soup = BeautifulSoup(r.text, "lxml")
        out: list[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            lower = href.lower()
            if not any(lower.endswith(ext) or f"{ext}?" in lower for ext in _TABULAR_EXT):
                continue
            if href.startswith("/"):
                href = f"{BASE}{href}"
            if not href.startswith("http"):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
        return out

    def _fetch_and_describe(
        self,
        client: httpx.Client,
        page_url: str,
        file_url: str,
        cache: Path,
    ) -> list[Document]:
        ext = "xlsx" if file_url.lower().endswith(".xlsx") else (
            "xls" if file_url.lower().endswith(".xls") else "csv"
        )
        cache_name = re.sub(r"[^a-zA-Z0-9]+", "_", file_url.split("://", 1)[-1])[:200]
        cache_path = cache / f"{cache_name}.{ext}"

        if cache_path.exists():
            raw = cache_path.read_bytes()
        else:
            try:
                r = client.get(file_url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("tabular fetch failed %s: %s", file_url, exc)
                return []
            raw = r.content
            cache_path.write_bytes(raw)
            time.sleep(self.request_delay_s)

        try:
            if ext in ("xlsx", "xls"):
                descriptions = self._describe_xlsx(raw, file_url, page_url)
            else:
                desc = self._describe_csv(raw, file_url, page_url)
                descriptions = [(file_url.split("/")[-1].rsplit(".", 1)[0], desc)] if desc else []
        except Exception as exc:
            log.warning("parse failed for %s: %s", file_url, exc)
            return []

        out: list[Document] = []
        for sheet_name, body in descriptions:
            if not body or len(body) < 100:
                continue
            basename = file_url.split("/")[-1].rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
            if sheet_name and sheet_name != basename:
                title = f"DfE SEN statistics — {basename} — {sheet_name}"
            else:
                title = f"DfE SEN statistics — {basename}"
            title = title[:300]

            source_id = f"{file_url.replace('https://', '')}#{sheet_name}"
            meta = SourceMetadata(
                source=self.source,
                source_id=source_id,
                fetched_at=datetime.now(timezone.utc),
                url=file_url,
                licence=self.licence,
                extras={
                    "doc_type": "statistics-tabular",
                    "format": ext,
                    "sheet": sheet_name,
                    "publication_url": page_url,
                },
            )
            did = doc_id(self.source, source_id)
            out.append(Document(
                doc_id=did,
                title=title,
                body=body,
                sections=[],
                metadata=meta,
                content_hash=hash_text(body, salt=did),
            ))
        return out

    @staticmethod
    def _describe_csv(raw: bytes, file_url: str, page_url: str) -> str | None:
        try:
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            return None
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            return None
        if not header or all(not col.strip() for col in header):
            return None
        rows_sample: list[list[str]] = []
        row_count = 0
        for row in reader:
            row_count += 1
            if len(rows_sample) < 5:
                rows_sample.append(row)
        return _format_description(
            kind="CSV",
            basename=file_url.split("/")[-1],
            source_url=file_url,
            publication_url=page_url,
            header=header,
            rows_sample=rows_sample,
            row_count=row_count,
        )

    @staticmethod
    def _describe_xlsx(raw: bytes, file_url: str, page_url: str) -> list[tuple[str, str]]:
        """Return (sheet_name, description) per sheet."""
        wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        out: list[tuple[str, str]] = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Find first row with non-empty cells to use as header
            header: list[str] | None = None
            rows_sample: list[list[str]] = []
            row_count = 0
            for row in ws.iter_rows(values_only=True, max_row=500):
                values = [("" if v is None else str(v)).strip() for v in row]
                if header is None:
                    if any(values):
                        header = values
                    continue
                row_count += 1
                if len(rows_sample) < 5 and any(values):
                    rows_sample.append(values)
            if not header:
                continue
            body = _format_description(
                kind=f"XLSX sheet '{sheet_name}'",
                basename=file_url.split("/")[-1],
                source_url=file_url,
                publication_url=page_url,
                header=header,
                rows_sample=rows_sample,
                row_count=row_count,
            )
            out.append((sheet_name, body))
        return out


def _format_description(
    *,
    kind: str,
    basename: str,
    source_url: str,
    publication_url: str,
    header: list[str],
    rows_sample: list[list[str]],
    row_count: int,
) -> str:
    parts: list[str] = [
        f"DfE SEN statistics {kind}: {basename}",
        f"Source URL: {source_url}",
        f"Publication page: {publication_url}",
        f"Licence: Open Government Licence v3.0",
        f"Total data rows: {row_count:,}",
        f"Columns ({len(header)}):",
    ]
    for i, col in enumerate(header, 1):
        if col.strip():
            parts.append(f"  {i}. {col}")
    parts.append("")
    parts.append("Sample rows (first 5):")
    for row in rows_sample:
        cells = row[: len(header)]
        clean = " | ".join(cell for cell in cells if cell)
        if clean:
            parts.append(f"  {clean}")
    return "\n".join(parts)
