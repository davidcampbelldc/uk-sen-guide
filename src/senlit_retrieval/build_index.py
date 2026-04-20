"""CLI: build the BM25 + dense indices from the chunks JSONL produced by ingest."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console

from .retrieval.bm25_index import Bm25Index
from .retrieval.dense_index import DenseIndex

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()
log = logging.getLogger("senlit.index")


def _load_chunks(chunks_jsonl: Path) -> list[dict]:
    out = []
    with chunks_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@app.command()
def run(
    chunks_path: Path = typer.Option(None, help="Path to chunks JSONL (auto-discovered if absent)"),
    data_root: Path = typer.Option(Path("data"), help="Data root"),
    qdrant_host: str = typer.Option("localhost"),
    qdrant_port: int = typer.Option(6333),
    collection: str = typer.Option("senlit_chunks"),
    bm25_only: bool = typer.Option(False, "--bm25-only", help="Skip dense index (useful for dev)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Build BM25 + dense indices from chunks."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if chunks_path is None:
        jsonls = sorted((data_root / "chunks").glob("chunks-*.jsonl"))
        if not jsonls:
            console.print(
                f"[red]No chunks found under {data_root}/chunks. "
                f"Run `python -m senlit_retrieval.ingest` first.[/]"
            )
            raise typer.Exit(code=1)
        chunks_path = jsonls[-1]

    chunks = _load_chunks(chunks_path)
    console.print(f"[cyan]Loaded {len(chunks):,} chunks from {chunks_path}[/]")

    # BM25
    index_dir = data_root / "index"
    bm25_dir = index_dir / "bm25"
    console.print(f"[cyan]Building BM25 index → {bm25_dir}[/]")
    bm25 = Bm25Index()
    bm25.build(chunks)
    bm25.save(bm25_dir)
    console.print(f"[green]✓ BM25 indexed {bm25.size:,} chunks[/]")

    # Dense
    if bm25_only:
        console.print("[yellow]Skipping dense index (--bm25-only).[/]")
        return

    console.print(f"[cyan]Building dense index in Qdrant collection '{collection}'[/]")
    dense = DenseIndex(
        collection=collection,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
    )
    n = dense.upsert(chunks)
    console.print(f"[green]✓ Dense indexed {n:,} chunks in Qdrant[/]")


if __name__ == "__main__":
    app()
