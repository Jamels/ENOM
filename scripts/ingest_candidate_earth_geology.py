"""Query USGS State Geologic Map Compilation at Earth catalogue candidates.

This is regional map context, not a field sample or a globally consistent
geologic classification. Places outside the service extent are retained as
explicit coverage gaps.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/geology"
SERVICE_URL = (
    "https://services1.arcgis.com/gGHDlz6USftL5Pau/ArcGIS/rest/services/"
    "StaticSnapshotForMobile_GeologyUSGS/FeatureServer/1/query"
)
DATASET_ID = "usgs-earth-sgmc"
DOI_URL = "https://doi.org/10.5066/F7WH2N65"
SERVICE_RECORD_URL = (
    "https://services1.arcgis.com/gGHDlz6USftL5Pau/ArcGIS/rest/services/"
    "StaticSnapshotForMobile_GeologyUSGS/FeatureServer/1"
)
FIELDS = (
    "UNIT_NAME,SGMC_LABEL,GENERALIZED_LITH,AGE_MIN,AGE_MAX,MAJOR1,MAJOR2,MAJOR3,"
    "REFERENCE,NGMDB1,NGMDB2,NGMDB3,DIGITAL_URL,STATE"
)
CONUS_EXTENT = (-126.489840313, 24.276909189, -66.742744918, 49.384518964)


def _normalize_feature(attributes: dict[str, Any]) -> dict[str, Any]:
    reference = attributes.get("REFERENCE")
    scale_match = re.search(r"scale\s+(1:\s*[\d,]+)", reference or "", re.IGNORECASE)
    materials = [attributes[key] for key in ("MAJOR1", "MAJOR2", "MAJOR3") if attributes.get(key)]
    return {
        "map_unit_code": attributes.get("SGMC_LABEL"),
        "map_unit_name": attributes.get("UNIT_NAME"),
        "map_unit_interpretation": attributes.get("GENERALIZED_LITH"),
        "map_unit_age_min": attributes.get("AGE_MIN"),
        "map_unit_age_max": attributes.get("AGE_MAX"),
        "major_materials": materials,
        "state": attributes.get("STATE"),
        "reference": reference,
        "nominal_cartographic_scale": scale_match.group(1).replace(" ", "")
        if scale_match
        else None,
        "ngmdb_urls": [
            attributes.get(key) for key in ("NGMDB1", "NGMDB2", "NGMDB3") if attributes.get(key)
        ],
        "digital_data_url": attributes.get("DIGITAL_URL"),
    }


def query_point(site: dict[str, Any], *, session: requests.Session | None = None) -> dict[str, Any]:
    longitude = float(site["longitude_east_deg"])
    longitude = longitude - 360 if longitude > 180 else longitude
    latitude = float(site["latitude_deg"])
    client = session or requests.Session()
    response = client.get(
        SERVICE_URL,
        params={
            "f": "json",
            "geometry": f"{longitude},{latitude}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": FIELDS,
            "returnGeometry": "false",
            "resultRecordCount": "5",
        },
        timeout=30,
        headers={"User-Agent": "ENOM candidate geology evidence/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"USGS SGMC query failed: {payload['error']}")
    features = [
        _normalize_feature(row.get("attributes", {})) for row in payload.get("features", [])
    ]
    in_extent = (
        CONUS_EXTENT[0] <= longitude <= CONUS_EXTENT[2]
        and CONUS_EXTENT[1] <= latitude <= CONUS_EXTENT[3]
    )
    if len(features) == 1:
        status = "mapped"
    elif len(features) > 1:
        status = "boundary_ambiguous"
    else:
        status = "unmapped" if in_extent else "outside_map_extent"
    return {
        "observation_id": site["id"],
        "place_id": site["id"],
        "body": "earth",
        "name": site["name"],
        "longitude_east_deg": float(site["longitude_east_deg"]),
        "latitude_deg": latitude,
        "dataset_id": DATASET_ID,
        "provider": "U.S. Geological Survey Mineral Resources Program / State Geological Surveys",
        "source_product_id": "State Geologic Map Compilation (SGMC), conterminous United States",
        "source_url": SERVICE_URL,
        "dataset_reference_url": DOI_URL,
        "record_url": SERVICE_RECORD_URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "map_layer": "S_USA.Geol_Geology_USA_USGS_PL",
        "classification_status": status,
        "map_unit_code": features[0]["map_unit_code"] if status == "mapped" else None,
        "map_unit_name": features[0]["map_unit_name"] if status == "mapped" else None,
        "map_unit_interpretation": features[0]["map_unit_interpretation"]
        if status == "mapped"
        else None,
        "map_unit_age_min": features[0]["map_unit_age_min"] if status == "mapped" else None,
        "map_unit_age_max": features[0]["map_unit_age_max"] if status == "mapped" else None,
        "major_materials": features[0]["major_materials"] if status == "mapped" else [],
        "state": features[0]["state"] if status == "mapped" else None,
        "nominal_cartographic_scale": features[0]["nominal_cartographic_scale"]
        if status == "mapped"
        else None,
        "reference": features[0]["reference"] if status == "mapped" else None,
        "ngmdb_urls": features[0]["ngmdb_urls"] if status == "mapped" else [],
        "digital_data_url": features[0]["digital_data_url"] if status == "mapped" else None,
        "candidate_units": features if status == "boundary_ambiguous" else [],
        "coordinate_reference_system": "WGS 84 query coordinates; source layer NAD83 (EPSG:4269)",
        "nominal_coverage": (
            "Conterminous United States only; component map scales and "
            "state-unit classifications vary."
        ),
        "source_description": (
            "USGS SGMC regional map synthesis compiled from state maps "
            "(approximately 1:50,000–1:1,000,000). Units are not fully "
            "reconciled across state boundaries and do not describe a local "
            "sample or engineering property."
        ),
        "scorecard_role": "geology_context_only; excluded from similarity scoring",
    }


def ingest(*, session: requests.Session | None = None) -> list[dict[str, Any]]:
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    sites = [row for row in catalogue["entries"] if row["body"] == "earth"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    written = []
    for site in sites:
        row = query_point(site, session=client)
        path = OUTPUT / f"usgs-candidate-earth-{site['id']}.json"
        pending = path.with_suffix(".json.part")
        pending.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        pending.replace(path)
        written.append(row)
    return written


if __name__ == "__main__":
    rows = ingest()
    summary = {
        "indexed": len(rows),
        "mapped": sum(row["classification_status"] == "mapped" for row in rows),
        "outside_map_extent": sum(
            row["classification_status"] == "outside_map_extent" for row in rows
        ),
    }
    print(json.dumps(summary, indent=2))
