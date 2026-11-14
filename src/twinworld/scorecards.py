"""Missing-data-aware planetary-to-Earth terrain analogue scorecards."""

from __future__ import annotations

import math
from typing import Any

VARIABLES: dict[str, dict[str, Any]] = {
    "elevation_range": {
        "units": "m",
        "tolerance": 200.0,
        "label": "10 km footprint relief range",
    },
    "mean_slope": {"units": "degree", "tolerance": 5.0, "label": "Mean slope"},
    "slope_p90": {"units": "degree", "tolerance": 10.0, "label": "90th percentile slope"},
    "median_local_relief_3x3": {
        "units": "m",
        "tolerance": 60.0,
        "label": "Median 3×3 local relief",
    },
    "median_roughness_3x3": {
        "units": "m",
        "tolerance": 20.0,
        "label": "Median 3×3 roughness",
    },
}

MISSION_PRESETS: dict[str, dict[str, Any]] = {
    "landing": {
        "name": "Landing-site terrain screening",
        "weights": {
            "elevation_range": 0.20,
            "mean_slope": 0.28,
            "slope_p90": 0.24,
            "median_local_relief_3x3": 0.16,
            "median_roughness_3x3": 0.12,
        },
        "limits": {"slope_p90": 10.0, "median_local_relief_3x3": 60.0},
        "limit_basis": {
            "slope_p90": {
                "note": (
                    "Reference only: a draft NASA VIPER requirement limits lander effective "
                    "slope to 10°. This 926 m slope percentile is not the foot-scale "
                    "effective-slope test."
                ),
                "source_url": "https://assets.science.nasa.gov/content/dam/science/psd/lunar-science/documents/VIPER_Technical_Information_AFPP.pdf",
            },
            "median_local_relief_3x3": {
                "note": (
                    "60 m at 1.39 km scale is a research assumption; no vehicle-specific "
                    "limit is validated."
                ),
                "source_url": None,
            },
        },
    },
    "base_construction": {
        "name": "Base-construction terrain screening",
        "weights": {
            "elevation_range": 0.20,
            "mean_slope": 0.16,
            "slope_p90": 0.12,
            "median_local_relief_3x3": 0.28,
            "median_roughness_3x3": 0.24,
        },
        "limits": {"mean_slope": 5.0, "median_local_relief_3x3": 40.0},
        "limit_basis": {
            "mean_slope": {
                "note": (
                    "Reference only: a NASA notional lunar landing-pad document lists <5°; "
                    "it is preliminary and does not establish a base-construction limit."
                ),
                "source_url": "https://ntrs.nasa.gov/api/citations/20205009125/downloads/Lunar%20Landing%20%26%20Launch%20Pads%20v1.pdf",
            },
            "median_local_relief_3x3": {
                "note": (
                    "40 m at 1.39 km scale is a research assumption; no construction "
                    "requirement is validated."
                ),
                "source_url": None,
            },
        },
    },
    "rover_mobility": {
        "name": "Rover-mobility terrain screening",
        "weights": {
            "elevation_range": 0.20,
            "mean_slope": 0.16,
            "slope_p90": 0.32,
            "median_local_relief_3x3": 0.20,
            "median_roughness_3x3": 0.12,
        },
        "limits": {"slope_p90": 15.0, "median_local_relief_3x3": 100.0},
        "limit_basis": {
            "slope_p90": {
                "note": (
                    "Reference only: NASA slope-climbing trials tested a specific rover on loose "
                    "sand through 15°. This 926 m terrain percentile is not a mobility "
                    "performance limit."
                ),
                "source_url": "https://ntrs.nasa.gov/citations/20180000349",
            },
            "median_local_relief_3x3": {
                "note": (
                    "100 m at 1.39 km scale is a research assumption; no rover-specific "
                    "limit is validated."
                ),
                "source_url": None,
            },
        },
    },
}


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate score weights without silently normalizing their relative values."""
    if not weights:
        raise ValueError("At least one terrain weight is required")
    unknown = set(weights) - set(VARIABLES)
    if unknown:
        raise ValueError(f"Unknown terrain weight(s): {', '.join(sorted(unknown))}")
    normalized_input: dict[str, float] = {}
    for name, raw_value in weights.items():
        value = float(raw_value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Weight '{name}' must be a finite, non-negative number")
        normalized_input[name] = value
    if sum(normalized_input.values()) <= 0:
        raise ValueError("At least one terrain weight must be greater than zero")
    return normalized_input


def measurements_by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index known, valued terrain measurements by their stable variable name."""
    available: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        value = row.get("value")
        scale = row.get("spatial_scale_m")
        if (
            name not in VARIABLES
            or row.get("availability") != "available"
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or scale <= 0
        ):
            continue
        available[name] = row
    return available


