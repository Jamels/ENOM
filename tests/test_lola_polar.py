import json
from pathlib import Path

import numpy as np

from twinworld import lola_polar
from twinworld.api import datasets, dataset_coverage, place_coverage_preview, place_elevation_preview
from twinworld.analogue import discover, source_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_lunar_candidate_coordinates_map_inside_native_south_polar_grid():
    candidates = [
        (188.13, -89.77),
        (359.76422, -85.9948),
        (292.0679, -88.6834),
    ]
    pixels = [lola_polar.lunar_polar_pixel(longitude, latitude) for longitude, latitude in candidates]
    assert len(set(pixels)) == len(candidates)
    assert all(0 <= column < lola_polar.GRID_SIZE for column, _ in pixels)
    assert all(0 <= row < lola_polar.GRID_SIZE for _, row in pixels)


def test_polar_crop_reads_only_the_requested_window_and_masks_zero_shot_cells(monkeypatch):
    calls = []
    width = 16

    def fake_range(url, start, end, **_kwargs):
        calls.append((url, start, end))
        payload = bytearray(end - start + 1)
        value = 200 if url == lola_polar.DEM_URL else 2
        dtype = "<i2"
        row_bytes = np.full(width, value, dtype=dtype).tobytes()
        for row in range(width):
            start_offset = row * lola_polar.RECORD_BYTES
            payload[start_offset : start_offset + width * 2] = row_bytes
        if url == lola_polar.COUNT_URL:
            payload[5 * lola_polar.RECORD_BYTES + 5 * 2 : 5 * lola_polar.RECORD_BYTES + 6 * 2] = np.array([0], dtype=dtype).tobytes()
        return bytes(payload)

    monkeypatch.setattr(lola_polar, "read_byte_range", fake_range)
    elevation, counts, first_col, first_row = lola_polar.read_lola_polar_crop(
        188.13, -89.77, half_width_pixels=8
    )
    assert len(calls) == 2
    assert calls[0][0] == lola_polar.DEM_URL
    assert calls[1][0] == lola_polar.COUNT_URL
    assert len(elevation) == len(counts) == width
    assert first_col >= 0 and first_row >= 0
    assert np.nanmedian(elevation) == 100
    assert counts[5, 5] == 0 and np.isnan(elevation[5, 5])


def test_lola_polar_crops_are_place_linked_and_used_for_terrain_ranking():
    metadata = [
        json.loads(path.read_text())
        for path in sorted((ROOT / "data/terrain").glob("lola_polar_*.tif.json"))
    ]
    assert len(metadata) == 3
    assert {row["place_id"] for row in metadata} == {
        "moon-shackleton-rim", "moon-malapert-massif", "moon-de-gerlache-rim"
    }
    assert all(row["observed_cell_fraction"] == 1 for row in metadata)
    assert all((ROOT / row["count_raster"]).is_file() for row in metadata)

    result = discover(ROOT, "moon-shackleton-rim", "polar_resources")
    terrain = next(row for row in result["target_evidence"] if row["id"] == "terrain")
    assert terrain["status"] == "available"
    assert {row["name"] for row in terrain["measurements"]} >= {
        "elevation_range", "mean_slope", "median_roughness_3x3"
    }
    assert any(row["score"] is not None for row in result["results"])

    source = next(row for row in source_inventory(ROOT) if row["id"] == "lola-polar-dem")
    assert source["status"] == "operational" and source["coverage_count"] == 3
    assert next(row for row in datasets() if row["id"] == "lro-lola-gdr-polar-ldem-120m")["coverage_count"] == 3
    coverage = dataset_coverage("lro-lola-gdr-polar-ldem-120m")
    assert set(coverage["place_ids"]) == {row["place_id"] for row in metadata}
    assert "not vertical uncertainty" in coverage["support_semantics"]
    assert place_elevation_preview("moon-shackleton-rim").body.startswith(b"\x89PNG\r\n\x1a\n")
    assert place_coverage_preview("moon-shackleton-rim").body.startswith(b"\x89PNG\r\n\x1a\n")
