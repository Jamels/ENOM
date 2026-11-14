import json
import struct
from pathlib import Path

import pytest

from twinworld import minirf
from twinworld.analogue import discover, source_inventory
from twinworld.api import dataset_coverage, datasets, place_minirf_cpr_preview

ROOT = Path(__file__).resolve().parents[1]


def test_polar_coordinates_match_the_three_candidate_regions():
    coords = [
        minirf.polar_pixel(188.13, -89.77),
        minirf.polar_pixel(359.76422, -85.9948),
        minirf.polar_pixel(292.0679, -88.6834),
    ]
    assert coords == [(645, 654), (646, 518), (607, 631)]
    with pytest.raises(ValueError, match="covers latitudes"):
        minirf.polar_pixel(0, -60)


def test_reads_only_local_byte_ranges_and_ignores_pds_nulls(monkeypatch):
    calls = []

    def fake_range(url, start, end, timeout=30):
        calls.append((url, start, end))
        values = [2.0] * ((end - start + 1) // 4)
        if len(calls) == 1:
            values[0] = struct.unpack("<f", struct.pack("<I", 0xFF7FFFFB))[0]
        return struct.pack(f"<{len(values)}f", *values)

    monkeypatch.setattr(minirf, "read_byte_range", fake_range)
    sample = minirf.read_cpr_neighborhood(188.13, -89.77, radius_pixels=1)
    assert len(calls) == 3
    assert calls[0][0] == minirf.IMAGE_URL
    assert calls[0][2] - calls[0][1] + 1 == 12
    assert sample["valid_pixel_count"] == 8
    assert sample["median_cpr"] == 2.0


def test_minirf_is_place_linked_context_not_a_score():
    result = discover(ROOT, "moon-shackleton-rim", "polar_resources")
    water = next(row for row in result["target_evidence"] if row["id"] == "water_resources")
    item = next(row for row in water["evidence_items"] if row["dataset_id"] == minirf.DATASET_ID)
    assert water["status"] == "context_only"
    assert item["kind"] == "measured_remote_sensing"
    assert item["measurements"][0]["units"] == "dimensionless ratio"
    assert "not a unique water-ice detector" in item["interpretation_note"]
    assert "not establish water" in item["use_limit"]
    assert all(
        next(d for d in row["dimension_scores"] if d["id"] == "water_resources")["score"] is None
        for row in result["results"]
    )

    data = json.loads((ROOT / "data/environment/lro-mini-rf-south-polar-cpr.json").read_text())
    assert len(data["records"]) == 3
    assert all(row["valid_pixel_count"] == 25 for row in data["records"])
    assert "full mosaic not downloaded" in data["retrieval_method"]
    source = next(row for row in source_inventory(ROOT) if row["id"] == "mini-rf-cpr")
    assert source["status"] == "operational" and source["coverage_count"] == 3
    assert dataset_coverage(minirf.DATASET_ID)["status"] == "context_only"
    registry = next(row for row in datasets() if row["id"] == minirf.DATASET_ID)
    assert registry["coverage_count"] == 3
    assert place_minirf_cpr_preview("moon-shackleton-rim").body.startswith(b"\x89PNG\r\n\x1a\n")
    layer = next(row for row in result["target_layers"] if row["id"] == "mini_rf_cpr")
    assert layer["status"] == "available"
    assert "never overlaid on Earth coordinates" in layer["alignment_note"]
