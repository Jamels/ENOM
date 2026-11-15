"""Read only ALDS south-polar map-cell records at ENOM's lunar candidates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from twinworld import lend

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/lro-lend-south-polar-alds.json"


def main() -> None:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]
    sites = [
        item
        for item in entries
        if item.get("body") == "moon" and item.get("candidate_type") == "lunar_south_polar"
    ]
    records = []
    for site in sites:
        for product in lend.ALDS_PRODUCTS:
            sample = lend.read_alds_cell(
                float(site["longitude_east_deg"]), float(site["latitude_deg"]), product
            )
            records.append(
                {
                    "observation_id": f"{site['id']}:{sample['product_id']}",
                    "place_id": site["id"],
                    "dataset_id": lend.DATASET_ID,
                    "product_id": sample["product_id"],
                    "provider": "NASA LRO LEND / PDS Geosciences Node",
                    "source_url": sample["source_url"],
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "body": "moon",
                    "latitude_deg": sample["grid_cell"]["latitude_deg"],
                    "longitude_east_deg": sample["grid_cell"]["longitude_east_deg"],
                    "candidate_latitude_deg": site["latitude_deg"],
                    "candidate_longitude_east_deg": site["longitude_east_deg"],
                    "location_precision": "0.5_degree_south_polar_grid_cell",
                    "grid_spacing_deg": sample["grid_spacing_deg"],
                    "record_index": sample["record_index"],
                    "exposure_field_value": sample["exposure_field_value"],
                    "observation_period": sample["temporal_coverage"],
                    "retrieval_method": (
                        "HTTP byte-range read of the one 310-byte PDS record for this grid cell"
                    ),
                    "evidence_kind": "measured_remote_sensing",
                    "measurement": {
                        "name": sample["measurement_name"],
                        "value": sample["value"],
                        "units": sample["units"],
                        "availability": sample["availability"],
                        "summary_statistic": (
                            "Cumulative normalized rate for the ALDS grid cell over the product "
                            "period"
                        ),
                        "spatial_grid_spacing_deg": sample["grid_spacing_deg"],
                        "uncertainty": {
                            "description": "PDS CSETN_ERR statistical error",
                            "value": sample["statistical_error"],
                            "units": sample["units"],
                        }
                        if sample["statistical_error"] is not None
                        else sample["uncertainty"],
                    },
                    "interpretation": sample["interpretation"],
                    "uncertainty": sample["uncertainty"],
                    "use_limit": (
                        "Indirect neutron context only. Does not identify water-ice "
                        "concentration or prove accessible/extractable resources; excluded "
                        "from analogue scores and mission suitability."
                    ),
                }
            )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "dataset_id": lend.DATASET_ID,
                "instrument": "LRO Lunar Exploration Neutron Detector (LEND)",
                "source_url": "https://pds-geosciences.wustl.edu/missions/lro/lend.htm",
                "products": list(lend.ALDS_PRODUCTS),
                "retrieval_method": (
                    "Six 310-byte rows read by HTTP byte ranges; full archive tables not downloaded"
                ),
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} LEND place/product records to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
