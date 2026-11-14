"""Ingest Jezero rover-localization context from the NASA PDS PLACES bundle."""

from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi

from twinworld import mars2020_places

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/mars2020-jezero-rover-places.json"
CSV_URL = (
    "https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-"
    "mars2020_rover_places/data_localizations/best_tactical.csv"
)
RELEASE_URL = "https://pds-geosciences.wustl.edu/missions/mars2020/places.htm"
SEARCH_RADIUS_KM = 20.0


def main() -> None:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]
    site = next(item for item in entries if item["id"] == "mars-jezero")
    request = urllib.request.Request(CSV_URL, headers={"User-Agent": "ENOM-science-data/1.0"})
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=60, context=tls_context) as response:
        csv_text = response.read().decode("utf-8")
    points = mars2020_places.parse_best_tactical_csv(
        csv_text,
        float(site["latitude_deg"]),
        float(site["longitude_east_deg"]),
        SEARCH_RADIUS_KM,
    )
    if not points:
        raise RuntimeError("No rover drive localizations were found near the Jezero candidate")
    records = [{
        "observation_id": f"mars-jezero:PLACES:site-{point['site']}:drive-{point['drive']}:pose-{point['pose']}",
        "place_id": "mars-jezero",
        "dataset_id": mars2020_places.DATASET_ID,
        **point,
    } for point in points]
    payload = {
        "dataset_id": mars2020_places.DATASET_ID,
        "product_id": "best_tactical.csv",
        "provider": "NASA Mars 2020 Rover PLACES / PDS Geosciences Node",
        "source_url": CSV_URL,
        "release_url": RELEASE_URL,
        "release": 16,
        "release_date": "2026-08-11",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "place_id": "mars-jezero",
        "body": "mars",
        "candidate_latitude_deg": site["latitude_deg"],
        "candidate_longitude_east_deg": site["longitude_east_deg"],
        "candidate_region_radius_km": SEARCH_RADIUS_KM,
        "coordinate_system": "planetocentric latitude, east-positive longitude; Mars radius 3396.19 km for distance",
        "position_uncertainty": "The table supplies localized coordinates but no per-position uncertainty field in this ENOM ingest.",
        "known_source_gap": (
            "PDS Release 16 notes that ROVER,n,0 entries are absent from best_tactical.csv; "
            "those positions are represented by SITE rows, so ENOM's drive-position subset does not include them."
        ),
        "interpretation_limit": (
            "Positions are selected best-tactical rover localizations associated with drive records. "
            "They are discrete location fixes, not a continuous wheel path, odometry track, hazard assessment, or vehicle-suitability result. "
            "Release 16 omits ROVER,n,0 fixes from this table, leaving a gap at those drive starts."
        ),
        "use_limit": (
            "Positions are selected best-tactical rover localizations associated with drive records. "
            "They are discrete location fixes, not a continuous wheel path, odometry track, hazard assessment, or vehicle-suitability result. "
            "Release 16 omits ROVER,n,0 fixes from this table, leaving a gap at those drive starts."
        ),
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} Jezero-area rover position fixes to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
