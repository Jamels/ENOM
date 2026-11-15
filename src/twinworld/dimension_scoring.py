"""Authoritative evidence-aware scoring for the eight analogue dimensions.

Terrain uses the existing scorecard; mapped material groups and tightly gated
physical indicators use explicitly experimental indices. Unsupported local
observations remain unscored. No comparator establishes analogue validity.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from twinworld.scorecards import VARIABLES, compare_candidate

TERRAIN_ID = "terrain"
OPERATIONS_ID = "mission_operations"
SHARED_TERRAIN_VARIABLES = {
    "mean_slope",
    "slope_p90",
    "median_local_relief_3x3",
    "median_roughness_3x3",
}


def _dimension_map(value: list[dict[str, Any]] | Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Accept dimension rows or ID-to-evidence mappings without dropping inputs."""
    if isinstance(value, Mapping):
        result: dict[str, dict[str, Any]] = {}
        for key, evidence in value.items():
            if isinstance(evidence, Mapping):
                row = dict(evidence)
                row.setdefault("id", key)
            else:
                evidence_rows = list(evidence) if isinstance(evidence, list) else []
                row = {"id": key, "evidence_items": evidence_rows}
            result[str(key)] = row
        return result
    result = {}
    for row in value:
        if isinstance(row, dict) and isinstance(row.get("id", row.get("dimension_id")), str):
            result[str(row.get("id", row.get("dimension_id")))] = row
    return result


def _measurements(row: dict[str, Any]) -> list[dict[str, Any]]:
    if "scoring_measurements" in row:
        return [item for item in (row.get("scoring_measurements") or []) if isinstance(item, dict)]
    measurements = list(row.get("measurements", []) or [])
    for evidence in row.get("evidence_items", []) or []:
        if isinstance(evidence, dict):
            nested = evidence.get("measurements")
            if isinstance(nested, list):
                measurements.extend(item for item in nested if isinstance(item, dict))
            elif isinstance(evidence.get("name"), str):
                measurements.append(evidence)
    return [item for item in measurements if isinstance(item, dict)]


