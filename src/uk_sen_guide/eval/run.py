"""Eval CLI — run queries across 3 configs, compute metrics, write a report.

Usage:
    python -m uk_sen_guide.eval.run \
        --queries eval/queries.yaml \
        --chunks data/chunks/chunks-<hash>.jsonl \
        --index-dir data/index
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..retrieval.bm25_index import Bm25Index
from ..retrieval.dense_index import DenseIndex
from ..retrieval.reranker import CrossEncoderReranker
from ..retrieval.search import SearchConfig, SearchService
from .metrics import AggregateMetrics, evaluate_one
from .queries import Query, load_chunks_jsonl, load_queries

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()
log = logging.getLogger("uk_sen.eval")

CONFIGS: list[SearchConfig] = ["bm25", "semantic", "hybrid", "hybrid_rerank"]


def _build_qrels(query: Query, chunks: list[dict]) -> dict[str, int]:
    """Scan the corpus for chunks matching each of this query's matchers."""
    qrels: dict[str, int] = {}
    for chunk in chunks:
        meta = {
            "source": chunk.get("metadata", {}).get("source")
                      or (chunk.get("metadata", {}).get("source") if isinstance(chunk.get("metadata"), dict) else None),
            **(chunk.get("metadata") or {}),
            "text": chunk.get("text", ""),
        }
        section_ref = chunk.get("section_ref")
        doc_id = chunk.get("doc_id")
        for matcher in query.matchers:
            if matcher.matches(meta, section_ref=section_ref, doc_id=doc_id):
                cid = chunk["chunk_id"]
                # Take max relevance if a chunk matches multiple graded matchers
                qrels[cid] = max(qrels.get(cid, 0), matcher.relevance)
    return qrels


@app.command()
def run(
    queries: Path = typer.Option(Path("eval/queries.yaml"), help="YAML file with graded queries"),
    chunks: Path = typer.Option(None, help="Chunks JSONL (auto-discovered if absent)"),
    data_root: Path = typer.Option(Path("data")),
    index_dir: Path = typer.Option(Path("data/index")),
    out_dir: Path = typer.Option(Path("eval_runs")),
    qdrant_host: str = typer.Option("localhost"),
    qdrant_port: int = typer.Option(6333),
    collection: str = typer.Option("uk_sen_chunks"),
    configs: list[str] = typer.Option(None, help="Subset of configs to run (default: all 3)"),
    top_k: int = typer.Option(5, help="Results per query"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if chunks is None:
        jsonls = sorted((data_root / "chunks").glob("chunks-*.jsonl"))
        if not jsonls:
            console.print(f"[red]No chunks under {data_root}/chunks — run ingest first.[/]")
            raise typer.Exit(code=1)
        chunks = jsonls[-1]

    all_chunks = load_chunks_jsonl(chunks)
    console.print(f"[cyan]Loaded {len(all_chunks):,} chunks from {chunks}[/]")

    all_queries = load_queries(queries)
    console.print(f"[cyan]Loaded {len(all_queries)} queries from {queries}[/]")

    selected = configs or list(CONFIGS)
    # Validate config names
    valid = set(CONFIGS)
    for c in selected:
        if c not in valid:
            console.print(f"[red]Unknown config {c!r}. Valid: {CONFIGS}[/]")
            raise typer.Exit(code=1)

    # Build service
    console.print("[cyan]Loading indices + reranker...[/]")
    bm25 = Bm25Index()
    bm25.load(index_dir / "bm25")
    dense = DenseIndex(collection=collection, qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    reranker = CrossEncoderReranker()
    service = SearchService(bm25=bm25, dense=dense, reranker=reranker)

    # Build qrels per query
    console.print("[cyan]Building qrels from corpus × matchers...[/]")
    all_qrels: dict[str, dict[str, int]] = {}
    for q in all_queries:
        all_qrels[q.id] = _build_qrels(q, all_chunks)
    console.print(
        f"  Avg relevant per query: "
        f"{sum(len(qr) for qr in all_qrels.values()) / max(1, len(all_qrels)):.1f}"
    )

    # Run each config across all queries
    results_by_config: dict[str, AggregateMetrics] = {}
    latencies_by_config: dict[str, list[int]] = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    for config in selected:
        console.rule(f"[bold cyan]{config}")
        agg = AggregateMetrics()
        latencies: list[int] = []
        raw_runs: list[dict] = []
        for q in all_queries:
            resp = service.search(query=q.query, top_k=top_k, config=config)
            ranked = [r.chunk_id for r in resp.results]
            qrels = all_qrels[q.id]
            metrics = evaluate_one(q.id, ranked, qrels)
            agg.per_query.append(metrics)
            latencies.append(resp.latency_ms)
            raw_runs.append({
                "query_id": q.id,
                "type": q.type,
                "query": q.query,
                "config": config,
                "ranked": ranked,
                "num_relevant": sum(1 for g in qrels.values() if g > 0),
                "latency_ms": resp.latency_ms,
                "metrics": {
                    "precision_at_5": metrics.precision_at_5,
                    "recall_at_5": metrics.recall_at_5,
                    "ndcg_at_5": metrics.ndcg_at_5,
                },
            })

        results_by_config[config] = agg
        latencies_by_config[config] = latencies

        # Write raw run for this config
        run_path = out_dir / f"{config}-{int(time.time())}.jsonl"
        with run_path.open("w") as f:
            for row in raw_runs:
                f.write(json.dumps(row) + "\n")
        console.print(f"  [green]wrote[/] {run_path}")

    # Summary table
    console.rule("[bold]Results summary")
    table = Table()
    table.add_column("Config", style="cyan")
    table.add_column("P@5", justify="right")
    table.add_column("R@5", justify="right")
    table.add_column("NDCG@5", justify="right")
    table.add_column("p50 latency (ms)", justify="right")
    table.add_column("p95 latency (ms)", justify="right")
    for config in selected:
        agg = results_by_config[config]
        lats = sorted(latencies_by_config[config])
        p50 = lats[len(lats) // 2] if lats else 0
        p95 = lats[int(len(lats) * 0.95)] if lats else 0
        table.add_row(
            config,
            f"{agg.mean_precision_at_5:.3f}",
            f"{agg.mean_recall_at_5:.3f}",
            f"{agg.mean_ndcg_at_5:.3f}",
            str(p50),
            str(p95),
        )
    console.print(table)

    # Per-type breakdown
    console.rule("[bold]Per-query-type NDCG@5")
    types = sorted({q.type for q in all_queries})
    type_table = Table()
    type_table.add_column("Type", style="cyan")
    for config in selected:
        type_table.add_column(config, justify="right")
    for t in types:
        row: list[str] = [t]
        for config in selected:
            scores = [
                m.ndcg_at_5
                for m, q in zip(results_by_config[config].per_query, all_queries, strict=False)
                if q.type == t
            ]
            row.append(f"{(sum(scores) / len(scores)) if scores else 0:.3f}")
        type_table.add_row(*row)
    console.print(type_table)


if __name__ == "__main__":
    app()
