import json
import struct
from pathlib import Path

import pytest

from twinworld import lend
from twinworld.analogue import discover, source_inventory
from twinworld.api import dataset_coverage, datasets

ROOT = Path(__file__).resolve().parents[1]


def _alds_record(latitude: float, longitude: float, exposure: float, rate: float, error: float) -> bytes:
    row = bytearray(b" " * lend.ROW_BYTES)
    row[:23] = b"2009-09-15T00:00:00.000"
    row[23:46] = b"2011-12-11T00:00:00.000"
    struct.pack_into(">ff", row, 46, latitude, longitude)
    struct.pack_into(">fff", row, lend.CSETN_EXPOSURE_OFFSET, exposure, rate, error)
    return bytes(row)


def test_lend_south_polar_grid_cell_selection_and_bounds():
    assert lend.south_polar_grid_cell(188.13, -89.77) == (0, 376)
    assert lend.south_polar_grid_cell(359.76422, -85.9948) == (8, 719)
    assert lend.south_polar_grid_cell(292.0679, -88.6834) == (2, 584)
    with pytest.raises(ValueError, match="covers latitudes"):
        lend.south_polar_grid_cell(188, -79.9)


def test_reads_one_fixed_record_and_preserves_rate_error_and_missing_value(monkeypatch):
    calls = []

    def fake_range(url, start, end, **kwargs):
        calls.append((url, start, end, kwargs))
        return _alds_record(-89.75, 188.25, 76, 5.01, 0.31)

    monkeypatch.setattr(lend, "_read_pds_byte_range", fake_range)
    product = lend.ALDS_PRODUCTS[0]
    record = lend.read_alds_cell(188.13, -89.77, product)
    assert calls[0][1:3] == (376 * 310, 377 * 310 - 1)
    assert record["value"] == pytest.approx(5.01)
    assert record["statistical_error"] == pytest.approx(0.31)
    assert record["grid_cell"] == {"latitude_deg": -89.75, "longitude_east_deg": 188.25}

    monkeypatch.setattr(
        lend,
        "_read_pds_byte_range",
        lambda *_args, **_kwargs: _alds_record(-89.75, 188.25, 0, -1, -1),
    )
    missing = lend.read_alds_cell(188.13, -89.77, product)
    assert missing["availability"] == "not_observed"
    assert missing["value"] is None


def test_lend_records_are_place_linked_context_not_scores():
    result = discover(ROOT, "moon-shackleton-rim", "polar_resources")
    water = next(row for row in result["target_evidence"] if row["id"] == "water_resources")
    lend_items = [item for item in water["evidence_items"] if item["dataset_id"] == lend.DATASET_ID]
    assert len(lend_items) == 2
    assert all(item["kind"] == "measured_remote_sensing" for item in lend_items)
    assert "not directly measure water or ice" in lend_items[0]["interpretation_note"]
    assert any(item["measurements"][0]["availability"] == "not_observed" for item in lend_items)
    assert all(
        next(dimension for dimension in row["dimension_scores"] if dimension["id"] == "water_resources")["score"] is None
        for row in result["results"]
    )

    payload = json.loads((ROOT / "data/environment/lro-lend-south-polar-alds.json").read_text())
    assert len(payload["records"]) == 6
    assert "full archive tables not downloaded" in payload["retrieval_method"]
    source = next(row for row in source_inventory(ROOT) if row["id"] == "lunar-lend")
    assert source["status"] == "operational" and source["coverage_count"] == 6
    coverage = dataset_coverage(lend.DATASET_ID)
    assert coverage["unique_place_count"] == 3
    assert "not_observed" in coverage["missing_data_semantics"]
    registry = next(row for row in datasets() if row["id"] == lend.DATASET_ID)
    assert registry["coverage_count"] == 6