def _material_groups(row: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    """Map explicit mapped interpretations into a conservative shared taxonomy."""
    groups: set[str] = set()
    provenance: list[dict[str, Any]] = []
    interpretations = list(row.get("interpretations", []) or [])
    for evidence in row.get("evidence_items", []) or []:
        if isinstance(evidence, dict) and evidence.get("evidence_kind") == "interpreted_map_unit":
            interpretations.append(
                {**evidence, "classification_status": evidence.get("availability")}
            )
        if isinstance(evidence, dict) and isinstance(evidence.get("interpretation"), dict):
            interpretation = dict(evidence["interpretation"])
            interpretation.setdefault("observation_id", evidence.get("id"))
            interpretation.setdefault("source_url", evidence.get("source_url"))
            coverage = evidence.get("spatial_coverage", {})
            if isinstance(coverage, dict):
                interpretation.setdefault(
                    "nominal_cartographic_scale", coverage.get("nominal_cartographic_scale")
                )
            interpretations.append(interpretation)
    for item in interpretations:
        if not isinstance(item, dict) or item.get("classification_status") != "mapped":
            continue
        if not item.get("source_url") or not item.get("nominal_cartographic_scale"):
            continue
        label = str(item.get("map_unit_interpretation") or item.get("summary") or "").lower()
        materials = item.get("major_materials", [])
        material_terms = (
            {str(value).lower() for value in materials} if isinstance(materials, list) else set()
        )
        declared_groups = item.get("material_groups", [])
        item_groups = (
            {
                str(value)
                for value in declared_groups
                if value in {"mafic_volcanic", "intermediate_volcanic", "carbonate_sedimentary"}
            }
            if isinstance(declared_groups, list)
            and item.get("normalization_status") in {None, "normalized", "crosswalked"}
            else set()
        )
        if "basaltic lava" in label or material_terms.intersection({"basalt", "basanite"}):
            item_groups.add("mafic_volcanic")
        if material_terms.intersection({"andesite", "dacite"}):
            item_groups.add("intermediate_volcanic")
        if "carbonate" in label or "carbonate" in material_terms:
            item_groups.add("carbonate_sedimentary")
        if item_groups:
            groups.update(item_groups)
            provenance.append(
                {
                    "observation_id": item.get("observation_id"),
                    "dataset_id": item.get("dataset_id"),
                    "map_unit_code": item.get("map_unit_code"),
                    "map_unit_name": item.get("map_unit_name"),
                    "mapped_interpretation": item.get("map_unit_interpretation")
                    or item.get("summary"),
                    "major_materials": sorted(material_terms),
                    "material_groups": sorted(item_groups),
                    "normalization_status": item.get(
                        "normalization_status", "explicit_coarse_crosswalk"
                    ),
                    "nominal_cartographic_scale": item.get("nominal_cartographic_scale"),
                    "source_url": item.get("source_url"),
                }
            )
    return groups, provenance


def _geology_comparison(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float | None, list[dict[str, Any]], str]:
    target_groups, target_sources = _material_groups(target)
    candidate_groups, candidate_sources = _material_groups(candidate)
    if not target_groups or not candidate_groups:
        return (
            None,
            [],
            (
                "Both places need mapped material terms supported by the "
                "explicit coarse crosswalk. Raw map-unit codes are not compared."
            ),
        )
    union = target_groups | candidate_groups
    score = len(target_groups & candidate_groups) / len(union)
    scales = sorted(
        {
            str(evidence["nominal_cartographic_scale"])
            for evidence in [*target_sources, *candidate_sources]
            if evidence.get("nominal_cartographic_scale")
        }
    )
    return (
        score,
        [
            {
                "name": "mapped_material_group_jaccard",
                "label": "Mapped coarse material-group overlap",
                "availability": "available",
                "score": score,
                "reference_groups": sorted(target_groups),
                "candidate_groups": sorted(candidate_groups),
                "units": "dimensionless categorical Jaccard index",
                "reference_evidence": target_sources,
                "candidate_evidence": candidate_sources,
                "nominal_cartographic_scales": scales,
            }
        ],
        (
            "Experimental interpreted-material crosswalk; compares broad "
            "mapped groups only. It does not establish mineral abundance, "
            "exact lithology, or geological equivalence. Regional map scales "
            "and classification practices differ."
        ),
    )


# These are explicit experimental ranking indices, not calibrated physical
# equivalence models. No existing unmatched climatology/radar/literature record
# is relabelled to satisfy this contract.
PHYSICAL_COMPARISONS = {
    "thermal_illumination": {
        "surface_temperature": ("K", "relative", "positive"),
        "illuminated_fraction": ("1", "bounded", "fraction"),
    },
    "water_resources": {"water_ice_mass_fraction": ("kg/kg", "bounded", "fraction")},
    "dust_processes": {
        "surface_migration_rate": ("m/year", "relative", "nonnegative"),
        "erosion_rate": ("m/year", "relative", "nonnegative"),
    },
    "biology_habitability": {"water_activity": ("1", "bounded", "fraction")},
    "subsurface": {
        "observed_cavity_span": ("m", "relative", "positive"),
        "observed_cavity_depth": ("m", "relative", "positive"),
    },
}
MISSING_REQUIREMENTS = {
    "thermal_illumination": (
        "Paired QA-qualified surface temperatures or illumination "
        "fractions with the same explicit local-time/season/statistic "
        "comparison basis are missing. Air temperature and thermal "
        "inertia cannot substitute."
    ),
    "water_resources": (
        "Paired measured water/ice mass fractions with the same "
        "material/depth/statistic basis are missing. Neutron counts, "
        "CPR, humidity and modeled ice stability cannot substitute."
    ),
    "dust_processes": (
        "Paired repeat-observation surface migration or erosion rates "
        "with matched temporal/statistical support are missing. Wind "
        "speed alone cannot substitute."
    ),
    "biology_habitability": (
        "Paired independently measured environmental water activity with "
        "matching material/depth/temperature conditions is missing. This "
        "proxy cannot infer life or overall habitability."
    ),
    "subsurface": (
        "Paired measured cavity geometry with confirmed observed-cavity "
        "status and matching measurement definitions is missing. Pit "
        "interpretations and radar reflectors cannot substitute."
    ),
}


def _physical_comparison(
    dimension_id: str,
    target: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[float | None, float, list[dict[str, Any]]]:
    specs = PHYSICAL_COMPARISONS[dimension_id]

    def eligible(row: dict[str, Any], name: str) -> bool:
        value, scale = row.get("value"), row.get("spatial_scale_m")
        units, _metric, domain = specs[name]
        if (
            row.get("name") != name
            or row.get("units") != units
            or row.get("availability") != "available"
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or scale <= 0
            or isinstance(row.get("support_fraction"), bool)
            or row.get("support_fraction") != 1.0
            or not isinstance(row.get("comparison_basis"), str)
            or not row["comparison_basis"].strip()
            or not isinstance(row.get("source_url"), str)
            or not row["source_url"].strip()
            or not isinstance(row.get("product_id"), str)
            or not row["product_id"].strip()
        ):
            return False
        if domain == "fraction" and not 0 <= value <= 1:
            return False
        if domain == "positive" and value <= 0:
            return False
        if domain == "nonnegative" and value < 0:
            return False
        return dimension_id != "subsurface" or row.get("feature_status") == "observed_cavity"

    details = []
    for name, (units, metric, _domain) in specs.items():
        refs = [row for row in _measurements(target) if eligible(row, name)]
        earths = [row for row in _measurements(candidate) if eligible(row, name)]
        # Ambiguous repeat observations need a source-specific aggregation step.
        if len(refs) != 1 or len(earths) != 1:
            continue
        ref, earth = refs[0], earths[0]
        if (
            ref["comparison_basis"] != earth["comparison_basis"]
            or max(ref["spatial_scale_m"], earth["spatial_scale_m"])
            / min(ref["spatial_scale_m"], earth["spatial_scale_m"])
            > 1.05
        ):
            continue
        a, b = float(ref["value"]), float(earth["value"])
        difference = abs(a - b)
        score = (
            1.0 - difference
            if metric == "bounded"
            else (min(a, b) / max(a, b) if max(a, b) else 1.0)
        )
        details.append(
            {
                "name": name,
                "units": units,
                "reference_value": a,
                "earth_value": b,
                "score": score,
                "difference": b - a,
                "availability": "available",
                "reference_spatial_scale_m": ref["spatial_scale_m"],
                "earth_spatial_scale_m": earth["spatial_scale_m"],
                "scale_match": True,
                "comparison_basis": ref["comparison_basis"],
                "reference_evidence": ref,
                "candidate_evidence": earth,
                "metric": "1 - absolute fraction difference"
                if metric == "bounded"
                else "min/max ratio",
            }
        )
    return (
        sum(row["score"] for row in details) / len(details) if details else None,
        len(details) / len(specs),
        details,
    )


def _weights(weights: dict[str, float], dimension_ids: set[str]) -> dict[str, float]:
    if set(weights) != dimension_ids:
        missing, extra = sorted(dimension_ids - set(weights)), sorted(set(weights) - dimension_ids)
        raise ValueError(
            f"Weights must include all eight dimensions (missing={missing}, unknown={extra})"
        )
    checked: dict[str, float] = {}
    for key, raw in weights.items():
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(raw)
            or raw < 0
        ):
            raise ValueError(f"Weight '{key}' must be a finite, non-negative number")
        checked[key] = float(raw)
    try:
        total = math.fsum(checked.values())
    except OverflowError as exc:
        raise ValueError("The total dimension weight must be finite") from exc
    if not math.isfinite(total):
        raise ValueError("The total dimension weight must be finite")
    if total <= 0:
        raise ValueError("At least one dimension weight must be greater than zero")
    return checked


def _terrain_comparison(
    target: dict[str, Any], candidate: dict[str, Any], supplied: dict[str, Any] | None
) -> dict[str, Any]:
    if supplied is not None:
        return supplied
    names = list(VARIABLES)
    return compare_candidate(
        _measurements(target), _measurements(candidate), {name: 1.0 for name in names}
    )


def _scored_variables(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in comparison.get("variables", [])
        if isinstance(item, dict) and item.get("name") in VARIABLES
    ]


def compare_dimensions(
    target_dimensions: list[dict[str, Any]] | Mapping[str, Any],
    candidate_dimensions: list[dict[str, Any]] | Mapping[str, Any],
    weights: dict[str, float],
    terrain_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare supported dimensions and preserve explicit evidence gaps.

    Terrain and mission-operations terrain proxies share one evidence budget:
    their combined influence is ``max(weight_terrain, weight_operations)``.
    That budget is split by the two assigned weights. This prevents selecting
    both dimensions from silently amplifying the same four terrain variables.
    """
    from twinworld.analogue import DIMENSIONS

    ids = set(DIMENSIONS)
    checked_weights = _weights(weights, ids)
    target = _dimension_map(target_dimensions)
    candidate = _dimension_map(candidate_dimensions)
    target_terrain = target.get(TERRAIN_ID, {})
    candidate_terrain = candidate.get(TERRAIN_ID, {})
    comparison = _terrain_comparison(target_terrain, candidate_terrain, terrain_comparison)
    variables = _scored_variables(comparison)

    terrain_weight = checked_weights[TERRAIN_ID]
    operations_weight = checked_weights[OPERATIONS_ID]
    shared_budget = max(terrain_weight, operations_weight)
    split_total = terrain_weight + operations_weight
    terrain_budget = shared_budget * (terrain_weight / split_total) if split_total else 0.0
    operations_budget = shared_budget * (operations_weight / split_total) if split_total else 0.0

    dimension_scores: list[dict[str, Any]] = []
    aggregate_numerator = 0.0
    aggregate_denominator = 0.0
    weighted_coverage_numerator = 0.0
    requested_total = sum(checked_weights.values())
    missing: list[str] = []

    for dimension_id, spec in DIMENSIONS.items():
        original = candidate.get(dimension_id, {})
        row = dict(original)
        row.setdefault("label", spec["label"])
        assigned_weight = checked_weights[dimension_id]
        score: float | None = None
        effective_weight = 0.0
        score_coverage = 0.0
        comparison_variables: list[dict[str, Any]] = []
        methodology = (
            "No validated cross-body comparison method is currently available for this evidence."
        )
        note = "Evidence is retained for context; no numerical similarity score is supported."
        evidence_status = str(original.get("status", "not_observed"))

        if dimension_id in {TERRAIN_ID, OPERATIONS_ID}:
            budget = terrain_budget if dimension_id == TERRAIN_ID else operations_budget
            selected = [
                item
                for item in variables
                if dimension_id == TERRAIN_ID or item.get("name") in SHARED_TERRAIN_VARIABLES
            ]
            selected_budget = budget
            if dimension_id == TERRAIN_ID and operations_weight == 0:
                selected_budget = assigned_weight
            elif dimension_id == OPERATIONS_ID and terrain_weight == 0:
                selected_budget = assigned_weight
            eligible = [
                item
                for item in selected
                if isinstance(item.get("score"), (int, float))
                and math.isfinite(item["score"])
                and item.get("availability") == "available"
                and isinstance(item.get("weight", 1.0), (int, float))
                and item.get("weight", 1.0) > 0
            ]
            requested_component_weight = sum(
                float(item.get("weight", 1.0))
                for item in selected
                if isinstance(item.get("weight", 1.0), (int, float))
                and math.isfinite(item.get("weight", 1.0))
                and item.get("weight", 1.0) > 0
            )
            used_component_weight = sum(float(item.get("weight", 1.0)) for item in eligible)
            score_coverage = (
                used_component_weight / requested_component_weight
                if requested_component_weight > 0
                else 0.0
            )
            if eligible:
                component_numerator = sum(
                    float(item["score"]) * float(item.get("weight", 1.0)) for item in eligible
                )
                score = (
                    float(comparison["similarity_score"])
                    if dimension_id == TERRAIN_ID and comparison.get("similarity_score") is not None
                    else component_numerator / used_component_weight
                )
                effective_weight = selected_budget * score_coverage
                methodology = (
                    "Existing terrain scorecard: per-measurement exp(-absolute "
                    "difference / documented tolerance), restricted to matching "
                    "units and spatial scales within 5%."
                )
                note = (
                    "Terrain measurements are coarse similarity proxies, not vehicle "
                    "safety or mission suitability. Terrain and operations share "
                    "these source measurements."
                )
                comparison_variables = selected
                evidence_status = "available" if score_coverage == 1 else "partial_coverage"
            else:
                exclusions = [
                    *target_terrain.get("scoring_exclusions", []),
                    *candidate_terrain.get("scoring_exclusions", []),
                ]
                note = "; ".join(exclusions) or (
                    "No terrain variables were comparable at both places with "
                    "matching units and spatial scales."
                )
                comparison_variables = selected
            if assigned_weight > 0:
                effective_weight = min(assigned_weight, effective_weight)
                if eligible and score is not None:
                    aggregate_numerator += effective_weight * score
                    aggregate_denominator += effective_weight
                    weighted_coverage_numerator += effective_weight
            else:
                score = None
                effective_weight = 0.0
            if dimension_id == OPERATIONS_ID:
                methodology = (
                    "Terrain-derived operations proxy using the four shared slope, "
                    "relief, and roughness measurements; no vehicle constraints or "
                    "traverses are evaluated."
                )
                note = (
                    "Shares terrain evidence with the terrain dimension; its "
                    "effective weight is allocated from one shared budget. This is "
                    "not an engineering safety assessment."
                )

        if dimension_id == "geology_materials":
            score, comparison_variables, note = _geology_comparison(
                target.get(dimension_id, {}), candidate.get(dimension_id, {})
            )
            if score is not None:
                score_coverage = 1.0
                effective_weight = assigned_weight
                aggregate_numerator += effective_weight * score
                aggregate_denominator += effective_weight
                weighted_coverage_numerator += effective_weight
                methodology = (
                    "Experimental Jaccard similarity over an explicit broad "
                    "mapped-material crosswalk: basalt/basanite/basaltic lava flows "
                    "→ mafic volcanic; andesite/dacite → intermediate volcanic; "
                    "carbonate → carbonate sedimentary. Map-unit codes are never "
                    "compared."
                )
                evidence_status = "experimental_interpreted"

        if dimension_id in PHYSICAL_COMPARISONS:
            score, score_coverage, comparison_variables = _physical_comparison(
                dimension_id, target.get(dimension_id, {}), candidate.get(dimension_id, {})
            )
            note = MISSING_REQUIREMENTS[dimension_id]
            methodology = (
                "Experimental matched-measurand index: 1 minus absolute "
                "difference for bounded fractions; min/max ratio for nonnegative "
                "dimensional values. Requires full recorded support, canonical "
                "units, scales within 5%, unique observations, provenance and an "
                "identical explicit comparison basis."
            )
            if score is not None:
                effective_weight = assigned_weight * score_coverage
                aggregate_numerator += effective_weight * score
                aggregate_denominator += effective_weight
                weighted_coverage_numerator += effective_weight
                evidence_status = "experimental_proxy"
                note = (
                    "Matched physical indicator only; broader dimension coverage and "
                    "uncertainty remain limited. The declared matching basis and "
                    "observations have not been independently validated. No biological, "
                    "resource-access, "
                    "geological-equivalence or engineering-safety inference is made."
                )

        if score is None:
            missing.append(dimension_id)
        row.update(
            {
                "dimension_id": dimension_id,
                "id": dimension_id,
                "weight": assigned_weight,
                "score": score,
                "effective_weight": effective_weight,
                "weight_contribution": effective_weight * score if score is not None else 0.0,
                "methodology": methodology,
                "evidence_status": evidence_status,
                "score_coverage": score_coverage,
                "comparison_variables": comparison_variables,
                "score_note": note,
                "scored": score is not None,
                "methodology_kind": "experimental"
                if dimension_id not in {TERRAIN_ID, OPERATIONS_ID}
                else "proxy",
                "reference_evidence": target.get(dimension_id, {}),
                "limitations": [
                    note,
                    "Scores are uncalibrated research indices; uncertainty is not propagated.",
                ],
            }
        )
        dimension_scores.append(row)

    overall = aggregate_numerator / aggregate_denominator if aggregate_denominator > 0 else None
    independent_scored = {
        row["id"]
        for row in dimension_scores
        if row["effective_weight"] > 0 and row["id"] not in {TERRAIN_ID, OPERATIONS_ID}
    }
    if any(
        row["effective_weight"] > 0
        for row in dimension_scores
        if row["id"] in {TERRAIN_ID, OPERATIONS_ID}
    ):
        independent_scored.add("shared_terrain_evidence")
    return {
        "score": overall,
        "evidence_coverage": weighted_coverage_numerator / requested_total
        if requested_total
        else 0.0,
        "dimension_scores": dimension_scores,
        "missing_dimensions": missing,
        "independent_evidence_groups": sorted(independent_scored),
        "evidence_class": "experimental_multi_dimension"
        if len(independent_scored) > 1
        and any(row["evidence_status"] == "experimental_interpreted" for row in dimension_scores)
        else "multi_dimension"
        if len(independent_scored) > 1
        else "limited_evidence"
        if overall is not None
        else "no_comparable_evidence",
    }
