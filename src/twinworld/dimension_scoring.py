"""Eight-dimension prototype scoring with evidence and estimates kept separate.

Every requested dimension receives a bounded prototype score. Compatible
observations remain distinguishable from context-based estimates and neutral
simulations; no score establishes analogue validity or mission suitability.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache
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

BODY_SOLAR_PARAMETERS = {
    "earth": {
        "obliquity_deg": 23.44,
        "solar_day_hours": 24.0,
        "source_url": "https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html",
    },
    "mars": {
        "obliquity_deg": 25.19,
        "solar_day_hours": 24.6597,
        "source_url": "https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html",
    },
    "moon": {
        "obliquity_deg": 1.54,
        "solar_day_hours": 708.73,
        "source_url": (
            "https://ntrs.nasa.gov/api/citations/20205007447/downloads/"
            "SLS-SPEC-159%20Cross-Program%20Design%20Specification%20for%20Natural%20"
            "Environments%20%28DSNE%29%20REVISION%20H.pdf"
        ),
    },
}


def _location(row: dict[str, Any]) -> dict[str, Any] | None:
    location = row.get("location")
    if not isinstance(location, Mapping):
        return None
    body = location.get("body")
    latitude = location.get("latitude_deg")
    if (
        body not in BODY_SOLAR_PARAMETERS
        or isinstance(latitude, bool)
        or not isinstance(latitude, (int, float))
        or not math.isfinite(latitude)
        or not -90 <= latitude <= 90
    ):
        return None
    return {"body": body, "latitude_deg": float(latitude)}


@lru_cache(maxsize=4096)
def _daylight_hours_profile(body: str, latitude_rounded: float) -> tuple[float, ...]:
    """Idealized daylight hours over a normalized solar year, without horizons."""
    parameters = BODY_SOLAR_PARAMETERS[body]
    latitude = math.radians(latitude_rounded)
    obliquity = math.radians(parameters["obliquity_deg"])
    sin_latitude, cos_latitude = math.sin(latitude), math.cos(latitude)
    result = []
    for index in range(360):
        solar_longitude = 2 * math.pi * index / 360
        sin_declination = math.sin(obliquity) * math.sin(solar_longitude)
        cos_declination = math.sqrt(max(0.0, 1 - sin_declination**2))
        denominator = cos_latitude * cos_declination
        numerator = -sin_latitude * sin_declination
        if abs(denominator) < 1e-12:
            daylight_fraction = 1.0 if numerator < 0 else 0.0 if numerator > 0 else 0.5
        else:
            hour_angle_cosine = numerator / denominator
            daylight_fraction = (
                1.0
                if hour_angle_cosine <= -1
                else 0.0
                if hour_angle_cosine >= 1
                else math.acos(hour_angle_cosine) / math.pi
            )
        result.append(daylight_fraction * parameters["solar_day_hours"])
    return tuple(result)


def _solar_geometry_estimate(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float | None, list[dict[str, Any]]]:
    reference_location, earth_location = _location(target), _location(candidate)
    if reference_location is None or earth_location is None:
        return None, []
    reference_profile = _daylight_hours_profile(
        reference_location["body"], round(reference_location["latitude_deg"], 5)
    )
    earth_profile = _daylight_hours_profile(
        earth_location["body"], round(earth_location["latitude_deg"], 5)
    )
    component_scores = [
        min(reference, earth) / max(reference, earth)
        if max(reference, earth) > 0
        else 1.0
        for reference, earth in zip(reference_profile, earth_profile, strict=True)
    ]
    reference_mean = sum(reference_profile) / len(reference_profile)
    earth_mean = sum(earth_profile) / len(earth_profile)
    score = sum(component_scores) / len(component_scores)
    parameters = [
        BODY_SOLAR_PARAMETERS[reference_location["body"]],
        BODY_SOLAR_PARAMETERS[earth_location["body"]],
    ]
    return score, [
        {
            "name": "idealized_daylight_duration_profile",
            "label": "Idealized seasonal daylight-duration profile",
            "availability": "available",
            "reference_value": reference_mean,
            "earth_value": earth_mean,
            "units": "hours per local solar day",
            "score": score,
            "metric": "Mean pointwise min/max ratio over 360 normalized solar-longitude samples",
            "reference_body": reference_location["body"],
            "candidate_body": earth_location["body"],
            "reference_latitude_deg": reference_location["latitude_deg"],
            "candidate_latitude_deg": earth_location["latitude_deg"],
            "reference_obliquity_deg": parameters[0]["obliquity_deg"],
            "candidate_obliquity_deg": parameters[1]["obliquity_deg"],
            "reference_solar_day_hours": parameters[0]["solar_day_hours"],
            "candidate_solar_day_hours": parameters[1]["solar_day_hours"],
            "reference_source_url": parameters[0]["source_url"],
            "candidate_source_url": parameters[1]["source_url"],
            "assumptions": [
                "Spherical surface and geometric horizon",
                "No local terrain, crater-wall or boulder shadowing",
                "Sinusoidal solar declination using current axial obliquity",
                "Normalized seasons are aligned at northern spring equinox",
                "Lunar libration, nodal precession and orbital perturbations omitted",
            ],
        }
    ]


def _available_measurements(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        measurement
        for measurement in _measurements(row)
        if measurement.get("availability") == "available"
        and not isinstance(measurement.get("value"), bool)
        and isinstance(measurement.get("value"), (int, float))
        and math.isfinite(measurement["value"])
    ]


def _measurement_value(
    row: dict[str, Any], names: tuple[str, ...], contains: tuple[str, ...] = ()
) -> tuple[float | None, list[dict[str, Any]]]:
    matches = []
    wanted = {name.casefold() for name in names}
    terms = tuple(term.casefold() for term in contains)
    for measurement in _available_measurements(row):
        name = str(measurement.get("name", "")).casefold()
        if name in wanted or any(term in name for term in terms):
            matches.append(measurement)
    if not matches:
        return None, []
    return (
        sum(float(row["value"]) for row in matches) / len(matches),
        matches,
    )


def _prototype_context(row: dict[str, Any]) -> dict[str, Any]:
    context = row.get("prototype_context")
    return dict(context) if isinstance(context, Mapping) else {}


def _land_cover_water_index(row: dict[str, Any]) -> tuple[float | None, dict[str, float]]:
    context = _prototype_context(row)
    land_cover = context.get("land_cover")
    if not isinstance(land_cover, Mapping):
        return None, {}
    groups = land_cover.get("group_fractions")
    if not isinstance(groups, Mapping):
        return None, {}
    valid = {
        key: float(groups[key])
        for key in ("snow_ice", "water", "grass_shrub_wetland")
        if not isinstance(groups.get(key), bool)
        and isinstance(groups.get(key), (int, float))
        and math.isfinite(groups[key])
        and 0 <= groups[key] <= 1
    }
    if not valid:
        return None, {}
    value = (
        0.55 * valid.get("snow_ice", 0.0)
        + 0.30 * valid.get("water", 0.0)
        + 0.15 * valid.get("grass_shrub_wetland", 0.0)
    )
    return min(1.0, max(0.0, value)), valid


def _water_availability_estimate(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, list[dict[str, Any]], str]:
    target_location, earth_location = _location(target), _location(candidate)
    if target_location is None or earth_location is None or earth_location["body"] != "earth":
        return 0.5, [], "No paired place metadata; neutral simulated water-context estimate."

    humidity, humidity_rows = _measurement_value(
        candidate,
        ("RH2M",),
        ("relative humidity",),
    )
    precipitation, precipitation_rows = _measurement_value(
        candidate,
        (),
        ("precipitation",),
    )
    measured_water_activity, water_activity_rows = _measurement_value(
        candidate,
        (),
        ("water activity",),
    )
    land_index, land_groups = _land_cover_water_index(candidate)

    candidate_components: list[tuple[str, float, float]] = []
    if measured_water_activity is not None and 0 <= measured_water_activity <= 1:
        candidate_components.append(("sampled_soil_water_activity", measured_water_activity, 0.45))
    if humidity is not None and 0 <= humidity <= 100:
        candidate_components.append(("air_relative_humidity_fraction", humidity / 100, 0.25))
    if precipitation is not None and precipitation >= 0:
        units = str(precipitation_rows[0].get("units", "")).casefold()
        annual_mm = precipitation * 12 if "month" in units else precipitation
        candidate_components.append(
            ("annualized_precipitation_index", 1 - math.exp(-annual_mm / 250), 0.30)
        )
    if land_index is not None:
        candidate_components.append(("esa_worldcover_water_snow_wetland_index", land_index, 0.30))

    if candidate_components:
        total_weight = sum(weight for _name, _value, weight in candidate_components)
        candidate_index = sum(value * weight for _name, value, weight in candidate_components) / total_weight
        candidate_basis = "Earth source-context index from available climate, field and/or land-cover indicators"
    else:
        earth_latitude = abs(earth_location["latitude_deg"])
        candidate_index = 0.08 + 0.62 * (earth_latitude / 90) ** 1.5
        candidate_basis = "Latitude-based cold/wet prior; no site-specific Earth water context was indexed"

    latitude = abs(target_location["latitude_deg"])
    if target_location["body"] == "moon":
        target_index = 0.04 + 0.86 * min(1.0, max(0.0, (latitude - 70) / 20))
    else:
        target_index = 0.08 + 0.78 * min(1.0, max(0.0, (latitude - 48) / 42))
    score = 1 - abs(target_index - candidate_index)
    details = [
        {
            "name": "prototype_water_context_index",
            "label": "Prototype water-context index",
            "availability": "available",
            "reference_value": target_index,
            "earth_value": candidate_index,
            "units": "dimensionless prototype index",
            "score": score,
            "target_basis": (
                f"Simulated {target_location['body']} latitude prior at "
                f"{latitude:.3f}° absolute latitude; not an ice or liquid-water measurement"
            ),
            "candidate_basis": candidate_basis,
            "candidate_components": [
                {"name": name, "value": value, "weight": weight}
                for name, value, weight in candidate_components
            ],
            "candidate_land_cover": land_groups,
            "reference_evidence": [
                item for item in _source_evidence(target)
            ],
            "candidate_evidence": [
                item for item in _source_evidence(candidate)
            ],
        }
    ]
    return score, details, "Prototype resource-context resemblance; not a reserve or accessible-water estimate."


def _wind_index(row: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]]]:
    value, measurements = _measurement_value(
        row,
        ("WS10M", "ERA5 monthly mean 10 m wind speed", "MEDA horizontal wind speed"),
        ("wind speed",),
    )
    return (min(1.0, max(0.0, value / 10)), measurements) if value is not None else (None, [])


def _dust_process_estimate(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, list[dict[str, Any]], str]:
    target_location, earth_location = _location(target), _location(candidate)
    if target_location is None or earth_location is None:
        return 0.5, [], "No paired location metadata; neutral simulated dust-process estimate."
    target_wind, target_rows = _wind_index(target)
    earth_wind, earth_rows = _wind_index(candidate)
    if target_location["body"] == "moon" and target_wind is None:
        target_wind = 0.0
    elif target_wind is None:
        target_wind = 0.45
    if earth_wind is None:
        earth_wind = min(1.0, max(0.0, 0.15 + abs(earth_location["latitude_deg"]) / 120))
    score = 1 - abs(target_wind - earth_wind)
    details = [
        {
            "name": "near_surface_wind_potential_index",
            "label": "Near-surface wind-potential proxy",
            "availability": "available",
            "reference_value": target_wind,
            "earth_value": earth_wind,
            "units": "dimensionless index (wind speed / 10 m/s, capped)",
            "score": score,
            "reference_measurements": target_rows,
            "candidate_measurements": earth_rows,
            "normalization": "Wind-speed indicator divided by 10 m/s, then clipped to [0, 1]",
            "support_note": (
                "MEDA is a one-sol rover sample and Earth wind records are gridded "
                "climatologies at different sensor heights; this is an exploratory proxy."
            ),
        }
    ]
    return score, details, "Estimated wind-potential resemblance only; wind speed does not measure dust lifting, migration or erosion."


def _temperature_celsius(row: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]]]:
    value, measurements = _measurement_value(
        row,
        ("T2M", "ERA5 monthly mean 2 m air temperature", "MEDA ATS local air temperature near mast sensor 1"),
        ("air temperature",),
    )
    if value is None:
        return None, []
    units = str(measurements[0].get("units", "")).casefold()
    if units in {"k", "kelvin"}:
        value -= 273.15
    return value, measurements


def _habitability_estimate(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, list[dict[str, Any]], str]:
    target_location, earth_location = _location(target), _location(candidate)
    if target_location is None or earth_location is None:
        return 0.5, [], "No paired location metadata; neutral simulated environmental-stress estimate."
    temperature, temperature_rows = _temperature_celsius(candidate)
    humidity, humidity_rows = _measurement_value(candidate, ("RH2M",), ("relative humidity",))
    if temperature is not None or humidity is not None:
        components = []
        if temperature is not None:
            components.append(("thermal_extremity_index", min(1.0, abs(temperature - 15) / 80), 0.6))
        if humidity is not None and 0 <= humidity <= 100:
            components.append(("atmospheric_dryness_index", 1 - humidity / 100, 0.4))
        total_weight = sum(weight for _name, _value, weight in components)
        earth_stress = sum(value * weight for _name, value, weight in components) / total_weight
        earth_basis = "Earth 2 m air-climate context; humidity is atmospheric, not soil water activity"
    else:
        snow_index, groups = _land_cover_water_index(candidate)
        latitude_stress = abs(earth_location["latitude_deg"]) / 90
        earth_stress = min(1.0, max(0.0, 0.65 * latitude_stress + 0.35 * (snow_index or 0)))
        components = [("latitude_climate_prior", latitude_stress, 0.65)]
        if snow_index is not None:
            components.append(("land_cover_cold_wet_index", snow_index, 0.35))
        earth_basis = "Earth latitude and available land-cover context; no microbial data used as a score"
    target_stress = 1.0 if target_location["body"] == "moon" else 0.88
    score = 1 - abs(target_stress - earth_stress)
    detail = {
        "name": "prototype_environmental_stress_similarity",
        "label": "Prototype environmental-stress resemblance",
        "availability": "available",
        "reference_value": target_stress,
        "earth_value": earth_stress,
        "units": "dimensionless prototype index",
        "score": score,
        "target_basis": (
            f"Simulated {target_location['body']} environmental-stress prior; "
            "not a life-detection or habitability measurement"
        ),
        "candidate_basis": earth_basis,
        "candidate_components": [
            {"name": name, "value": value, "weight": weight}
            for name, value, weight in components
        ],
        "candidate_measurements": [*temperature_rows, *humidity_rows],
        "candidate_land_cover": _land_cover_water_index(candidate)[1],
        "reference_evidence": _source_evidence(target),
        "candidate_evidence": _source_evidence(candidate),
        "limitations": [
            "No extraterrestrial life or biological presence is inferred",
            "The score estimates environmental-stress resemblance, not habitability",
            "Temperature and humidity inputs do not share material, temporal or spatial support",
        ],
    }
    return score, [detail], "Estimated environmental-stress resemblance; it does not predict life or overall habitability."


def _subsurface_class(row: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    context = _prototype_context(row)
    candidate_type = context.get("candidate_type")
    source_url = context.get("source_url")
    summary = context.get("basis") or context.get("summary")
    if candidate_type in {"lunar_volcanic_lava_tube", "volcanic_lava_tubes"}:
        kind = "volcanic_opening"
    elif candidate_type == "terrestrial_caves":
        kind = "karst_or_other_cave"
    else:
        return None, []
    return kind, [
        {
            "candidate_type": candidate_type,
            "summary": summary,
            "source_url": source_url,
            "classification_status": "interpreted_or_catalogued",
        }
    ]


def _subsurface_estimate(
    target: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, list[dict[str, Any]], str]:
    target_class, target_evidence = _subsurface_class(target)
    earth_class, earth_evidence = _subsurface_class(candidate)
    if target_class is None or earth_class is None:
        return (
            0.5,
            [
                {
                    "name": "subsurface_context_prior",
                    "label": "Neutral subsurface prototype prior",
                    "availability": "estimated",
                    "reference_value": 0.5,
                    "earth_value": 0.5,
                    "units": "dimensionless prototype index",
                    "score": 0.5,
                    "target_evidence": target_evidence,
                    "candidate_evidence": earth_evidence,
                    "interpretation": "Unknown is not treated as absence.",
                }
            ],
            "Neutral estimate where one or both locations lack a source-linked cave or pit class; unknown is not a negative observation.",
        )
    score = 0.85 if target_class == earth_class == "volcanic_opening" else 0.2 if target_class != earth_class else 0.7
    return (
        score,
        [
            {
                "name": "interpreted_subsurface_context_overlap",
                "label": "Interpreted subsurface-context overlap",
                "availability": "available",
                "reference_value": target_class,
                "earth_value": earth_class,
                "units": "dimensionless prototype index",
                "score": score,
                "target_evidence": target_evidence,
                "candidate_evidence": earth_evidence,
                "interpretation": "Context-class heuristic; no cave geometry or survey completeness is inferred.",
            }
        ],
        "Estimated match of source-linked catalogue feature classes. Lunar skylight relations remain hypotheses and Earth subsurface geometry is not measured here.",
    )


def _source_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    sources = row.get("sources", [])
    if isinstance(sources, list):
        result.extend(dict(item) for item in sources if isinstance(item, Mapping))
    for item in row.get("evidence_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("source_url") or item.get("dataset_id"):
            result.append(
                {
                    "dataset_id": item.get("dataset_id"),
                    "product_id": item.get("product_id"),
                    "provider": item.get("provider"),
                    "url": item.get("source_url"),
                }
            )
    unique = {}
    for item in result:
        key = (item.get("dataset_id"), item.get("product_id"), item.get("url"))
        unique[key] = item
    return list(unique.values())


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
    """Return an eight-score prototype and separate comparable-evidence coverage.

    Every dimension receives a bounded prototype score. Compatible observations
    populate observed_score; estimates and neutral simulation fallbacks populate
    only score. Terrain and operations share a single DEM evidence budget.
    """
    from twinworld.analogue import DIMENSIONS

    checked_weights = _weights(weights, set(DIMENSIONS))
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
    terrain_budget = shared_budget * terrain_weight / split_total if split_total else 0.0
    operations_budget = shared_budget * operations_weight / split_total if split_total else 0.0
    rows: list[dict[str, Any]] = []
    total_numerator = 0.0
    total_denominator = 0.0
    observed_numerator = 0.0
    observed_denominator = 0.0
    evidence_coverage_numerator = 0.0
    source_context_numerator = 0.0
    estimated_weight_numerator = 0.0
    simulated_weight_numerator = 0.0
    measured_weight_numerator = 0.0
    missing_evidence: list[str] = []

    for dimension_id, spec in DIMENSIONS.items():
        target_row = target.get(dimension_id, {})
        original = candidate.get(dimension_id, {})
        row = dict(original)
        row.setdefault("label", spec["label"])
        assigned_weight = checked_weights[dimension_id]
        observed_score: float | None = None
        score_coverage = 0.0
        comparison_variables: list[dict[str, Any]] = []
        methodology = "Neutral simulated prototype prior; no paired evidence or domain proxy is available."
        note = "A neutral 0.5 value completes the prototype scorecard; it is not evidence of a match."
        score_origin = "simulated"
        evidence_status = "simulated_prior"

        if dimension_id in {TERRAIN_ID, OPERATIONS_ID}:
            selected = [
                item
                for item in variables
                if dimension_id == TERRAIN_ID or item.get("name") in SHARED_TERRAIN_VARIABLES
            ]
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
                observed_score = (
                    float(comparison["similarity_score"])
                    if dimension_id == TERRAIN_ID and comparison.get("similarity_score") is not None
                    else component_numerator / used_component_weight
                )
                comparison_variables = selected
                score_origin = "measured" if dimension_id == TERRAIN_ID else "estimated"
                evidence_status = "measured" if dimension_id == TERRAIN_ID else "terrain_proxy"
                methodology = (
                    "DEM-derived terrain scorecard using compatible units and scales; "
                    "component scores are exp(-absolute difference / documented tolerance)."
                    if dimension_id == TERRAIN_ID
                    else "Terrain-derived operations proxy using slope, local relief and roughness."
                )
                note = (
                    "Terrain similarity is a prototype index, not a hazard or safety assessment."
                    if dimension_id == TERRAIN_ID
                    else "Reuses Terrain measurements. A shared effective-weight budget prevents double counting."
                )
            else:
                exclusions = [
                    *target_terrain.get("scoring_exclusions", []),
                    *candidate_terrain.get("scoring_exclusions", []),
                ]
                note = "; ".join(exclusions) or "No compatible paired terrain measurements were available."
                comparison_variables = selected
            score = observed_score if observed_score is not None else 0.5
            effective_weight = (
                terrain_budget if dimension_id == TERRAIN_ID else operations_budget
            )
            if dimension_id == TERRAIN_ID and operations_weight == 0:
                effective_weight = assigned_weight
            elif dimension_id == OPERATIONS_ID and terrain_weight == 0:
                effective_weight = assigned_weight

        elif dimension_id == "geology_materials":
            observed_score, comparison_variables, note = _geology_comparison(target_row, original)
            if observed_score is not None:
                score_coverage = 1.0
                score_origin = "estimated"
                evidence_status = "interpreted_map_proxy"
                methodology = (
                    "Experimental Jaccard similarity over the explicit broad mapped-material "
                    "crosswalk. Raw map-unit codes are never compared."
                )
            score = observed_score if observed_score is not None else 0.5
            effective_weight = assigned_weight

        elif dimension_id in PHYSICAL_COMPARISONS:
            observed_score, score_coverage, comparison_variables = _physical_comparison(
                dimension_id, target_row, original
            )
            methodology = (
                "Experimental matched-measurand index requiring canonical units, complete "
                "support, provenance, unique measurements and a matching declared basis."
            )
            note = MISSING_REQUIREMENTS[dimension_id]
            if observed_score is not None:
                score_origin = "measured"
                evidence_status = "matched_measurement"
                score_coverage = 1.0
            score = observed_score if observed_score is not None else 0.5
            effective_weight = assigned_weight

        else:
            score = 0.5
            effective_weight = assigned_weight

        if observed_score is None:
            if dimension_id == "thermal_illumination":
                estimate, details = _solar_geometry_estimate(target_row, original)
                if estimate is not None:
                    score = estimate
                    comparison_variables = details
                    score_origin = "estimated"
                    evidence_status = "estimated_geometry"
                    methodology = (
                        "Derived seasonal daylight-duration curve from body axial obliquity, "
                        "solar-day duration and site latitude. Surface temperatures are not compared."
                    )
                    note = (
                        "Geometry estimate only; local horizons, terrain shadows, atmosphere, "
                        "thermal inertia and surface-temperature response are not modeled."
                    )
            elif dimension_id == "water_resources":
                score, comparison_variables, note = _water_availability_estimate(target_row, original)
                has_location_pair = bool(_location(target_row) and _location(original))
                score_origin = "estimated" if has_location_pair else "simulated"
                evidence_status = "estimated_resource_context" if has_location_pair else "simulated_prior"
                methodology = (
                    "Prototype water-context index: a planetary latitude prior compared with "
                    "available Earth humidity, precipitation, field water-activity and/or "
                    "land-cover context. It does not estimate a resource quantity."
                )
            elif dimension_id == "dust_processes":
                score, comparison_variables, note = _dust_process_estimate(target_row, original)
                has_location_pair = bool(_location(target_row) and _location(original))
                score_origin = "estimated" if has_location_pair else "simulated"
                evidence_status = "estimated_wind_proxy" if has_location_pair else "simulated_prior"
                methodology = (
                    "Prototype wind-potential index using available MEDA, POWER or ERA5 context, "
                    "normalized by 10 m/s. Wind speed is not a dust-lifting or erosion measurement."
                )
            elif dimension_id == "biology_habitability":
                score, comparison_variables, note = _habitability_estimate(target_row, original)
                has_location_pair = bool(_location(target_row) and _location(original))
                score_origin = "estimated" if has_location_pair else "simulated"
                evidence_status = (
                    "estimated_environmental_stress" if has_location_pair else "simulated_prior"
                )
                methodology = (
                    "Prototype environmental-stress resemblance using Earth climate or land-cover "
                    "context and an explicit planetary baseline. Biological studies remain context."
                )
            elif dimension_id == "subsurface":
                score, comparison_variables, note = _subsurface_estimate(target_row, original)
                has_class_pair = all(
                    _subsurface_class(item)[0] is not None for item in (target_row, original)
                )
                score_origin = "estimated" if has_class_pair else "simulated"
                score_coverage = 1.0 if has_class_pair else 0.0
                evidence_status = (
                    "interpreted_context_proxy" if has_class_pair else "simulated_prior"
                )
                methodology = (
                    "Prototype comparison of source-linked cave/pit catalogue classes. "
                    "Unsurveyed geometry and detection completeness are not inferred."
                )
            elif dimension_id not in {TERRAIN_ID, OPERATIONS_ID, "geology_materials"}:
                methodology = (
                    "Neutral simulated prototype prior. It contributes to prototype similarity "
                    "but not to observed similarity or evidence coverage."
                )
                note = (
                    "No paired source-backed observation or available proxy was sufficient; "
                    "a neutral 0.5 simulation is shown for the prototype."
                )

        if not math.isfinite(score):
            score = 0.5
            score_origin = "simulated"
            evidence_status = "simulated_prior"
            note = "A non-finite estimate was rejected and replaced by the neutral simulated prior."
        score = min(1.0, max(0.0, float(score)))

        if assigned_weight > 0:
            total_numerator += effective_weight * score
            total_denominator += effective_weight
            evidence_coverage_numerator += effective_weight * score_coverage
            if observed_score is not None and score_origin == "measured":
                observed_numerator += effective_weight * observed_score * score_coverage
                observed_denominator += effective_weight * score_coverage
            if (
                _source_evidence(target_row)
                or _source_evidence(original)
                or _available_measurements(target_row)
                or _available_measurements(original)
                or _prototype_context(target_row).get("land_cover")
                or _prototype_context(original).get("land_cover")
                or _prototype_context(target_row).get("candidate_type")
                or _prototype_context(original).get("candidate_type")
                or any(
                    item.get("reference_source_url") or item.get("candidate_source_url")
                    for item in comparison_variables
                )
            ):
                source_context_numerator += effective_weight
            if score_origin == "estimated":
                estimated_weight_numerator += effective_weight
            elif score_origin == "simulated":
                simulated_weight_numerator += effective_weight
            elif score_origin == "measured":
                measured_weight_numerator += effective_weight
        if assigned_weight > 0 and score_coverage == 0:
            missing_evidence.append(dimension_id)

        reference_sources = _source_evidence(target_row)
        candidate_sources = _source_evidence(original)
        row.update(
            {
                "dimension_id": dimension_id,
                "id": dimension_id,
                "weight": assigned_weight,
                "score": score,
                "prototype_score": score,
                "observed_score": observed_score if score_origin == "measured" else None,
                "score_origin": score_origin,
                "effective_weight": effective_weight,
                "weight_contribution": effective_weight * score,
                "normalized_contribution": (
                    effective_weight * score / total_denominator if total_denominator else 0.0
                ),
                "methodology": methodology,
                "evidence_status": evidence_status,
                "score_coverage": score_coverage,
                "comparison_variables": comparison_variables,
                "score_note": note,
                "scored": True,
                "evidence_backed": score_coverage > 0,
                "reference_sources": reference_sources,
                "candidate_sources": candidate_sources,
                "methodology_kind": score_origin,
                "reference_evidence": target_row,
                "limitations": [
                    note,
                    "Prototype estimates are uncalibrated; uncertainty is not propagated.",
                ],
            }
        )
        rows.append(row)

    overall = total_numerator / total_denominator if total_denominator else 0.5
    observed_overall = (
        observed_numerator / observed_denominator if observed_denominator else None
    )
    independent_scored = {
        row["id"]
        for row in rows
        if row["evidence_backed"]
        and row["effective_weight"] > 0
        and row["id"] not in {TERRAIN_ID, OPERATIONS_ID}
    }
    if any(
        row["evidence_backed"] and row["effective_weight"] > 0
        for row in rows
        if row["id"] in {TERRAIN_ID, OPERATIONS_ID}
    ):
        independent_scored.add("shared_terrain_evidence")
    return {
        "score": overall,
        "prototype_similarity": overall,
        "observed_similarity": observed_overall,
        "evidence_coverage": evidence_coverage_numerator / total_denominator
        if total_denominator
        else 0.0,
        "source_context_coverage": source_context_numerator / total_denominator
        if total_denominator
        else 0.0,
        "measured_weight_coverage": measured_weight_numerator / total_denominator
        if total_denominator
        else 0.0,
        "estimated_weight_coverage": estimated_weight_numerator / total_denominator
        if total_denominator
        else 0.0,
        "simulated_weight_coverage": simulated_weight_numerator / total_denominator
        if total_denominator
        else 0.0,
        "dimension_scores": rows,
        "missing_dimensions": [],
        "missing_evidence_dimensions": missing_evidence,
        "estimated_dimensions": [row["id"] for row in rows if row["score_origin"] == "estimated"],
        "simulated_dimensions": [
            row["id"] for row in rows if row["score_origin"] == "simulated"
        ],
        "independent_evidence_groups": sorted(independent_scored),
        "evidence_class": "prototype_multi_source"
        if len(independent_scored) > 1
        else "prototype_observed_subset"
        if observed_overall is not None
        else "prototype_estimated",
    }
