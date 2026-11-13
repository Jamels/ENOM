"""Missing-data-aware terrain analogue scorecards for terrestrial candidates."""

from __future__ import annotations

import math
from typing import Any

VARIABLES: dict[str, dict[str, Any]] = {
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
            "mean_slope": 0.35,
            "slope_p90": 0.30,
            "median_local_relief_3x3": 0.20,
            "median_roughness_3x3": 0.15,
        },
        "limits": {"slope_p90": 10.0, "median_local_relief_3x3": 60.0},
    },
    "base_construction": {
        "name": "Base-construction terrain screening",
        "weights": {
            "mean_slope": 0.20,
            "slope_p90": 0.15,
            "median_local_relief_3x3": 0.35,
            "median_roughness_3x3": 0.30,
        },
        "limits": {"mean_slope": 5.0, "median_local_relief_3x3": 40.0},
    },
    "rover_mobility": {
        "name": "Rover-mobility terrain screening",
        "weights": {
            "mean_slope": 0.20,
            "slope_p90": 0.40,
            "median_local_relief_3x3": 0.25,
            "median_roughness_3x3": 0.15,
        },
        "limits": {"slope_p90": 15.0, "median_local_relief_3x3": 100.0},
    },
}


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
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
    return {
        row["name"]: row
        for row in rows
        if row.get("name") in VARIABLES
        and row.get("value") is not None
        and row.get("spatial_scale_m") is not None
    }


def _compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("units") != b.get("units"):
        return False
    scale_a, scale_b = float(a["spatial_scale_m"]), float(b["spatial_scale_m"])
    if scale_a <= 0 or scale_b <= 0:
        return False
    return max(scale_a, scale_b) / min(scale_a, scale_b) <= 1.05


def compare_candidate(
    lunar_measurements: list[dict[str, Any]],
    earth_measurements: list[dict[str, Any]],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Compare only same-unit, within-5%-scale derived local terrain measures.

    Variable score is exp(-absolute difference / a documented engineering-scale
    tolerance). The result is an interpretable ranking index, not a probability.
    """
    checked_weights = validate_weights(weights)
    lunar = measurements_by_name(lunar_measurements)
    earth = measurements_by_name(earth_measurements)
    details: list[dict[str, Any]] = []
    weighted_sum = 0.0
    used_weight = 0.0
    for name, weight in checked_weights.items():
        a, b = lunar.get(name), earth.get(name)
        if weight == 0 or a is None or b is None or not _compatible(a, b):
            details.append(
                {
                    "name": name,
                    "label": VARIABLES[name]["label"],
                    "availability": "unmatched_or_missing",
                    "lunar_value": None if a is None else a.get("value"),
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
                "lunar_value": float(a["value"]),
                "earth_value": float(b["value"]),
                "difference": float(b["value"]) - float(a["value"]),
                "units": VARIABLES[name]["units"],
                "lunar_spatial_scale_m": float(a["spatial_scale_m"]),
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
    checks = []
    for name, maximum in limits.items():
        row = observed.get(name)
        checks.append(
            {
                "name": name,
                "value": None if row is None else float(row["value"]),
                "units": VARIABLES[name]["units"],
                "maximum": maximum,
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
