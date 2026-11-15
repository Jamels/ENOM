"""Fetch bounded Copernicus windows around the pilot's Earth regions."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from pystac_client import Client

from scripts.ingest_candidate_copdem import STAC_URL, ingest
from twinworld.records import PatchRecord, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "15")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=90)
    args = parser.parse_args()
    groups: dict[str, PatchRecord] = {}
    for row in read_jsonl(ROOT / "data/manifests/pilot-100.jsonl"):
        if row.body == "earth":
            groups.setdefault(row.geographic_group, row)
    output = ROOT / "artifacts/discovery/copernicus"
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    for group, row in sorted(groups.items()):
        cosine = max(0.2, math.cos(math.radians(row.latitude)))
        for lat_step in (-1, 0, 1):
            for lon_step in (-1, 0, 1):
                latitude = row.latitude + lat_step * 0.25
                longitude = (row.longitude + lon_step * 0.25 / cosine) % 360
                if not -80 < latitude < 84:
                    continue
                suffix = f"{lat_step + 1}{lon_step + 1}"
                candidates.append(
                    {
                        "id": f"expanded_{group}_{suffix}",
                        "name": f"{group.replace('_', ' ')} · region {suffix}",
                        "latitude_deg": latitude,
                        "longitude_east_deg": longitude,
                    }
                )
    client = Client.open(STAC_URL)
    completed, failures = [], []
    for site in candidates[: args.limit]:
        try:
            data = ingest(site, client, output_dir=output)
            if float(str(data["valid_pixel_fraction"])) < 0.9:
                failures.append({"site": site["id"], "reason": "insufficient valid cells"})
                continue
            completed.append(str(data["observation_id"]))
        except Exception as error:
            # Avoid exposing signed provider URLs or credentials from exception strings.
            failures.append({"site": site["id"], "reason": type(error).__name__})
        print(
            json.dumps({"completed": len(completed), "failed": len(failures), "site": site["id"]}),
            flush=True,
        )
    manifest = {
        "version": 1,
        "contexts": completed,
        "failures": failures,
        "sampling": "3x3 positions at approximately 0.25 degrees from pilot region centres",
    }
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps({"contexts": len(completed), "failures": failures}, indent=2))


if __name__ == "__main__":
    main()
