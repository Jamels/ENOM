import json
from pathlib import Path

import pytest

from twinworld import diviner_prp
from twinworld.analogue import _place_layers, build_places, discover, source_inventory
from twinworld.api import dataset_coverage, datasets

ROOT = Path(__file__).resolve().parents[1]


def _prp_record(latitude: float, longitude: float, average: float = 110.0, maximum: float = 220.0, ice: float = 0.4) -> bytes:
    return (
        f"0,0,0,0,0,0,0,0,0,{longitude:15.9f},{latitude:15.9f},0,"
        f"{average:8.3f},{maximum:8.3f},{ice:11.5f}\r\n"
    ).encode("ascii").ljust(diviner_prp.ROW_BYTES, b" ")[: diviner_prp.ROW_BYTES]


def test_south_polar_mesh_lookup_bounds_and_longitude_wrap():
    assert diviner_prp._candidate_grid(-89.77, 188.13) == diviner_prp._candidate_grid(-89.77, -171.87)
    with pytest.raises(ValueError, match="covers latitudes"):
        diviner_prp._candidate_grid(-79.9, 0)


def test_parse_prp_fields_and_preserve_excluded_ice_depth_as_missing():
    parsed = diviner_prp._parse_record(
        _prp_record(-89.77, 188.13, ice=-999.0), 12, -89.77, 188.13
    )
    assert parsed["measurements"]["annual_average_surface_temperature_2cm"] == 110.0
    assert parsed["measurements"]["annual_maximum_surface_temperature"] == 220.0
    assert parsed["measurements"]["modeled_ice_stability_depth"] is None
    assert parsed["distance_from_candidate_km"] == pytest.approx(0.0, abs=0.01)


def test_reads_only_five_local_row_ranges(monkeypatch):
    calls = []

    def fake_range(_url, start, end, **_kwargs):
        calls.append((start, end))
        return _prp_record(-89.77, 188.13) * ((end - start + 1) // diviner_prp.ROW_BYTES)

    monkeypatch.setattr(diviner_prp, "_read_pds_byte_range", fake_range)
    sample = diviner_prp.read_nearest_triangle(-89.77, 188.13)
    assert len(calls) == 5
    assert sample["search_triangle_count"] == 50
    assert sample["distance_from_candidate_km"] == pytest.approx(0.0, abs=0.01)


def test_diviner_prp_is_context_evidence_not_cross_body_score():
    result = discover(ROOT, "moon-shackleton-rim", "polar_resources")
    thermal = next(row for row in result["target_evidence"] if row["id"] == "thermal_illumination")
    resources = next(row for row in result["target_evidence"] if row["id"] == "water_resources")
    thermal_items = [item for item in thermal["evidence_items"] if item["dataset_id"] == diviner_prp.DATASET_ID]
    resource_items = [item for item in resources["evidence_items"] if item["dataset_id"] == diviner_prp.DATASET_ID]
    assert len(thermal_items) == len(resource_items) == 1
    assert "thermal-model" in thermal["summary"]
    assert "not a direct detection" in resources["summary"]
    assert thermal_items[0]["spatial_coverage"]["spatial_scale_m"] == 500.0
    assert thermal_items[0]["spatial_coverage"]["location_precision"] == "nearest_triangular_mesh_centroid"
    assert "Nearest mesh centroid" in thermal_items[0]["spatial_relation"]
    assert all(
        next(dimension for dimension in row["dimension_scores"] if dimension["id"] in {"thermal_illumination", "water_resources"})["score"] is None
        for row in result["results"]
    )

    payload = json.loads((ROOT / "data/environment/lro-diviner-south-polar-prp.json").read_text())
    assert len(payload["records"]) == 3
    assert all(record["distance_from_candidate_km"] < 1 for record in payload["records"])
    source = next(row for row in source_inventory(ROOT) if row["id"] == "diviner-prp")
    assert source["status"] == "operational" and source["coverage_count"] == 3
    coverage = dataset_coverage(diviner_prp.DATASET_ID)
    assert coverage["unique_place_count"] == 3
    assert "not direct detection" in coverage["interpretation_limit"]
    registry = next(row for row in datasets() if row["id"] == diviner_prp.DATASET_ID)
    assert registry["coverage_count"] == 3


@pytest.mark.parametrize("place_id", ["earth-namib", "mars-jezero", "moon-shackleton-rim"])
def test_elevation_and_slope_layers_share_a_registered_grid_for_each_body(place_id):
    place = next(row for row in build_places(ROOT) if row["id"] == place_id)
    layers = {row["id"]: row for row in _place_layers(ROOT, place)}
    assert layers["terrain_dem"]["url"]
    assert layers["terrain_slope"]["url"]
    assert layers["terrain_dem"]["body"] == layers["terrain_slope"]["body"]
    assert layers["terrain_dem"]["alignment_group"] == layers["terrain_slope"]["alignment_group"]
