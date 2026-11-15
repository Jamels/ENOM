"""Ingest bounded NASA MOLA terrain windows for Mars catalogue targets."""

from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .ingest_mola import ingest
else:
    from ingest_mola import ingest

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    catalogue = json.loads((ROOT / "data/manifests/candidate-locations.json").read_text())
    targets = [row for row in catalogue["entries"] if row["body"] == "mars"]
    completed = []
    for target in targets:
        slug = target["id"].replace("-", "_")
        output = ROOT / "data/terrain" / f"mola-candidate-{slug}.tif"
        metadata = ingest(
            target["id"],
            output,
            longitude_east_deg=float(target["longitude_east_deg"]),
            latitude_deg=float(target["latitude_deg"]),
            place_name=str(target["name"]),
        )
        completed.append(
            {"site": target["id"], "observed_fraction": metadata["observed_cell_fraction"]}
        )
    print(json.dumps(completed, indent=2))


if __name__ == "__main__":
    main()