def _compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Require matching units and spatial scales within five percent."""
    if a.get("units") != b.get("units"):
        return False
    scale_a, scale_b = float(a["spatial_scale_m"]), float(b["spatial_scale_m"])
    if scale_a <= 0 or scale_b <= 0:
        return False
    # Comparing different footprint sizes can create a false terrain match.
    return max(scale_a, scale_b) / min(scale_a, scale_b) <= 1.05


def compare_candidate(
    reference_measurements: list[dict[str, Any]],
    earth_measurements: list[dict[str, Any]],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Compare only same-unit, within-5%-scale derived local terrain measures.

    Variable score is exp(-absolute difference / a documented engineering-scale
    tolerance). The result is an interpretable ranking index, not a probability.
    """
    checked_weights = validate_weights(weights)
    reference = measurements_by_name(reference_measurements)
    earth = measurements_by_name(earth_measurements)
    details: list[dict[str, Any]] = []
    weighted_sum = 0.0
    used_weight = 0.0
    for name, weight in checked_weights.items():
        a, b = reference.get(name), earth.get(name)
        if weight == 0 or a is None or b is None or not _compatible(a, b):
            details.append(
                {
                    "name": name,
                    "label": VARIABLES[name]["label"],
                    "availability": "unmatched_or_missing",
                    "reference_value": None if a is None else a.get("value"),
                    "earth_value": None if b is None else b.get("value"),
                    "weight": weight,
                    "score": None,
                    "difference": None,
                    "units": VARIABLES[name]["units"],
                    "tolerance": VARIABLES[name]["tolerance"],
                    "scale_match": False,
                }
            )
            continue
        delta = abs(float(a["value"]) - float(b["value"]))
        tolerance = float(VARIABLES[name]["tolerance"])
        score = math.exp(-delta / tolerance)
        details.append(
            {
                "name": name,
                "label": VARIABLES[name]["label"],
                "availability": "available",
                "reference_value": float(a["value"]),
                "earth_value": float(b["value"]),
                "difference": float(b["value"]) - float(a["value"]),
                "units": VARIABLES[name]["units"],
                "reference_spatial_scale_m": float(a["spatial_scale_m"]),
                "earth_spatial_scale_m": float(b["spatial_scale_m"]),
                "scale_match": True,
                "weight": weight,
                "tolerance": tolerance,
                "score": score,
            }
        )
        weighted_sum += weight * score
        used_weight += weight
    final_score = weighted_sum / used_weight if used_weight > 0 else None
    expected_count = sum(weight > 0 for weight in checked_weights.values())
    measured_count = sum(item["availability"] == "available" for item in details)
    return {
        "similarity_score": final_score,
        "score_interpretation": (
            "0–1 terrain ranking index; not a probability or mission-suitability score"
        ),
        "data_completeness": measured_count / expected_count if expected_count else 0.0,
        "matched_variable_count": measured_count,
        "requested_variable_count": expected_count,
        "variables": details,
    }


def mission_suitability(measurements: list[dict[str, Any]], objective: str) -> dict[str, Any]:
    """Return transparent provisional screening checks, separate from similarity."""
    if objective not in MISSION_PRESETS:
        raise ValueError(f"Unknown mission objective '{objective}'")
    observed = measurements_by_name(measurements)
    limits = MISSION_PRESETS[objective]["limits"]
    limit_basis = MISSION_PRESETS[objective]["limit_basis"]
    checks = []
    for name, maximum in limits.items():
        row = observed.get(name)
        checks.append(
            {
                "name": name,
                "value": None if row is None else float(row["value"]),
                "units": VARIABLES[name]["units"],
                "maximum": maximum,
                "basis": limit_basis[name]["note"],
                "basis_source_url": limit_basis[name]["source_url"],
                "status": (
                    "not_assessed"
                    if row is None
                    else "within_screen"
                    if float(row["value"]) <= maximum
                    else "outside_screen"
                ),
            }
        )
    if any(item["status"] == "outside_screen" for item in checks):
        status = "provisional_concern"
    elif any(item["status"] == "not_assessed" for item in checks):
        status = "insufficient_data"
    else:
        status = "provisional_pass"
    return {
        "status": status,
        "checks": checks,
        "qualification": (
            "Provisional terrain-only screening; criteria are configurable research assumptions, "
            "not validated vehicle or site-certification limits."
        ),
    }
