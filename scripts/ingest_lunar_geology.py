"""Retrieve bounded lunar map-unit context for indexed Moon scorecard sites.

The source is the USGS Unified Geologic Map of the Moon (1:5M), served as a
public ArcGIS feature layer. Point classifications are categorical context,
not engineering properties or terrain-score inputs.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
TERRAIN_DIR = ROOT / "data/terrain"
OUTPUT_DIR = ROOT / "data/geology"
SERVICE_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/ArcGIS/rest/services/"
    "Features_Fortezzo_et_al_2020_Unified_Map_of_the_Moon/FeatureServer"
)
LAYER_ID = 7
QUERY_URL = f"{SERVICE_URL}/{LAYER_ID}/query"
PRODUCT_URL = (
    "https://astrogeology.usgs.gov/search/map/Moon/Geology/"
    "Unified_Geologic_Map_of_the_Moon_GIS_v2/"
)
DATASET_ID = "usgs-fortezzo-2020-unified-lunar-geology"
PRODUCT_ID = "Fortezzo et al. (2020) Unified Geologic Map of the Moon / GeoUnits_Mercator"
MOON_RADIUS_M = 1_737_400.0
TIMEOUT = (10, 40)
FIELDS = "FIRST_UnitSymbol,FIRST_UnitAge,FIRST_UnitName,Description,Interpretation"


def normalize_east_longitude(longitude_deg: float) -> float:
    """Wrap east-positive Moon longitude into the service's [-180, 180) range."""
    if not math.isfinite(longitude_deg) or not -360.0 <= longitude_deg <= 360.0:
        raise ValueError("Lunar east longitude must be finite and in [-360, 360]")
    value = (longitude_deg + 180.0) % 360.0 - 180.0
    return value


def mercator_point(longitude_east_deg: float, latitude_deg: float) -> tuple[float, float]:
    """Project Moon_2000 longitude/latitude into the service's spherical Mercator."""
    if not math.isfinite(latitude_deg) or not -90.0 < latitude_deg < 90.0:
        raise ValueError("Lunar latitude must be finite and strictly between -90 and 90")
    longitude = normalize_east_longitude(longitude_east_deg)
    latitude_rad = math.radians(latitude_deg)
    x = MOON_RADIUS_M * math.radians(longitude)
    y = MOON_RADIUS_M * math.log(math.tan(math.pi / 4.0 + latitude_rad / 2.0))
    return x, y


