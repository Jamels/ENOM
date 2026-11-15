"""Exercise real local discovery through HTTP contracts and emit a compact trace.

Requires the explicitly built discovery index and existing source assets. This
does not fetch provider data or certify scientific analogue relevance.
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient

from twinworld import api
from twinworld.analogue import DIMENSIONS
from twinworld.scorecards import MISSION_PRESETS


def run() -> dict[str, Any]:
    client = TestClient(api.app)
    info = client.get("/api/discovery/index")
    info.raise_for_status()
    examples: dict[str, Any] = {}
    for body, preferred in (
        ("moon", "lola_polar_moon_shackleton_rim"),
        ("mars", "mars_aeolis_nondune-01"),
    ):
        coverage = client.get("/api/discovery/coverage", params={"body": body})
        coverage.raise_for_status()
        contexts = coverage.json()["contexts"]
        target = next((row for row in contexts if row["observation_id"] == preferred), None)
        if target is None:
            examples[body] = {"status": "reference_context_unavailable", "context_id": preferred}
            continue
        started = perf_counter()
        center = target["index_center"]
        resolved = client.post("/api/discovery/resolve", json={"body": body, **center})
        resolved.raise_for_status()
        response = client.post(
            "/api/discovery/rank",
            json={
                "index_id": resolved.json()["index_id"],
                "context_id": preferred,
                "weights": MISSION_PRESETS["landing"]["weights"],
                "dimension_weights": dict.fromkeys(DIMENSIONS, 1.0),
                "result_limit": 10,
            },
        )
        response.raise_for_status()
        ranking = response.json()
        first = next(iter(ranking["results"]), None)
        examples[body] = {
            "context_id": preferred,
            "selected_coordinate": center,
            "resolve_status": resolved.json()["status"],
            "status": ranking["status"],
            "response_bytes": len(response.content),
            "resolve_and_rank_ms": round((perf_counter() - started) * 1000, 2),
            "total_results": ranking["total_results"],
            "returned_results": len(ranking["results"]),
            "best_comparison": first,
        }
    negative = client.post(
        "/api/discovery/resolve",
        json={
            "body": "mars",
            "latitude_deg": 0.0,
            "longitude_east_deg": 0.0,
        },
    )
    negative.raise_for_status()
    examples["negative"] = negative.json()
    catalogue = client.post(
        "/api/analogue/discover",
        json={
            "target_site_id": "moon-mare-tranquillitatis-pit",
            "profile_id": "geology_materials",
            "weights": dict.fromkeys(DIMENSIONS, 1.0),
            "limit": 3,
        },
    )
    catalogue.raise_for_status()
    examples["catalogue_multidimension"] = catalogue.json()
    return {
        "index_id": info.json()["index_id"],
        "counts": info.json()["counts"],
        "examples": examples,
        "qualification": (
            "Real local source-backed HTTP traces; browser interaction is verified "
            "separately. Numerical availability is reported per dimension."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, allow_nan=False))
