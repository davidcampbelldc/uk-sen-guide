"""Cold-cache vs warm-cache latency profile.

Runs a small sequence of queries from a fresh Python process to measure:
  * cold-cache latency — first query after model / index load
  * warm-cache latency — steady-state p50 / p95 / p99 from queries 3..N

Run with:
    python -m scripts.latency_profile --n-warmup 2 --n-measure 15
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from senlit_retrieval.retrieval.bm25_index import Bm25Index
from senlit_retrieval.retrieval.dense_index import DenseIndex
from senlit_retrieval.retrieval.reranker import CrossEncoderReranker
from senlit_retrieval.retrieval.search import SearchService

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()


@app.command()
def run(
    queries_file: Path = typer.Option(Path("eval/queries.yaml")),
    index_dir: Path = typer.Option(Path("data/index")),
    n_warmup: int = typer.Option(2, help="Queries to run before measurement"),
    n_measure: int = typer.Option(15, help="Queries to measure"),
) -> None:
    raw = yaml.safe_load(queries_file.read_text())
    queries = [q["query"] for q in raw.get("queries", []) if q.get("type") != "out-of-scope"]
    queries = queries[: n_warmup + n_measure]

    console.print("[cyan]Loading indices + models (cold-cache setup)...[/]")
    t_load_start = time.perf_counter()
    bm25 = Bm25Index()
    bm25.load(index_dir / "bm25")
    dense = DenseIndex()
    reranker = CrossEncoderReranker()
    service = SearchService(bm25=bm25, dense=dense, reranker=reranker)
    t_load = time.perf_counter() - t_load_start
    console.print(f"  load time: {t_load * 1000:.0f} ms (process startup)")

    for config in ("semantic", "hybrid", "hybrid_rerank"):
        console.rule(f"[bold cyan]{config}")

        # Cold-cache query — first one after load / model-warmup
        t0 = time.perf_counter()
        service.search(query=queries[0], top_k=5, config=config)
        cold_ms = (time.perf_counter() - t0) * 1000

        # Warm queries
        warm_latencies: list[float] = []
        for q in queries[1 : 1 + n_warmup]:
            t0 = time.perf_counter()
            service.search(query=q, top_k=5, config=config)
            # discard warmup

        for q in queries[1 + n_warmup :]:
            t0 = time.perf_counter()
            service.search(query=q, top_k=5, config=config)
            warm_latencies.append((time.perf_counter() - t0) * 1000)

        warm_latencies.sort()
        p50 = statistics.median(warm_latencies) if warm_latencies else 0.0
        p95 = warm_latencies[int(len(warm_latencies) * 0.95)] if warm_latencies else 0.0
        p99 = warm_latencies[int(len(warm_latencies) * 0.99)] if warm_latencies else 0.0

        table = Table(show_header=False)
        table.add_row("cold (1st query)", f"{cold_ms:.0f} ms")
        table.add_row("warm p50", f"{p50:.0f} ms")
        table.add_row("warm p95", f"{p95:.0f} ms")
        table.add_row("warm p99", f"{p99:.0f} ms")
        table.add_row("cold / warm-p50 ratio", f"{cold_ms / p50:.1f}x" if p50 > 0 else "n/a")
        console.print(table)


if __name__ == "__main__":
    app()
