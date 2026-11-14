import json
from pathlib import Path

from twinworld import mars2020_places
from twinworld.analogue import discover, source_inventory
from twinworld.api import dataset_coverage, datasets, place_rover_operations_preview

ROOT = Path(__file__).resolve().parents[1]


def test_parser_keeps_only_valid_rover_drive_positions_in_radius():
    rows = """frame,site,drive,pose,planetocentric_latitude,longitude,elevation,sol
SITE,1,-1,-1,18.44,77.45,-2570,-1
ROVER,3,0,-1,18.44,77.45,-2570,-1
ROVER,3,28,-1,18.4401,77.4501,-2569,13
ROVER,4,70,-1,18.6,77.45,-2570,20
"""
    parsed = mars2020_places.parse_best_tactical_csv(rows, 18.44, 77.45, radius_km=1)
    assert len(parsed) == 1
    assert parsed[0]["drive"] == 28 and parsed[0]["sol"] == 13
    assert parsed[0]["distance_from_candidate_km"] < 1


def test_perseverance_position_evidence_is_visible_but_not_a_suitability_score():
    result = discover(ROOT, "mars-jezero", "mission_operations")
    dimension = next(row for row in result["target_evidence"] if row["id"] == "mission_operations")
    item = next(
        row for row in dimension["evidence_items"]
        if row["dataset_id"] == mars2020_places.DATASET_ID
    )
    assert item["measurements"][0]["value"] == 577
    assert item["measurements"][0]["units"] == "positions"
    assert "not a continuous wheel path" in item["use_limit"]
    assert result["results"]
    assert all(row["mission_suitability"]["status"] == "not_assessed" for row in result["results"])

    payload = json.loads((ROOT / "data/environment/mars2020-jezero-rover-places.json").read_text())
    assert len(payload["records"]) == 577
    assert min(row["sol"] for row in payload["records"]) >= 0
    assert max(row["sol"] for row in payload["records"]) == 1896
    assert all(row["distance_from_candidate_km"] <= 20 for row in payload["records"])
    coverage = dataset_coverage(mars2020_places.DATASET_ID)
    assert coverage["coverage_count"] == 577
    assert coverage["unique_place_count"] == 1
    source = next(row for row in source_inventory(ROOT) if row["id"] == "mars2020-rover-places")
    assert source["status"] == "operational" and source["coverage_count"] == 577
    registry = next(row for row in datasets() if row["id"] == mars2020_places.DATASET_ID)
    assert registry["coverage_count"] == 577

    layers = {row["id"]: row for row in result["target_layers"]}
    assert layers["rover_operations"]["alignment_group"] == layers["terrain_dem"]["alignment_group"]
    preview = place_rover_operations_preview("mars-jezero")
    assert preview.status_code == 200
    assert int(preview.headers["x-enom-displayed-positions"]) == 270
    assert int(preview.headers["x-enom-total-positions"]) == 577
