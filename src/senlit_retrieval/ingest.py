"""Ingest pipeline — fetches documents from source adapters, chunks them,
and persists documents + chunks to disk.

Idempotent: re-running with an unchanged corpus + chunker config is a no-op
beyond re-checking cached inputs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .chunking import Chunker, FixedSizeChunker, HeadingBoundaryChunker
from .hashing import hash_config
from .models import Chunk, Document
from .sources.base import SourceAdapter
from .sources.send_cop import SendCopAdapter

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()
log = logging.getLogger("senlit.ingest")


CHUNKERS: dict[str, type[Chunker]] = {
    "fixed": FixedSizeChunker,
    "heading_boundary": HeadingBoundaryChunker,
}


def available_adapters() -> list[SourceAdapter]:
    return [SendCopAdapter()]


def write_documents(docs: Iterable[Document], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for doc in docs:
        safe_id = doc.doc_id.replace("/", "_").replace("::", "__")
        path = out_dir / f"{safe_id}.json"
        path.write_text(doc.model_dump_json(indent=2))
        n += 1
    return n


def write_chunks(chunks: list[Chunk], out_dir: Path, config_hash: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"chunks-{config_hash}.jsonl"
    with path.open("w") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")
    return len(chunks)


@app.command()
def run(
    data_root: Path = typer.Option(Path("data"), help="Root for cache / docs / chunks"),
    chunker: str = typer.Option("heading_boundary", help=f"One of: {list(CHUNKERS)}"),
    sources: list[str] | None = typer.Option(None, help="Subset of source names to run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full ingest pipeline end-to-end."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )

    cache_dir = data_root / "cache"
    docs_dir = data_root / "docs"
    chunks_dir = data_root / "chunks"

    adapters_all = available_adapters()
    adapters = (
        adapters_all
        if sources is None
        else [a for a in adapters_all if a.source in set(sources)]
    )
    if not adapters:
        console.print(f"[red]No adapters matched sources={sources}[/]")
        raise typer.Exit(code=1)

    console.rule(f"[bold cyan]Ingest — {len(adapters)} source adapter(s)")
    for a in adapters:
        console.print(f"  • {a.source} ([dim]{a.licence}[/])")

    all_docs: list[Document] = []
    for adapter in adapters:
        console.print(f"\n[bold]Fetching[/] {adapter.source}")
        count = 0
        for doc in adapter.documents(cache_dir):
            all_docs.append(doc)
            count += 1
        console.print(f"  [green]✓[/] {count} document(s)")

    if not all_docs:
        console.print("[yellow]No documents produced — nothing to chunk.[/]")
        return

    chunker_cls = CHUNKERS[chunker]
    chunker_instance = chunker_cls()
    cfg = chunker_instance.config_dict()
    config_hash = hash_config(cfg)
    console.print(
        f"\n[bold]Chunking[/] with [cyan]{chunker_instance.name}[/] "
        f"[dim](config hash {config_hash})[/]"
    )

    all_chunks: list[Chunk] = []
    per_doc_rows: list[tuple[str, int, int, int]] = []
    for doc in all_docs:
        ck = chunker_instance.chunk(doc)
        all_chunks.extend(ck)
        per_doc_rows.append((doc.title[:60], len(doc.body), len(doc.sections), len(ck)))

    table = Table(title="Ingest summary", show_lines=False)
    table.add_column("Document", style="cyan")
    table.add_column("Chars", justify="right")
    table.add_column("Sections", justify="right")
    table.add_column("Chunks", justify="right", style="green")
    for row in per_doc_rows:
        table.add_row(row[0], f"{row[1]:,}", f"{row[2]:,}", f"{row[3]:,}")
    console.print(table)

    n_docs = write_documents(all_docs, docs_dir)
    n_chunks = write_chunks(all_chunks, chunks_dir, config_hash)
    console.print(f"\n[green]wrote[/] {n_docs} document(s) → {docs_dir}")
    console.print(f"[green]wrote[/] {n_chunks} chunk(s) → {chunks_dir}/chunks-{config_hash}.jsonl")


if __name__ == "__main__":
    app()
