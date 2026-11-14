"""Read local Diviner PRP cells for ENOM's lunar south-polar candidates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from twinworld import diviner_prp

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/lro-diviner-south-polar-prp.json"


def main() -> None:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]
    sites = [
        item for item in entries
        if item.get("body") == "moon" and item.get("candidate_type") == "lunar_south_polar"
    ]
    records = []
    for site in sites:
        sample = diviner_prp.read_nearest_triangle(
            float(site["latitude_deg"]), float(site["longitude_east_deg"])
        )
        records.append({
            "observation_id": f"{site['id']}:{diviner_prp.DATASET_ID}",
            "place_id": site["id"],
            "dataset_id": diviner_prp.DATASET_ID,
            "product_id": diviner_prp.PRODUCT_ID,
            "provider": "NASA LRO Diviner / PDS Geosciences Node",
            "source_url": diviner_prp.LABEL_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "body": "moon",
            "latitude_deg": sample["latitude_deg"],
            "longitude_east_deg": sample["longitude_east_deg"],
            "candidate_latitude_deg": site["latitude_deg"],
            "candidate_longitude_east_deg": site["longitude_east_deg"],
            "distance_from_candidate_km": sample["distance_from_candidate_km"],
            "record_index": sample["record_index"],
            "location_precision": "nearest_triangular_mesh_centroid",
            "spatial_scale_m": 500.0,
            "context_size_m": 500.0,
            "sample_count": 1,
            "spatial_relation": (
                f"Nearest mesh centroid is {sample['distance_from_candidate_km']:.3f} km from the catalogue place coordinate"
            ),
            "spatial_coverage": {
                "type": "nearest_triangle_centroid",
                "nominal_mesh_spacing_m": 500.0,
                "triangle_count_searched": sample["search_triangle_count"],
                "nearest_centroid_distance_km": sample["distance_from_candidate_km"],
                "note": sample["mesh_resolution_note"],
            },
            "retrieval_method": (
                "Five bounded HTTP byte-range reads around the candidate; each selected the nearest triangle centroid. "
                "The 604 MB global table was not downloaded."
            ),
            "evidence_kind": "model_derived_remote_sensing",
            "observation_period": "Thermal-model fit to Diviner observations from the first mapping year (2009-07-05 through 2010-07-05)",
            "measurements": [
                {
                    "name": "Annual average surface temperature at 2 cm depth",
                    "value": sample["measurements"]["annual_average_surface_temperature_2cm"],
                    "units": "K",
                    "availability": "available",
                    "spatial_scale_m": 500.0,
                    "sample_count": 1,
                    "uncertainty": "The PRP product provides no per-triangle uncertainty value; thermal-model uncertainty is not quantified here.",
                },
                {
                    "name": "Annual maximum surface temperature",
                    "value": sample["measurements"]["annual_maximum_surface_temperature"],
                    "units": "K",
                    "availability": "available",
                    "spatial_scale_m": 500.0,
                    "sample_count": 1,
                    "uncertainty": "The PRP product provides no per-triangle uncertainty value; thermal-model uncertainty is not quantified here.",
                },
                {
                    "name": "Modeled depth to water-ice stability threshold",
                    "value": sample["measurements"]["modeled_ice_stability_depth"],
                    "units": "m",
                    "availability": "available" if sample["measurements"]["modeled_ice_stability_depth"] is not None else "not_reported",
                    "spatial_scale_m": 500.0,
                    "sample_count": 1,
                    "uncertainty": "Model-derived depth threshold, not a detected ice layer. PDS -999 means the depth exceeds the product limit of 2.8738 m.",
                },
            ],
            "interpretation": (
                "Diviner PRP is a thermal-model estimate based on first-year observations. "
                "Ice stability depth is a modeled sublimation threshold, not a direct ice detection or resource measurement."
            ),
            "use_limit": (
                "Lunar environmental context only. No Earth-equivalent measurement is connected; values are not cross-body scored and do not prove accessible or usable water ice."
            ),
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "dataset_id": diviner_prp.DATASET_ID,
        "instrument": "Lunar Reconnaissance Orbiter Diviner",
        "source_url": "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm",
        "product_id": diviner_prp.PRODUCT_ID,
        "retrieval_method": "Nearest-triangle local samples; global PDS table not downloaded",
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} Diviner PRP candidate records to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
