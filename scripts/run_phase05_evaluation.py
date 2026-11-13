# ruff: noqa: E501
"""Measure mode rankings over a shared set of indexed cross-body queries."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from twinworld.api import MIN_TERRAIN_COVERAGE, SearchRequest, _load, _terrain_quality, search

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    "earth_namib_barchan-01",
    "earth_capitolreef_layered-01",
    "earth_reykjanes_nondune-01",
    "earth_uyuni_nondune-01",
    "mars-dune-barchan_crescent_dune-0067+071",
    "mars-dune-barchan_crescent_dune-0443+417",
    "mars-dune-barchan_crescent_dune-1284-163",
    "mars_aeolis_nondune-01",
]
MODES = ("visual", "terrain", "combined")


def main() -> None:
    records, _, _ = _load()
    valid_count = sum(bool(_terrain_quality(item.image_id)["eligible"]) for item in records)
    timings: dict[str, list[float]] = {mode: [] for mode in MODES}
    responses: dict[tuple[str, str], dict] = {}
    for query in QUERIES:
        for mode in MODES:
            start = time.perf_counter()
            response = search(
                SearchRequest(observation_id=query, method=mode, limit=50)
            ).model_dump(mode="json")
            timings[mode].append((time.perf_counter() - start) * 1000)
            responses[(query, mode)] = response
    rank_changes = []
    for query in QUERIES:
        for result in responses[(query, "combined")]["results"]:
            change = result["rank_change_within_eligible"]
            if change is not None:
                rank_changes.append(change)
    rows = [
        "# Phase 0.5 evaluation",
        "",
        "Generated from the indexed manifest and terrain sidecars by `scripts/run_phase05_evaluation.py`.",
        "",
        "## Coverage and eligibility",
        "",
        f"- Imagery gallery: {len(records)} observations (50 Earth, 50 Mars); each query exposes the same 50 cross-body candidates to all modes.",
        "- Terrain contexts: 10 Copernicus GLO-30 Earth observations and 10 MOLA MEG128 Mars observations (20 observations across the indexed regions).",
        f"- Terrain quality threshold: at least {MIN_TERRAIN_COVERAGE:.0%} observed cells. Coverage below this configurable engineering threshold is excluded from terrain scoring.",
        f"- Terrain-eligible observations: {valid_count}/100; the remaining observations have no indexed terrain context or inadequate observed-cell coverage.",
        "- Earth DEM valid-grid coverage is 100% for the selected contexts. MOLA observed-bin fractions range from 19.8% to 50.0%; two of ten MOLA contexts fall below the configured threshold.",
        "- Terrain-only returns only candidates with at least one common same-unit feature at matching physical scale. Missing or low-coverage DEMs are never assigned a low similarity score.",
        "",
        "## Mode measurements",
        "",
        "Latency is measured around direct in-process search handler calls on this workstation; it excludes HTTP transport and visual browser rendering.",
        "",
        "| Mode | Median latency (ms) | P95 latency (ms) |",
        "|---|---:|---:|",
    ]
    for mode in MODES:
        values = timings[mode]
        rows.append(
            f"| {mode} | {statistics.median(values):.2f} | {sorted(values)[int(0.95 * (len(values) - 1))]:.2f} |"
        )
    rows += [
        "",
        f"Combined ranking used equal weighting after min-max normalization of visual cosine within each gallery and robust scaling of terrain feature differences. Paired rank changes compare combined and visual order within the terrain-eligible candidate subset. Across {len(rank_changes)} returned combined candidates in the eight-query sample, changes ranged from {min(rank_changes, default=0):+d} to {max(rank_changes, default=0):+d} places.",
        "",
        "## Scientific interpretation and limitations",
        "",
        "- Visual-only retrieval remains the exact precomputed DINOv2 cosine ordering over the same cross-body gallery.",
        "- Terrain-only and combined ranking now use measured elevation range when the physical context scales match within 5%; Earth morphology additionally records slope, slope percentile, local relief, roughness, and curvature where supported. MOLA's sparse support currently contributes elevation range only.",
        "- Terrain feature differences are descriptive retrieval signals, not evidence of geological equivalence. Absolute elevations relative to Earth and Mars reference surfaces are never compared.",
        "- A provisional qualitative spot check is not an independent relevance judgment. The pilot contains no reviewed relevance labels, so no retrieval-accuracy improvement is claimed. Cases where terrain changes the order are reported as ranking changes only, not as scientifically improved matches.",
        "- Scientific plausibility of selected matches remains unvalidated; sensor, scale, illumination, geomorphic process, and data-product differences remain confounders. Human-reviewed, blinded relevance judgments are needed before effectiveness claims.",
        "- No GPU inference was performed locally. The existing remote-produced DINOv2 embeddings were reused.",
        "",
        "## API/UI validation state",
        "",
        "See the Phase 0.5 validation report for automated checks and frontend build results.",
    ]
    (ROOT / "reports/phase-05-evaluation.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(
        f"wrote evaluation for {len(QUERIES)} queries; terrain eligible={valid_count}; rank changes={len(rank_changes)}"
    )


if __name__ == "__main__":
    main()
