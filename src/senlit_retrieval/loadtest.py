"""Simple async concurrent load test against a running /search endpoint.

Usage:
    python -m senlit_retrieval.loadtest \
        --url http://localhost:8000/search \
        --queries-file eval/queries.yaml \
        --concurrency 20 \
        --duration 30

Reports throughput, latency p50/p95/p99, error rate. Intended as a
quick real-world check that the service holds up under concurrent load,
not a replacement for proper benchmarking (Locust, k6, Vegeta).
"""

from __future__ import annotations

import asyncio
import logging
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()
log = logging.getLogger("senlit.loadtest")


@dataclass
class Outcome:
    latency_ms: float
    status: int
    error: str | None = None


@dataclass
class Summary:
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def ok(self) -> int:
        return sum(1 for o in self.outcomes if o.status == 200)

    @property
    def errors(self) -> int:
        return self.total - self.ok

    def latencies_ok(self) -> list[float]:
        return sorted([o.latency_ms for o in self.outcomes if o.status == 200])

    def percentile(self, p: float) -> float:
        lats = self.latencies_ok()
        if not lats:
            return 0.0
        idx = min(len(lats) - 1, int(len(lats) * p))
        return lats[idx]


async def _one_request(
    client: httpx.AsyncClient,
    url: str,
    query: str,
    config: str,
    top_k: int,
) -> Outcome:
    body = {"query": query, "config": config, "top_k": top_k}
    t0 = time.perf_counter()
    try:
        r = await client.post(url, json=body)
        latency_ms = (time.perf_counter() - t0) * 1000
        return Outcome(latency_ms=latency_ms, status=r.status_code)
    except httpx.HTTPError as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return Outcome(latency_ms=latency_ms, status=0, error=str(exc))


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    queries: list[str],
    config: str,
    top_k: int,
    stop_at: float,
    summary: Summary,
) -> None:
    while time.monotonic() < stop_at:
        q = random.choice(queries)
        summary.outcomes.append(await _one_request(client, url, q, config, top_k))


async def _run(
    url: str,
    queries: list[str],
    config: str,
    concurrency: int,
    duration_s: float,
    top_k: int,
) -> Summary:
    summary = Summary()
    stop_at = time.monotonic() + duration_s
    limits = httpx.Limits(max_keepalive_connections=concurrency + 5, max_connections=concurrency + 10)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        workers = [
            asyncio.create_task(_worker(client, url, queries, config, top_k, stop_at, summary))
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)
    return summary


@app.command()
def run(
    url: str = typer.Option("http://localhost:8000/search", help="/search endpoint"),
    queries_file: Path = typer.Option(Path("eval/queries.yaml"), help="YAML queries file"),
    concurrency: int = typer.Option(10, "--concurrency", "-c", min=1, max=200),
    duration: float = typer.Option(20.0, help="Test duration in seconds"),
    config: str = typer.Option("hybrid_rerank", help="Retrieval config to test"),
    top_k: int = typer.Option(5),
    warmup: float = typer.Option(3.0, help="Seconds of single-thread warmup before measurement"),
) -> None:
    """Run a concurrent load test. Reports p50 / p95 / p99 / throughput / error rate."""
    raw = yaml.safe_load(queries_file.read_text())
    queries = [q["query"] for q in raw.get("queries", []) if q.get("type") != "out-of-scope"]
    if not queries:
        console.print("[red]No queries loaded.[/]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Warmup ({warmup}s @ concurrency=1)...[/]")
    warmup_summary = asyncio.run(_run(url, queries, config, 1, warmup, top_k))
    console.print(f"  warmup: {warmup_summary.total} requests, {warmup_summary.ok} ok")

    console.print(
        f"[cyan]Load test: concurrency={concurrency} duration={duration}s config={config}[/]"
    )
    started = time.perf_counter()
    summary = asyncio.run(_run(url, queries, config, concurrency, duration, top_k))
    wall = time.perf_counter() - started

    lats = summary.latencies_ok()
    table = Table(title=f"Load test — concurrency={concurrency}, config={config}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total requests", str(summary.total))
    table.add_row("Successful", str(summary.ok))
    table.add_row("Errors", str(summary.errors))
    table.add_row("Wall time (s)", f"{wall:.1f}")
    table.add_row("Throughput (req/s)", f"{summary.ok / wall:.1f}")
    if lats:
        table.add_row("p50 latency (ms)", f"{statistics.median(lats):.0f}")
        table.add_row("p95 latency (ms)", f"{summary.percentile(0.95):.0f}")
        table.add_row("p99 latency (ms)", f"{summary.percentile(0.99):.0f}")
        table.add_row("min latency (ms)", f"{min(lats):.0f}")
        table.add_row("max latency (ms)", f"{max(lats):.0f}")
    table.add_row("Error rate", f"{(summary.errors / max(1, summary.total)) * 100:.2f}%")
    console.print(table)


if __name__ == "__main__":
    app()
