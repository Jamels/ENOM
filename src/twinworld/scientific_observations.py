"""Read and normalize locally indexed, source-backed dimension observations.

This adapter deliberately does not score evidence. It links records only by an
explicit ``place_id`` or a source record's exact observation ID, preserves the
original provenance, and leaves unsupported dimensions empty.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

DIMENSION_IDS = (
    "geology_materials",
    "terrain",
    "thermal_illumination",
    "water_resources",
    "dust_processes",
    "biology_habitability",
    "subsurface",
    "mission_operations",
)

_ENVIRONMENT_DIMENSIONS = {
    "nasa-power-climatology": {
        "T2M": "thermal_illumination",
        "ALLSKY_SFC_SW_DWN": "thermal_illumination",
        "WS10M": "dust_processes",
        "RH2M": "water_resources",
    },
    "era5-earth-candidate-climatology": {
        "ERA5 monthly mean 2 m air temperature": "thermal_illumination",
        "ERA5 monthly mean 10 m wind speed": "dust_processes",
        "ERA5 average monthly precipitation total": "water_resources",
    },
    "mars2020-meda": {
        "thermal_illumination": "thermal_illumination",
        "dust_processes": "dust_processes",
        "water_resources": "water_resources",
    },
    "lro-diviner-south-polar-prp": {
        "lro-diviner-south-polar-prp": "thermal_illumination",
    },
    "lro-mini-rf-south-polar-cpr": {
        "lro-mini-rf-south-polar-cpr": "water_resources",
        "lro-mini-rf-south-polar-cpr:subsurface": "subsurface",
    },
    "lro-lend-south-polar-alds": {
        "lro-lend-south-polar-alds": "water_resources",
    },
    "earth-extremophile-studies": {
        "biology_habitability": "biology_habitability",
        "water_resources": "water_resources",
    },
}

# Coarse label crosswalk for *map interpretations*, not raw map-unit codes.
# Version and resulting groups remain visible to the experimental comparator.
MATERIAL_CROSSWALK_VERSION = "enom-broad-material-v1"
_MATERIAL_GROUPS = {
    "basalt": "mafic_volcanic",
    "basanite": "mafic_volcanic",
    "basaltic lava flows": "mafic_volcanic",
    "andesite": "intermediate_volcanic",
    "dacite": "intermediate_volcanic",
    "carbonate": "carbonate_sedimentary",
}


def empty_dimensions() -> dict[str, list[dict[str, Any]]]:
    """Return all stable dimensions, including those with no evidence."""
    return {dimension_id: [] for dimension_id in DIMENSION_IDS}


def dimension_inputs(
    root: Path,
    place_id: str,
    *,
    observations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build scorer inputs from exact-place local observations and sidecars.

    ``observations`` may be supplied from an already indexed place. Otherwise,
    compact JSON records are read from ``data/environment``, ``data/terrain``
    and ``data/geology``. No coordinate-nearest matching or network access is
    performed. Terrain's five established metrics are carried through with
    their native units, feature scales, and observation support.
    """
    result = empty_dimensions()
    rows = list(observations) if observations is not None else _local_observations(root, place_id)
    for observation in rows:
        if observation.get("place_id") != place_id:
            continue
        result.update(_add_observation(result, observation))
    return result


