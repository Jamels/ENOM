"""Exact, evidence-aware comparisons over the precomputed terrain index."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from twinworld.scorecards import VARIABLES, compare_candidate, validate_weights

POLICY_PATH = Path(__file__).resolve().parents[2] / "configs/discovery-policy.json"
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
POLICY_VERSION = POLICY["version"]
SCORING_METHOD = "eight-dimension-prototype-v3"
LAND_COVER_GROUPS = {
    "bare_sparse",
    "forest",
    "cropland",
    "built_up",
    "snow_ice",
    "water",
    "grass_shrub_wetland",
}
_SCORING_SOURCE_HASHES = {
    name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
    for name in (
        "discovery.py",
        "dimension_scoring.py",
        "analogue.py",
        "scorecards.py",
        "scientific_observations.py",
    )
}
POLICY_HASH = hashlib.sha256(
    json.dumps(
        {
            "policy": POLICY,
            "variables": VARIABLES,
            "scoring_method": SCORING_METHOD,
            "scoring_sources_sha256": _SCORING_SOURCE_HASHES,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()


def read_index(path: Path) -> tuple[str, list[dict[str, Any]]]:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        release = db.execute("SELECT id FROM release WHERE schema_version=4").fetchone()
        if release is None:
            raise ValueError("unsupported or empty discovery index")
        rows = db.execute("SELECT id, body, metadata FROM contexts ORDER BY id").fetchall()
        measurements: dict[int, list[dict[str, Any]]] = {}
        for context_id, payload in db.execute(
            "SELECT context_id, payload FROM measurements ORDER BY context_id, ordinal"
        ):
            measurements.setdefault(context_id, []).append(json.loads(payload))
    return release[0], [
        dict(json.loads(meta), index_body=body, measurements=measurements.get(context_id, []))
        for context_id, body, meta in rows
    ]


def _support_ok(row: dict[str, Any]) -> bool:
    if row.get("dataset_id") in {"mola-meg128", "lro-lola-gdr-polar-ldem-120m"}:
        fraction = row.get("observed_cell_fraction")
        return (
            isinstance(fraction, (int, float))
            and fraction >= POLICY["minimum_observed_fraction"]
            and not isinstance(fraction, bool)
            and math.isfinite(fraction)
            and 0 <= fraction <= 1
        )
    fraction = row.get("valid_pixel_fraction")
    return (
        isinstance(fraction, (int, float))
        and not isinstance(fraction, bool)
        and math.isfinite(fraction)
        and POLICY["minimum_valid_fraction"] <= fraction <= 1
    )


def comparison_measurements(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return measured values while preserving partial-observation semantics.

    MOLA's elevation range is the range among directly observed bins. At the
    configured minimum support it may rank as limited evidence, but it is not
    represented as a complete-footprint range and cannot qualify for the
    multi-feature tier.
    """
    return row.get("measurements", [])


