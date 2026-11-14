"""Ingest bounded LOLA cylindrical terrain windows for non-polar Moon candidates."""

from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .ingest_lola_scorecard import ingest
else:
    from ingest_lola_scorecard import ingest

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    catalogue = json.loads((ROOT / "data/manifests/candidate-locations.json").read_text())
    targets = [
        row for row in catalogue["entries"]
        if row["body"] == "moon" and abs(float(row["latitude_deg"])) <= 75
    ]
    outcomes = []
    for target in targets:
        slug = target["id"].replace("-", "_")
        try:
            metadata = ingest(
                float(target["longitude_east_deg"]), float(target["latitude_deg"]),
                output_id="moon_candidate_" + slug,
                place_name=str(target["name"]),
                place_id=str(target["id"]),
            )
            outcomes.append({"site": target["id"], "status": "available", "valid_fraction": metadata["valid_pixel_fraction"]})
        except Exception as error:
            outcomes.append({"site": target["id"], "status": "unavailable", "reason": str(error)})
    print(json.dumps(outcomes, indent=2))


if __name__ == "__main__":
    main()
