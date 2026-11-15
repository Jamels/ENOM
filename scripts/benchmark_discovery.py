"""Benchmark warm local discovery operations against a built SQLite index."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter

from fastapi.testclient import TestClient

from twinworld import api
from twinworld.discovery import rank, read_index
from twinworld.feature_index import resolve
from twinworld.scorecards import MISSION_PRESETS


def summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "median_ms": round(median(ordered), 2),
        "p95_ms": round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 2),
    }


def measure(operation, samples: int) -> list[float]:
    operation()  # warm the process and filesystem caches
    timings = []
    for _ in range(samples):
        start = perf_counter()
        operation()
        timings.append((perf_counter() - start) * 1000)
    return timings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=api.DISCOVERY_INDEX)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--context-id", default="mars_aeolis_nondune-01")
    parser.add_argument("--result-limit", type=int, default=10)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    if not 1 <= args.result_limit <= 500:
        parser.error("result limit must be between 1 and 500")
    index = args.index.resolve()
    release, contexts = read_index(index)
    weights = MISSION_PRESETS["landing"]["weights"]
    api.DISCOVERY_INDEX = index
    client = TestClient(api.app)
    target = next((row for row in contexts if row["observation_id"] == args.context_id), None)
    if target is None or target["index_body"] not in {"moon", "mars"}:
        parser.error("context ID must identify an indexed Moon or Mars context")
    center = target["index_center"]
    payload = {
        "index_id": release,
        "context_id": args.context_id,
        "weights": weights,
        "result_limit": args.result_limit,
    }
    response = client.post("/api/discovery/rank", json=payload)
    response.raise_for_status()
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "index_id": release,
        "index_bytes": index.stat().st_size,
        "earth_contexts": sum(row["index_body"] == "earth" for row in contexts),
        "samples": args.samples,
        "context_id": args.context_id,
        "result_limit": args.result_limit,
        "response_bytes": len(response.content),
        "returned_results": len(response.json()["results"]),
        "total_results": response.json()["total_results"],
        "lookup": summary(
            measure(
                lambda: resolve(
                    index,
                    target["index_body"],
                    center["latitude_deg"],
                    center["longitude_east_deg"],
                ),
                args.samples,
            )
        ),
        "ranking": summary(
            measure(
                lambda: rank(
                    index, release, args.context_id, weights, result_limit=args.result_limit
                ),
                args.samples,
            )
        ),
        "rank_http_testclient": summary(
            measure(
                lambda: client.post("/api/discovery/rank", json=payload).raise_for_status(),
                args.samples,
            )
        ),
        "note": (
            "Warm local TestClient timing excludes browser rendering, "
            "network transport and camera motion."
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
