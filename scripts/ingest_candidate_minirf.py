"""Retrieve only tiny site-centred sample windows from the PDS Mini-RF CPR map."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from twinworld import minirf

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/lro-mini-rf-south-polar-cpr.json"


def main() -> None:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]
    records = []
    for site in entries:
        if site.get("body") != "moon" or site.get("candidate_type") != "lunar_south_polar":
            continue
        sample = minirf.read_cpr_neighborhood(
            float(site["longitude_east_deg"]), float(site["latitude_deg"])
        )
        records.append({
            "observation_id": f"{site['id']}:mini-rf-cpr",
            "place_id": site["id"],
            "dataset_id": minirf.DATASET_ID,
            "product_id": minirf.PRODUCT_ID,
            "provider": "NASA LRO Mini-RF / PDS Geosciences Node",
            "source_url": minirf.LABEL_URL,
            "image_url": minirf.IMAGE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "body": "moon",
            "latitude_deg": site["latitude_deg"],
            "longitude_east_deg": site["longitude_east_deg"],
            "measurement_name": "Mini-RF circular polarization ratio (CPR)",
            "value": sample["median_cpr"],
            "units": "dimensionless ratio",
            "spatial_scale_m": minirf.PIXEL_SCALE_KM * 1000,
            "spatial_coverage": {
                "location_precision": "candidate_region_centre",
                "context_size_m": 5 * minirf.PIXEL_SCALE_KM * 1000,
                "window_pixels": sample["window_pixels"],
                "valid_pixel_count": sample["valid_pixel_count"],
                "sample_count": sample["sample_count"],
                "grid_column": sample["grid_column"],
                "grid_row": sample["grid_row"],
            },
            "temporal_coverage": "Combined acquisitions from 2009-07-19 through 2011-01-11",
            "measurement_semantics": (
                "Median CPR in a 5×5-pixel neighbourhood from the calibrated combined east- and west-looking mosaic."
            ),
            "evidence_kind": "measured_remote_sensing",
            "interpretation": (
                "Radar backscatter polarization ratio. Elevated CPR can be associated with rough blocky surfaces or volume scattering; it is not a unique water-ice detector."
            ),
            "uncertainty": (
                "Regional map pixel is about 948 m; this local statistic uses a 5×5 neighbourhood. Product is a combined multi-acquisition mosaic; no per-pixel uncertainty is supplied. CPR has non-ice explanations including surface roughness and blockiness."
            ),
            "use_limit": (
                "Context clue only. Does not establish water, ice, concentration, accessibility, or extractable reserves; excluded from similarity scoring and mission-suitability assessment."
            ),
            **sample,
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "dataset_id": minirf.DATASET_ID,
        "product_id": minirf.PRODUCT_ID,
        "source_url": minirf.LABEL_URL,
        "image_url": minirf.IMAGE_URL,
        "retrieval_method": "HTTP byte ranges for 5×5 pixel neighbourhoods only; full mosaic not downloaded",
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} Mini-RF place samples to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