def _add_observation(
    target: dict[str, list[dict[str, Any]]], observation: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    dataset_id = str(observation.get("dataset_id") or "")
    raw_metadata = observation.get("metadata")
    metadata: Mapping[str, Any] = (
        raw_metadata if isinstance(raw_metadata, Mapping) else observation
    )
    dimensions = _dimensions_for(observation, metadata)
    measures = observation.get("measurements") or observation.get("measurement")
    if measures is None and "value" in observation:
        # The local Mini-RF and some point-product records store one measure
        # directly on the observation rather than under a measurements array.
        measures = [
            {
                "name": observation.get("measurement_name") or observation.get("name"),
                "value": observation.get("value"),
                "units": observation.get("units"),
                "availability": observation.get("availability", "available"),
                "spatial_scale_m": observation.get("spatial_scale_m"),
                "uncertainty": observation.get("uncertainty"),
            }
        ]
    if isinstance(measures, Mapping):
        measures = [measures]
    if not isinstance(measures, list):
        measures = []
    for dimension_id in dimensions:
        for measure in measures:
            if not isinstance(measure, Mapping):
                continue
            measurement_dimension = _ENVIRONMENT_DIMENSIONS.get(dataset_id, {}).get(
                str(measure.get("name"))
            )
            if measurement_dimension is not None and measurement_dimension != dimension_id:
                continue
            row = dict(measure)
            row.update(
                {
                    "dimension_id": dimension_id,
                    "observation_id": observation.get("observation_id") or observation.get("id"),
                    "dataset_id": dataset_id or None,
                    "product_id": observation.get("product_id")
                    or observation.get("source_product_id"),
                    "source_url": observation.get("source_url"),
                    "provider": observation.get("provider"),
                    "evidence_kind": observation.get("evidence_kind")
                    or metadata.get("evidence_kind")
                    or observation.get("kind"),
                    "temporal_coverage": observation.get("temporal_coverage")
                    or observation.get("observation_period")
                    or observation.get("acquired_at"),
                    "spatial_coverage": observation.get("spatial_coverage")
                    or metadata.get("spatial_coverage"),
                    "methodology": observation.get("processing_method")
                    or metadata.get("processing_method")
                    or metadata.get("retrieval_method"),
                    "use_limit": observation.get("use_limit") or metadata.get("use_limit"),
                }
            )
            row.setdefault(
                "availability", "available" if row.get("value") is not None else "not_observed"
            )
            if row.get("spatial_scale_m") is None:
                row["spatial_scale_m"] = metadata.get("spatial_scale_m") or metadata.get(
                    "context_size_m"
                )
            if row.get("uncertainty") is None:
                row["uncertainty"] = observation.get("uncertainty") or metadata.get("uncertainty")
            target[dimension_id].append(row)
    # Preserve map-unit records as interpreted evidence; codes remain strings
    # and are never converted to numeric scores by this adapter.
    if observation.get("map_unit_code") is not None or observation.get("classification_status"):
        source_labels = list(observation.get("major_materials") or [])
        source_labels.extend(
            value
            for value in (
                observation.get("map_unit_interpretation"),
                observation.get("map_unit_description"),
            )
            if value
        )
        material_groups = _material_groups(source_labels)
        target["geology_materials"].append(
            {
                "dimension_id": "geology_materials",
                "observation_id": observation.get("observation_id") or observation.get("id"),
                "dataset_id": dataset_id or None,
                "product_id": observation.get("product_id") or observation.get("source_product_id"),
                "source_url": observation.get("source_url"),
                "value": None,
                "availability": observation.get("classification_status", "not_observed"),
                "evidence_kind": "interpreted_map_unit",
                "map_unit_code": observation.get("map_unit_code"),
                "map_unit_name": observation.get("map_unit_name"),
                "map_unit_interpretation": observation.get("map_unit_interpretation"),
                "major_materials": observation.get("major_materials", []),
                "material_groups": material_groups,
                "material_crosswalk_version": MATERIAL_CROSSWALK_VERSION,
                "normalization_status": (
                    "normalized" if material_groups else "no_supported_material_label"
                ),
                "spatial_scale_m": None,
                "nominal_cartographic_scale": metadata.get("nominal_cartographic_scale"),
                "uncertainty": metadata.get("source_description") or metadata.get("uncertainty"),
                "methodology": (
                    "Experimental explicit-label crosswalk to broad mapped material groups; "
                    "comparator may calculate set Jaccard only for mapped known labels."
                ),
                "use_limit": metadata.get("scorecard_role")
                or "Map interpretation; not a material assay.",
            }
        )
    for dimension_id in observation.get("context_dimensions", []):
        if dimension_id in DIMENSION_IDS:
            target[dimension_id].append(
                {
                    "dimension_id": dimension_id,
                    "observation_id": observation.get("observation_id") or observation.get("id"),
                    "dataset_id": dataset_id or None,
                    "source_url": observation.get("source_url"),
                    "value": None,
                    "availability": "context_only",
                    "evidence_kind": "catalogue_interpretation",
                    "summary": observation.get("summary"),
                    "uncertainty": observation.get("uncertainty"),
                    "use_limit": observation.get("use_limit"),
                }
            )
    return target


def _material_groups(labels: list[Any]) -> list[str]:
    groups = {
        _MATERIAL_GROUPS[str(label).strip().casefold()]
        for label in labels
        if str(label).strip().casefold() in _MATERIAL_GROUPS
    }
    return sorted(groups)


def _dimensions_for(observation: Mapping[str, Any], metadata: Mapping[str, Any]) -> list[str]:
    dataset_id = str(observation.get("dataset_id") or "")
    result: set[str] = set()
    declared = metadata.get("dimensions")
    if isinstance(declared, list):
        result.update(item for item in declared if item in DIMENSION_IDS)
    direct_mapping = _ENVIRONMENT_DIMENSIONS.get(dataset_id, {})
    if dataset_id == "mars2020-meda":
        result.update(item for item in declared or [] if item in direct_mapping)
    else:
        measurements = observation.get("measurements") or observation.get("measurement") or []
        if isinstance(measurements, Mapping):
            measurements = [measurements]
        for row in measurements if isinstance(measurements, list) else []:
            if isinstance(row, Mapping) and row.get("name") in direct_mapping:
                result.add(direct_mapping[row["name"]])
        if dataset_id in {"lro-diviner-south-polar-prp", "lro-lend-south-polar-alds"}:
            result.add(direct_mapping[dataset_id])
        if dataset_id == "lro-mini-rf-south-polar-cpr":
            result.add("water_resources")
    # Established DEM features feed terrain; when reused for operations the
    # scorer must account for their shared evidence budget.
    if dataset_id in {
        "cop-dem-glo-30",
        "nasadem-hgt",
        "mola-meg128",
        "lro-lola-gdr-ldem-64",
        "lro-lola-gdr-polar-ldem-120m",
    }:
        result.update(("terrain", "mission_operations"))
    return sorted(result)


def observation_identity(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint compact observation files so cached evidence follows edits."""
    paths = [root / "data/manifests/candidate-locations.json"]
    for directory in ("environment", "terrain", "geology"):
        paths.extend(sorted((root / "data" / directory).glob("*.json")))
    return tuple(
        (str(path), path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths if path.is_file()
    )


def local_observation_catalogue(root: Path) -> dict[str, list[dict[str, Any]]]:
    return _observation_catalogue(observation_identity(root))


@lru_cache(maxsize=4)
def _observation_catalogue(
    identity: tuple[tuple[str, int, int], ...],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for filename, _size, _mtime in identity:
        path = Path(filename)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        rows = payload.get("records", [payload])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            # Preserve parent product provenance for nested records.
            record = {key: value for key, value in payload.items() if key != "records"}
            record.update(row)
            place_id = record.get("place_id") or record.get("observation_id")
            if not isinstance(place_id, str):
                continue
            record["place_id"] = place_id
            result.setdefault(place_id, []).append(record)
    return result


def _local_observations(root: Path, place_id: str) -> list[dict[str, Any]]:
    return local_observation_catalogue(root).get(place_id, [])
