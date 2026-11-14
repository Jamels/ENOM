from __future__ import annotations

import numpy as np

from scripts.ingest_mola import _read_crop, tile_for
from twinworld.api import dataset_coverage, datasets, region


def test_mola_tile_selection_uses_east_longitude_and_north_latitude():
    assert tile_for(6.76, 7.1) == ("44n000hb", 0.0, 44.0)
    assert tile_for(276.0, -12.0) == ("00n270hb", 270.0, 0.0)


def test_mola_window_decoder_respects_big_endian_full_row_stride(monkeypatch):
    columns = 90 * 128
    row, column, width, height = 20, 4, 3, 2
    grid = np.arange(columns * (row + height), dtype=np.int16).reshape(row + height, columns)
    payload = b"".join(
        [grid[row, column:].astype(">i2").tobytes()]
        + [
            grid[index, : column + width].astype(">i2").tobytes()
            for index in range(row + 1, row + height)
        ]
    )
    monkeypatch.setattr("scripts.ingest_mola.read_range_window", lambda _url, **_: payload)
    output = _read_crop(
        "https://example.invalid/mola.img",
        row,
        column,
        width=width,
        height=height,
        bytes_per_sample=2,
        dtype=">i2",
    )
    np.testing.assert_array_equal(output, grid[row : row + height, column : column + width])


def test_mola_metadata_is_exposed_without_claiming_full_coverage():
    coverage = dataset_coverage("mola-meg128")
    assert coverage["coverage_count"] == 13
    assert len(coverage["observations"]) == 13
    mars = region("mars-dune-barchan_crescent_dune-0067+071")
    assert mars["terrain_contexts"][0]["observed_cell_count"] == 148
    mola = next(item for item in datasets() if item["id"] == "mola-meg128")
    assert mola["status"] == "operational"
