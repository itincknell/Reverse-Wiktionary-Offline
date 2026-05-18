#!/usr/bin/env python3
"""
HTTP benchmark for the serving API and UI search routes.

The script is dependency-free so it can run on a local machine, an Azure VM, or
a minimal deployment host. It is the sizing harness for the initial single-VM
deployment and captures route timing, API search timing, throughput, errors,
and optional per-request samples.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_QUERIES = Path(__file__).with_name("benchmark_queries.json")


@dataclass(frozen=True)
class Sample:
    route: str
    ok: bool
    status: int | None
    latency_ms: float
    embedding_ms: float | None = None
    qdrant_ms: float | None = None
    service_total_ms: float | None = None
    result_count: int | None = None
    error: str | None = None


def main() -> None:
    args = parse_args()
    queries = load_queries(args.queries)
    requests = build_requests(
        queries=queries,
        routes=args.routes,
        iterations=args.iterations,
        limit=args.limit,
        langs=args.langs,
        pos=args.pos,
    )

    started = time.perf_counter()
    samples = run_requests(
        base_url=args.base_url.rstrip("/"),
        requests=requests,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
    )
    elapsed_seconds = time.perf_counter() - started

    report = build_report(
        samples=samples,
        concurrency=args.concurrency,
        elapsed_seconds=elapsed_seconds,
        args=args,
        query_count=len(queries),
    )
    print_report(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.samples_output:
        args.samples_output.parent.mkdir(parents=True, exist_ok=True)
        args.samples_output.write_text(
            json.dumps([sample.__dict__ for sample in samples], indent=2) + "\n",
            encoding="utf-8",
        )

    if report["error_count"] and not args.allow_errors:
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--routes", nargs="+", choices=["api", "ui"], default=["api"])
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--langs", nargs="*", default=[])
    parser.add_argument("--pos", nargs="*", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--samples-output",
        type=Path,
        help="Optional path for per-request samples.",
    )
    parser.add_argument(
        "--allow-errors",
        action="store_true",
        help="Return success even when benchmark requests fail.",
    )
    return parser.parse_args()


def load_queries(path: Path) -> list[str]:
    queries = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(queries, list) or not all(isinstance(query, str) for query in queries):
        raise ValueError(f"{path} must contain a JSON list of query strings")

    return [query for query in queries if query.strip()]


def build_requests(
    *,
    queries: list[str],
    routes: list[str],
    iterations: int,
    limit: int,
    langs: list[str],
    pos: list[str],
) -> list[tuple[str, str, int, list[str], list[str]]]:
    requests: list[tuple[str, str, int, list[str], list[str]]] = []

    for _ in range(iterations):
        for route in routes:
            for query in queries:
                requests.append((route, query, limit, langs, pos))

    return requests


def run_requests(
    *,
    base_url: str,
    requests: list[tuple[str, str, int, list[str], list[str]]],
    concurrency: int,
    timeout_seconds: float,
) -> list[Sample]:
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                run_one,
                base_url=base_url,
                route=route,
                query=query,
                limit=limit,
                langs=langs,
                pos=pos,
                timeout_seconds=timeout_seconds,
            )
            for route, query, limit, langs, pos in requests
        ]
        return [future.result() for future in as_completed(futures)]


def run_one(
    *,
    base_url: str,
    route: str,
    query: str,
    limit: int,
    langs: list[str],
    pos: list[str],
    timeout_seconds: float,
) -> Sample:
    started = time.perf_counter()

    try:
        if route == "api":
            return run_api_search(
                base_url=base_url,
                query=query,
                limit=limit,
                langs=langs,
                pos=pos,
                timeout_seconds=timeout_seconds,
                started=started,
            )
        return run_ui_search(
            base_url=base_url,
            query=query,
            limit=limit,
            langs=langs,
            pos=pos,
            timeout_seconds=timeout_seconds,
            started=started,
        )
    except HTTPError as exc:
        return failed_sample(route, started, exc.code, str(exc))
    except (OSError, URLError, TimeoutError) as exc:
        return failed_sample(route, started, None, str(exc))


def run_api_search(
    *,
    base_url: str,
    query: str,
    limit: int,
    langs: list[str],
    pos: list[str],
    timeout_seconds: float,
    started: float,
) -> Sample:
    body = json.dumps(
        {
            "query": query,
            "langs": langs,
            "pos": pos,
            "limit": limit,
            "offset": 0,
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url}/api/v1/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))

    timing = payload.get("timing_ms", {})
    results = payload.get("results", [])

    return Sample(
        route="api",
        ok=True,
        status=200,
        latency_ms=elapsed_ms(started),
        embedding_ms=number_or_none(timing.get("embedding")),
        qdrant_ms=number_or_none(timing.get("qdrant")),
        service_total_ms=number_or_none(timing.get("total")),
        result_count=len(results) if isinstance(results, list) else None,
    )


def run_ui_search(
    *,
    base_url: str,
    query: str,
    limit: int,
    langs: list[str],
    pos: list[str],
    timeout_seconds: float,
    started: float,
) -> Sample:
    body = urlencode(
        {
            "query": query,
            "limit": limit,
            "langs": langs,
            "pos": pos,
        },
        doseq=True,
    ).encode("utf-8")
    request = Request(
        f"{base_url}/ui/search",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        response.read()

    return Sample(
        route="ui",
        ok=True,
        status=200,
        latency_ms=elapsed_ms(started),
    )


def failed_sample(
    route: str,
    started: float,
    status: int | None,
    error: str,
) -> Sample:
    return Sample(
        route=route,
        ok=False,
        status=status,
        latency_ms=elapsed_ms(started),
        error=error,
    )


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def number_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def build_report(
    *,
    samples: list[Sample],
    concurrency: int,
    elapsed_seconds: float,
    args: argparse.Namespace,
    query_count: int,
) -> dict[str, Any]:
    route_reports = {
        route: summarize_samples([sample for sample in samples if sample.route == route])
        for route in sorted({sample.route for sample in samples})
    }

    return {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": args.base_url,
        "routes_requested": args.routes,
        "iterations": args.iterations,
        "limit": args.limit,
        "langs": args.langs,
        "pos": args.pos,
        "query_count": query_count,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "request_count": len(samples),
        "error_count": sum(1 for sample in samples if not sample.ok),
        "throughput_rps": round(len(samples) / elapsed_seconds, 2) if elapsed_seconds else 0,
        "routes": route_reports,
    }


def summarize_samples(samples: list[Sample]) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    successes = [sample for sample in samples if sample.ok]
    failures = [sample for sample in samples if not sample.ok]

    report: dict[str, Any] = {
        "request_count": len(samples),
        "success_count": len(successes),
        "error_count": len(failures),
        "latency_ms": summarize_numbers(latencies),
    }

    service_totals = present([sample.service_total_ms for sample in successes])
    embedding = present([sample.embedding_ms for sample in successes])
    qdrant = present([sample.qdrant_ms for sample in successes])
    result_counts = present([sample.result_count for sample in successes])

    if service_totals:
        report["service_total_ms"] = summarize_numbers(service_totals)
    if embedding:
        report["embedding_ms"] = summarize_numbers(embedding)
    if qdrant:
        report["qdrant_ms"] = summarize_numbers(qdrant)
    if result_counts:
        report["result_count"] = summarize_numbers(result_counts)
    if failures:
        report["sample_errors"] = [sample.error for sample in failures[:5]]

    return report


def present(values: list[float | int | None]) -> list[float]:
    return [float(value) for value in values if value is not None]


def summarize_numbers(values: list[float]) -> dict[str, float]:
    if not values:
        return {}

    sorted_values = sorted(values)
    return {
        "min": round(sorted_values[0], 2),
        "p50": percentile(sorted_values, 50),
        "p95": percentile(sorted_values, 95),
        "p99": percentile(sorted_values, 99),
        "max": round(sorted_values[-1], 2),
        "avg": round(statistics.fmean(sorted_values), 2),
    }


def percentile(sorted_values: list[float], percentile_value: int) -> float:
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)

    index = (len(sorted_values) - 1) * (percentile_value / 100)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    value = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(value, 2)


def print_report(report: dict[str, Any]) -> None:
    print(
        f"requests={report['request_count']} concurrency={report['concurrency']} "
        f"elapsed={report['elapsed_seconds']}s throughput={report['throughput_rps']}rps"
    )

    for route, route_report in report["routes"].items():
        latency = route_report["latency_ms"]
        print(
            f"{route}: ok={route_report['success_count']} errors={route_report['error_count']} "
            f"latency_ms p50={latency['p50']} p95={latency['p95']} "
            f"p99={latency['p99']} avg={latency['avg']}"
        )

        if "embedding_ms" in route_report:
            embedding = route_report["embedding_ms"]
            qdrant = route_report["qdrant_ms"]
            print(
                f"{route}: embedding_ms avg={embedding['avg']} p95={embedding['p95']} "
                f"qdrant_ms avg={qdrant['avg']} p95={qdrant['p95']}"
            )


if __name__ == "__main__":
    main()