def _dimension_inputs(
    row: dict[str, Any],
    observations: dict[str, list[dict[str, Any]]],
    prototype_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from twinworld.scientific_observations import dimension_inputs

    observation_id = str(row["observation_id"])
    place_id = str(row.get("place_id") or observation_id)
    result: dict[str, Any] = dimension_inputs(
        Path(__file__).resolve().parents[2],
        place_id,
        observations=observations.get(place_id, []),
    )
    center = row.get("index_center") if isinstance(row.get("index_center"), dict) else {}
    location = {
        "body": row.get("index_body"),
        "latitude_deg": center.get("latitude_deg"),
    }
    catalogue_context = (prototype_contexts or {}).get(place_id, {})
    prototype_context = {
        key: catalogue_context[key]
        for key in ("candidate_type", "summary", "source_url")
        if catalogue_context.get(key) is not None
    }
    if isinstance(row.get("land_cover"), dict):
        prototype_context["land_cover"] = row["land_cover"]
    result = {
        dimension_id: {
            "id": dimension_id,
            "evidence_items": evidence_rows,
            "location": location,
            "prototype_context": prototype_context,
        }
        for dimension_id, evidence_rows in result.items()
    }
    # The indexed terrain is the authoritative footprint-specific observation.
    # Catalogue evidence can add context but cannot replace its support mask.
    result["terrain"] = {
        "id": "terrain",
        "status": "available",
        "scoring_measurements": comparison_measurements(row),
        "observation_ids": [observation_id],
        "sources": [
            {
                "dataset_id": row.get("dataset_id"),
                "product_id": row.get("source_product_id"),
                "url": row.get("source_url") or row.get("source_catalog_url"),
            }
        ],
        "observation_coverage": row.get("observed_cell_fraction", row.get("valid_pixel_fraction")),
        "uncertainty": row.get("uncertainty_note") or row.get("missing_data_semantics"),
    }
    return result


def _compact_dimensions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep explanatory scores in rankings; raw evidence has a detail endpoint."""
    fields = {
        "dimension_id",
        "id",
        "label",
        "weight",
        "score",
        "effective_weight",
        "weight_contribution",
        "normalized_contribution",
        "prototype_score",
        "observed_score",
        "score_origin",
        "evidence_backed",
        "methodology",
        "methodology_kind",
        "evidence_status",
        "score_coverage",
        "comparison_variables",
        "score_note",
        "scored",
        "sources",
        "reference_sources",
        "candidate_sources",
        "observation_coverage",
        "uncertainty",
    }
    summaries = [{key: value for key, value in row.items() if key in fields} for row in rows]
    for summary in summaries:
        for variable in summary.get("comparison_variables", []):
            for measurement_key in ("reference_measurements", "candidate_measurements"):
                variable[measurement_key] = [
                    {
                        key: measurement[key]
                        for key in ("name", "value", "units", "source_url", "dataset_id", "temporal_coverage")
                        if key in measurement
                    }
                    for measurement in variable.get(measurement_key, [])
                    if isinstance(measurement, dict)
                ][:8]
        if summary.get("dimension_id") == "mission_operations":
            variables = summary.get("comparison_variables", [])
            summary["shared_comparison_variables"] = [item["name"] for item in variables]
            summary["comparison_variables"] = []
    return summaries


def _footprint_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    dimensions: list[tuple[float, float]] = []
    for row in (a, b):
        width, height = row.get("index_ground_width_m"), row.get("index_ground_height_m")
        if (
            not isinstance(width, (int, float))
            or not isinstance(height, (int, float))
            or isinstance(width, bool)
            or isinstance(height, bool)
            or not math.isfinite(width)
            or not math.isfinite(height)
            or min(width, height) <= 0
        ):
            return False
        # Context footprints have no privileged north/east orientation. Sort
        # each context's own sides so an equivalent 90-degree rotation matches.
        dimensions.append((min(float(width), float(height)), max(float(width), float(height))))
    area_a = dimensions[0][0] * dimensions[0][1]
    area_b = dimensions[1][0] * dimensions[1][1]
    matched_dimension_ratios = [
        max(dimensions[0][axis], dimensions[1][axis])
        / min(dimensions[0][axis], dimensions[1][axis])
        for axis in (0, 1)
    ]
    return (
        all(ratio <= POLICY["maximum_footprint_ratio"] for ratio in matched_dimension_ratios)
        and max(area_a, area_b) / min(area_a, area_b) <= POLICY["maximum_footprint_ratio"]
    )


def _validate_land_cover_constraints(constraints: dict[str, float]) -> dict[str, float]:
    if not isinstance(constraints, dict):
        raise ValueError("land-cover filters must be a mapping of classes to fractions")
    validated: dict[str, float] = {}
    for name, value in constraints.items():
        if name not in LAND_COVER_GROUPS:
            raise ValueError(f"unknown land-cover group: {name}")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError("land-cover fractions must be finite values from 0 to 1")
        validated[name] = float(value)
    return validated


def _land_cover_status(
    row: dict[str, Any],
    minimums: dict[str, float],
    maximums: dict[str, float],
) -> str:
    if not minimums and not maximums:
        return "pass"
    land_cover = row.get("land_cover")
    if (
        not isinstance(land_cover, dict)
        or land_cover.get("status") != "available"
        or isinstance(land_cover.get("valid_fraction"), bool)
        or land_cover.get("valid_fraction") != 1.0
    ):
        return "missing"
    fractions = land_cover.get("group_fractions")
    if not isinstance(fractions, dict):
        return "missing"
    for name in minimums.keys() | maximums.keys():
        value = fractions.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            return "missing"
        if value < minimums.get(name, 0.0) or value > maximums.get(name, 1.0):
            return "unsuitable"
    return "pass"


def _passes_land_cover(row: dict[str, Any], constraints: dict[str, float]) -> bool:
    """Compatibility helper for maximum-only callers; bounds are inclusive."""
    return _land_cover_status(row, {}, constraints) == "pass"


def _near_equivalent_candidates(
    results: list[dict[str, Any]], tolerance: float
) -> list[dict[str, Any]]:
    score_key = "score" if results and "score" in results[0] else "similarity_score"
    if not results or results[0].get(score_key) is None:
        return []
    best = results[0]
    best_score = float(best[score_key])
    class_key = (
        "dimension_evidence_class" if "dimension_evidence_class" in best else "evidence_class"
    )
    count_key = (
        "contributing_dimension_count"
        if "contributing_dimension_count" in best
        else "matched_variable_count"
    )
    return [
        result
        for result in results
        if result.get(class_key) == best.get(class_key)
        and result.get(count_key) == best.get(count_key)
        and isinstance(result.get(score_key), (int, float))
        and best_score - float(result[score_key]) <= tolerance
    ]


def _summarize_near_equivalents(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "near_equivalent_count": len(candidates),
        "near_equivalent_context_ids": [
            result["context"]["observation_id"] for result in candidates[:100]
        ],
        "near_equivalent_ids_truncated": len(candidates) > 100,
    }


def rank(
    index: Path,
    index_id: str,
    context_id: str,
    weights: dict[str, float],
    land_cover_max_fractions: dict[str, float] | None = None,
    result_limit: int | None = None,
    result_offset: int = 0,
    *,
    dimension_weights: dict[str, float] | None = None,
    land_cover_min_fractions: dict[str, float] | None = None,
) -> dict[str, Any]:
    from twinworld.analogue import (
        DIMENSIONS,
        candidate_context_records,
        validate_dimension_weights,
    )
    from twinworld.dimension_scoring import compare_dimensions

    checked = validate_weights(weights)
    if set(checked) != set(VARIABLES):
        raise ValueError("weights must contain all five terrain variables")
    selected_dimension_weights = validate_dimension_weights(
        ({key: 1.0 if key == "terrain" else 0.0 for key in DIMENSIONS})
        if dimension_weights is None or not dimension_weights
        else dimension_weights
    )
    land_cover_filters = _validate_land_cover_constraints(
        {} if land_cover_max_fractions is None else land_cover_max_fractions
    )
    land_cover_minimums = _validate_land_cover_constraints(
        {} if land_cover_min_fractions is None else land_cover_min_fractions
    )
    for name in land_cover_minimums.keys() & land_cover_filters.keys():
        if land_cover_minimums[name] > land_cover_filters[name]:
            raise ValueError(f"land-cover minimum exceeds maximum for {name}")
    if result_limit is not None and (
        isinstance(result_limit, bool) or not isinstance(result_limit, int) or result_limit < 1
    ):
        raise ValueError("result limit must be a positive integer")
    if isinstance(result_offset, bool) or not isinstance(result_offset, int) or result_offset < 0:
        raise ValueError("result offset must be a nonnegative integer")
    release, rows = read_index(index)
    if index_id != release:
        raise RuntimeError("discovery index changed")
    target = next(
        (r for r in rows if r["observation_id"] == context_id and r["index_body"] != "earth"), None
    )
    if target is None:
        raise KeyError(context_id)
    results = []
    land_cover_filter_excluded = 0
    land_cover_missing_count = 0
    land_cover_unsuitable_count = 0
    from twinworld.scientific_observations import local_observation_catalogue

    observations = local_observation_catalogue(Path(__file__).resolve().parents[2])
    prototype_contexts = {
        record["place_id"]: record
        for record in candidate_context_records(Path(__file__).resolve().parents[2])
    }
    target_dimensions = _dimension_inputs(target, observations, prototype_contexts)
    terrain_dimension_weight = max(
        selected_dimension_weights["terrain"], selected_dimension_weights["mission_operations"]
    )
    if terrain_dimension_weight == 0 or _support_ok(target):
        for earth in (r for r in rows if r["index_body"] == "earth"):
            land_cover_status = _land_cover_status(earth, land_cover_minimums, land_cover_filters)
            if land_cover_status != "pass":
                land_cover_filter_excluded += 1
                land_cover_missing_count += land_cover_status == "missing"
                land_cover_unsuitable_count += land_cover_status == "unsuitable"
                continue
            if (
                terrain_dimension_weight > 0 and not _support_ok(earth)
            ) or not _footprint_compatible(target, earth):
                continue
            comparison = compare_candidate(
                comparison_measurements(target), comparison_measurements(earth), checked
            )
            dimension_comparison = compare_dimensions(
                target_dimensions,
                _dimension_inputs(earth, observations, prototype_contexts),
                selected_dimension_weights,
                terrain_comparison=comparison,
            )
            count = comparison["matched_variable_count"]
            direct = target.get("native_count_crop_fraction")
            retained = target.get("observed_cell_fraction")
            tier = (
                "multi_feature"
                if count >= POLICY["multi_feature_minimum_count"]
                and isinstance(direct, (int, float))
                and direct >= POLICY["multi_feature_minimum_direct_fraction"]
                and isinstance(retained, (int, float))
                and retained >= POLICY["minimum_valid_fraction"]
                else "limited_evidence"
            )
            # Measurements and full footprint geometry remain in the index;
            # comparison variables contain the values needed to explain scores.
            # Repeating both on every result makes large rankings impractical.
            summary_fields = {
                "observation_id",
                "place_id",
                "name",
                "body",
                "dataset_id",
                "provider",
                "source_product_id",
                "source_url",
                "source_catalog_url",
                "source_resolution_m",
                "valid_pixel_fraction",
                "observed_cell_fraction",
                "uncertainty_note",
                "missing_data_semantics",
                "land_cover",
                "index_body",
                "index_center",
                "index_ground_width_m",
                "index_ground_height_m",
            }
            context = {key: value for key, value in earth.items() if key in summary_fields}
            if isinstance(context.get("land_cover"), dict):
                cover_fields = {"status", "valid_fraction", "group_fractions", "source_url"}
                context["land_cover"] = {
                    key: value
                    for key, value in context["land_cover"].items()
                    if key in cover_fields
                }
            results.append(
                {
                    "context": context,
                    "evidence_class": tier,
                    "terrain_support_class": tier,
                    **comparison,
                    "score_interpretation": (
                        "Eight-dimension prototype similarity; not a probability, "
                        "validated geological analogue, or mission suitability."
                    ),
                    "score": dimension_comparison["score"],
                    "prototype_similarity": dimension_comparison["prototype_similarity"],
                    "observed_similarity": dimension_comparison["observed_similarity"],
                    "evidence_coverage": dimension_comparison["evidence_coverage"],
                    "source_context_coverage": dimension_comparison["source_context_coverage"],
                    "measured_weight_coverage": dimension_comparison["measured_weight_coverage"],
                    "estimated_weight_coverage": dimension_comparison["estimated_weight_coverage"],
                    "simulated_weight_coverage": dimension_comparison["simulated_weight_coverage"],
                    "dimension_scores": _compact_dimensions(
                        dimension_comparison["dimension_scores"]
                    ),
                    "missing_dimensions": dimension_comparison["missing_dimensions"],
                    "missing_evidence_dimensions": dimension_comparison[
                        "missing_evidence_dimensions"
                    ],
                    "dimension_evidence_class": dimension_comparison["evidence_class"],
                    "independent_evidence_group_count": len(
                        dimension_comparison["independent_evidence_groups"]
                    ),
                    "contributing_dimension_count": sum(
                        row["scored"] and row["weight"] > 0
                        for row in dimension_comparison["dimension_scores"]
                    ),
                }
            )
    results.sort(
        key=lambda r: (
            r["score"] is None,
            -(r["score"] or 0.0),
            -(r["evidence_coverage"] or 0.0),
            -r["independent_evidence_group_count"],
            r["context"]["observation_id"],
        )
    )
    for i, result in enumerate(results, 1):
        result["rank"] = i
    near_equivalent = _near_equivalent_candidates(results, float(POLICY["ranking_tie_tolerance"]))
    recommendations: list[dict[str, Any]] = []
    suppressed = 0
    for result in results:
        center = result["context"]["index_center"]
        lat = math.radians(center["latitude_deg"])
        lon = math.radians(center["longitude_east_deg"])
        nearby = False
        for chosen in recommendations:
            other = chosen["context"]["index_center"]
            other_lat = math.radians(other["latitude_deg"])
            delta_lon = math.radians(other["longitude_east_deg"]) - lon
            h = math.sin((other_lat - lat) / 2) ** 2 + (
                math.cos(lat) * math.cos(other_lat) * math.sin(delta_lon / 2) ** 2
            )
            if 2 * 6371000 * math.asin(math.sqrt(min(1.0, h))) < POLICY["diversity_distance_m"]:
                nearby = True
                break
        if nearby:
            suppressed += 1
        else:
            recommendations.append(result)
    total_results = len(results)
    page_end = None if result_limit is None else result_offset + result_limit
    result_page = results[result_offset:page_end]
    return {
        "index_id": release,
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "scoring_method": SCORING_METHOD,
        "weights": checked,
        "dimension_weights": selected_dimension_weights,
        "ranking_tie_tolerance": POLICY["ranking_tie_tolerance"],
        **_summarize_near_equivalents(near_equivalent),
        "applied_land_cover_filters": land_cover_filters,
        "applied_land_cover_min_fractions": land_cover_minimums,
        "land_cover_filter_excluded_count": land_cover_filter_excluded,
        "land_cover_missing_count": land_cover_missing_count,
        "land_cover_unsuitable_count": land_cover_unsuitable_count,
        "target": target,
        "status": "ranked" if results else "insufficient_evidence",
        "results": result_page,
        "total_results": total_results,
        "result_limit": len(result_page) if result_limit is None else result_limit,
        "result_offset": result_offset,
        "next_result_offset": (
            result_offset + len(result_page)
            if page_end is not None and result_offset + len(result_page) < total_results
            else None
        ),
        "recommendations": recommendations[:10],
        "diversified_count": len(recommendations),
        "suppressed_neighbours": suppressed,
        "mission_suitability": {
            "status": "not_assessed",
            "explanation": "Terrain similarity does not establish vehicle or site suitability.",
        },
        "limitations": [
            "Rankings sort by the eight-dimension weighted prototype similarity; source-backed "
            "evidence coverage is a separate reported quantity. Terrain and operations share "
            "one effective weight budget to prevent double-counting their shared measurements.",
            "Similarity is a research ranking index, not a probability or validated analogue.",
            "A sparse MOLA elevation range describes observed bins only and can omit "
            "unobserved extremes; it is ranked as limited evidence.",
            "ESA WorldCover is a 2021 categorical map; class fractions are coarse context "
            "summaries, not field measurements. Active filters require complete classification.",
            "Earth DEM represents surface elevation and may include vegetation or buildings.",
        ],
    }
