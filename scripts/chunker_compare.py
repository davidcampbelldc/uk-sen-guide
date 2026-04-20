"""Structural comparison of chunker strategies on the ingested corpus.

Doesn't re-embed (would be ~70 CPU-min on this hardware). Instead compares
chunker output on the same documents: chunk count, size distribution,
section-ref preservation rate.

Full retrieval-quality comparison of chunkers is deferred to a production
iteration with GPU infra — flagged in docs/ROADMAP.md.
"""

from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

from rich.console import Console
from rich.table import Table

from senlit_retrieval.chunking import FixedSizeChunker, HeadingBoundaryChunker
from senlit_retrieval.models import Document, Section, SourceMetadata

console = Console()


def load_documents() -> list[Document]:
    docs = []
    for path in glob.glob("data/docs/*.json"):
        d = json.loads(Path(path).read_text())
        meta = SourceMetadata(**d["metadata"])
        sections = [Section(**s) for s in d.get("sections", [])]
        docs.append(
            Document(
                doc_id=d["doc_id"],
                title=d["title"],
                body=d["body"],
                sections=sections,
                metadata=meta,
                content_hash=d["content_hash"],
            )
        )
    return docs


def chunker_stats(name: str, chunker, docs: list[Document]) -> dict:
    all_chunks = []
    section_preserved = 0
    for doc in docs:
        chunks = chunker.chunk(doc)
        all_chunks.extend(chunks)
        for c in chunks:
            if c.section_ref is not None:
                section_preserved += 1

    sizes = [len(c.text) for c in all_chunks]
    token_counts = [c.token_count for c in all_chunks]
    return {
        "name": name,
        "total_chunks": len(all_chunks),
        "mean_chars": statistics.mean(sizes),
        "median_chars": statistics.median(sizes),
        "stdev_chars": statistics.stdev(sizes) if len(sizes) > 1 else 0,
        "min_chars": min(sizes),
        "max_chars": max(sizes),
        "mean_tokens": statistics.mean(token_counts),
        "section_ref_preserved": section_preserved,
        "section_preservation_rate": section_preserved / len(all_chunks) if all_chunks else 0,
    }


def main() -> None:
    console.print("[cyan]Loading documents...[/]")
    docs = load_documents()
    console.print(f"  {len(docs)} docs loaded")

    arms = [
        ("fixed (2000c/200ov)", FixedSizeChunker(max_chars=2000, overlap_chars=200)),
        ("fixed (3000c/300ov)", FixedSizeChunker(max_chars=3000, overlap_chars=300)),
        ("heading_boundary (default)", HeadingBoundaryChunker()),
        ("heading_boundary (large 3200c)", HeadingBoundaryChunker(target_chars=3200, hard_max_chars=4000)),
    ]

    console.print("\n[bold]Chunk statistics by strategy[/]\n")
    table = Table()
    table.add_column("Strategy")
    table.add_column("Chunks", justify="right")
    table.add_column("Mean chars", justify="right")
    table.add_column("Median", justify="right")
    table.add_column("Stdev", justify="right")
    table.add_column("Min / Max", justify="right")
    table.add_column("Mean ~tokens", justify="right")
    table.add_column("§ preserved", justify="right")

    for name, chunker in arms:
        s = chunker_stats(name, chunker, docs)
        table.add_row(
            s["name"],
            f"{s['total_chunks']:,}",
            f"{s['mean_chars']:.0f}",
            f"{s['median_chars']:.0f}",
            f"{s['stdev_chars']:.0f}",
            f"{s['min_chars']} / {s['max_chars']}",
            f"{s['mean_tokens']:.0f}",
            f"{s['section_preservation_rate'] * 100:.0f}%",
        )
    console.print(table)

    console.print("\n[bold yellow]Retrieval-quality comparison:[/]")
    console.print(
        "Deferred. Would require re-embedding each chunker's output into a separate\n"
        "Qdrant collection (~70 CPU-min per strategy on this laptop) and re-running\n"
        "the eval. Flagged in docs/ROADMAP.md for a GPU-accelerated production\n"
        "iteration. Structural deltas above inform the initial choice."
    )


if __name__ == "__main__":
    main()
