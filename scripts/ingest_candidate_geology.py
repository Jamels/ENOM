"""Attach USGS regional geology context to the Moon/Mars candidate catalogue."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import shapefile

if __package__:
    from .ingest_lunar_geology import _layer_metadata, classify_site
    from .ingest_mars_geology import (
        ARCHIVE_CACHE,
        ARCHIVE_URL,
        DOI_URL,
        RECORD_URL,
        load_geounits,
        mapped_unit_at,
        normalize_east_longitude,
    )
    from .ingest_mars_geology import (
        PRODUCT_ID as MARS_PRODUCT_ID,
    )
else:
    from ingest_lunar_geology import _layer_metadata, classify_site
    from ingest_mars_geology import (
        ARCHIVE_CACHE,
        ARCHIVE_URL,
        DOI_URL,
        RECORD_URL,
        load_geounits,
        mapped_unit_at,
        normalize_east_longitude,
    )
    from ingest_mars_geology import (
        PRODUCT_ID as MARS_PRODUCT_ID,
    )

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/geology"


def ingest(reader: shapefile.Reader | None = None) -> list[dict[str, object]]:
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    targets = [item for item in catalogue["entries"] if item["body"] in {"moon", "mars"}]
    moon_layer = _layer_metadata() if any(item["body"] == "moon" for item in targets) else None
    mars_reader = reader or load_geounits(ARCHIVE_CACHE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    written = []
    for target in targets:
        if target["body"] == "moon":
            result = classify_site(target["id"], target, moon_layer)
            result["place_id"] = target["id"]
            output_path = OUTPUT / f"usgs-candidate-moon-{target['id']}.json"
        else:
            longitude = float(target["longitude_east_deg"])
            latitude = float(target["latitude_deg"])
            status, unit = mapped_unit_at(mars_reader, longitude, latitude)
            result = {
                "observation_id": target["id"],
                "body": "mars",
                "name": target["name"],
                "place_id": target["id"],
                "longitude_east_deg": longitude % 360,
                "longitude_layer_deg": normalize_east_longitude(longitude),
                "latitude_deg": latitude,
                "dataset_id": "usgs-sim-1083-mars-global-geology",
                "provider": "U.S. Geological Survey Astrogeology Science Center",
                "source_product_id": MARS_PRODUCT_ID,
                "source_url": ARCHIVE_URL,
                "dataset_reference_url": DOI_URL,
                "record_url": RECORD_URL,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "map_layer": "I1083_GeoUnits",
                "map_unit_code": unit,
                "classification_status": status,
                "coordinate_reference_system": "Mars_2000_Sphere geographic; 3,396,190 m radius",
                "nominal_cartographic_scale": (
                    "1:25,000,000 from 65°S to 65°N; approximately 1:5,000,000 poleward of 60°"
                ),
                "source_description": (
                    "Regional mapped interpretation from USGS SIM 1083; not a local material assay."
                ),
                "scorecard_role": "geology_context_only; excluded from similarity scoring",
            }
            output_path = OUTPUT / f"usgs-candidate-mars-{target['id']}.json"
        temporary = output_path.with_suffix(".json.part")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_path)
        written.append(result)
    return written


if __name__ == "__main__":
    rows = ingest()
    print(f"Indexed USGS geology context for {len(rows)} Moon/Mars candidate places.")