def _get_json(url: str, params: dict[str, object] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("USGS lunar map service returned a non-object response")
    if "error" in payload:
        raise RuntimeError(f"USGS lunar map service error: {payload['error']}")
    return payload


def _layer_metadata() -> dict[str, Any]:
    layer = _get_json(f"{SERVICE_URL}/{LAYER_ID}", {"f": "json"})
    field_names = {field.get("name") for field in layer.get("fields", [])}
    if not set(FIELDS.split(",")).issubset(field_names):
        raise RuntimeError("USGS lunar GeoUnits layer is missing expected unit attributes")
    spatial_reference = layer.get("extent", {}).get("spatialReference", {})
    wkt = spatial_reference.get("wkt", "")
    if 'GCS_Moon_2000' not in wkt or '"Moon_2000_IAU_IAG",1737400.0' not in wkt:
        raise RuntimeError("USGS lunar GeoUnits layer CRS is not the expected Moon_2000 sphere")
    extent = layer.get("extent")
    if not isinstance(extent, dict):
        raise RuntimeError("USGS lunar GeoUnits layer has no valid projected extent")
    return {"extent": extent, "spatial_reference": spatial_reference}


def _site_sidecars() -> dict[str, dict[str, Any]]:
    sites: dict[str, dict[str, Any]] = {}
    for path in sorted(TERRAIN_DIR.glob("*.tif.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("body") != "moon" or metadata.get("dataset_id") != "lro-lola-gdr-ldem-64":
            continue
        observation_id = metadata.get("observation_id")
        if observation_id:
            sites[str(observation_id)] = metadata
    return sites


def classify_site(
    observation_id: str,
    metadata: dict[str, Any],
    layer: dict[str, Any],
    *,
    session: Any = requests,
) -> dict[str, Any]:
    longitude = float(metadata["longitude_east_deg"])
    latitude = float(metadata["latitude_deg"])
    x, y = mercator_point(longitude, latitude)
    extent = layer["extent"]
    inside_layer_extent = (
        float(extent["xmin"]) <= x <= float(extent["xmax"])
        and float(extent["ymin"]) <= y <= float(extent["ymax"])
    )
    attributes: list[dict[str, Any]] = []
    if inside_layer_extent:
        response = session.get(
            QUERY_URL,
            params={
                "f": "json",
                "geometry": json.dumps({"x": x, "y": y}, separators=(",", ":")),
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": FIELDS,
                "returnGeometry": "false",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise RuntimeError(f"USGS lunar map query error: {result['error']}")
        attributes = [
            item.get("attributes", {})
            for item in result.get("features", [])
            if isinstance(item.get("attributes"), dict)
        ]

    by_code = {
        str(item.get("FIRST_UnitSymbol")): item
        for item in attributes
        if item.get("FIRST_UnitSymbol") not in (None, "")
    }
    if not inside_layer_extent:
        status = "outside_map_extent"
    elif len(by_code) == 1:
        status = "mapped"
    elif len(by_code) > 1:
        status = "boundary_ambiguous"
    else:
        status = "unmapped"
    unit = next(iter(by_code.values())) if status == "mapped" else {}
    return {
        "observation_id": observation_id,
        "body": "moon",
        "name": metadata.get("name", observation_id),
        "longitude_east_deg": longitude,
        "longitude_layer_deg": normalize_east_longitude(longitude),
        "latitude_deg": latitude,
        "dataset_id": DATASET_ID,
        "provider": "U.S. Geological Survey Astrogeology Science Center",
        "source_product_id": PRODUCT_ID,
        "source_url": QUERY_URL,
        "dataset_reference_url": PRODUCT_URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "map_unit_code": unit.get("FIRST_UnitSymbol"),
        "map_unit_name": unit.get("FIRST_UnitName"),
        "map_unit_age": unit.get("FIRST_UnitAge"),
        "map_unit_description": unit.get("Description"),
        "map_unit_interpretation": unit.get("Interpretation"),
        "candidate_unit_codes": sorted(by_code),
        "classification_status": status,
        "nominal_cartographic_scale": "1:5,000,000 global map; regional-unit generalization",
        "coordinate_reference_system": (
            "Moon_2000 geographic projected to spherical Mercator; R=1,737,400 m; "
            "central meridian 0°"
        ),
        "service_layer_extent": {key: extent[key] for key in ("xmin", "ymin", "xmax", "ymax")},
        "source_description": (
            "The USGS unified map aggregates 49 lunar geologic units from six regional maps. "
            "Mapped interpretation is regional context at 1:5M scale, not a local assay, "
            "mineral detection, regolith composition measurement, or engineering property."
        ),
        "source_attribution": (
            "USGS Astrogeology Science Center; Fortezzo, Spudis, and Harrel (2020)"
        ),
        "usage_note": (
            "The public feature service exposes no explicit licence field; preserve USGS and "
            "map-author attribution and consult the product page for reuse terms."
        ),
        "scorecard_role": (
            "geology_context_only; excluded from terrain ranking and mission screening"
        ),
    }


def ingest_sites(
    observation_ids: list[str] | None = None,
    *,
    output_dir: Path = OUTPUT_DIR,
    session: Any = requests,
) -> list[dict[str, Any]]:
    sites = _site_sidecars()
    selected_ids = observation_ids or sorted(sites)
    missing = set(selected_ids) - sites.keys()
    if missing:
        raise ValueError(f"No LOLA scorecard site metadata for: {', '.join(sorted(missing))}")
    layer = _layer_metadata() if selected_ids else None
    results = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for observation_id in selected_ids:
        result = classify_site(observation_id, sites[observation_id], layer, session=session)
        target = output_dir / f"usgs-unified-moon-{observation_id}.json"
        temporary = target.with_suffix(".json.part")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", action="append", dest="observation_ids")
    args = parser.parse_args()
    print(json.dumps(ingest_sites(args.observation_ids), indent=2))


if __name__ == "__main__":
    main()
