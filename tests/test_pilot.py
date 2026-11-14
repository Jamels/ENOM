from dataclasses import replace
from pathlib import Path

import pytest
import shapefile
from rasterio.coords import BoundingBox
from rasterio.crs import CRS

from scripts.build_pilot import _cached_patch_matches, _dune_positions, _sha256
from twinworld.geospatial import mars_surface_distance_m, ring_contains, shape_contains
from twinworld.records import read_jsonl


def test_cached_patch_reuse_checks_source_center_and_file_checksum(tmp_path: Path):
    record = read_jsonl(Path("data/manifests/pilot-100.jsonl"))[0]
    patch_path = tmp_path / "patch.tif"
    patch_path.write_bytes(b"cached raster contents")
    cached_record = replace(
        record,
        source_id="source-1",
        checksum_sha256=_sha256(patch_path),
        processing={"patch_center_x": "10", "patch_center_y": "20"},
    )
    planned_row = {
        "source_id": "source-1",
        "center_x": 10,
        "center_y": 20,
    }

    assert _cached_patch_matches(planned_row, cached_record, patch_path)
    wrong_source = {**planned_row, "source_id": "source-2"}
    assert not _cached_patch_matches(wrong_source, cached_record, patch_path)
    assert not _cached_patch_matches({**planned_row, "center_x": 11}, cached_record, patch_path)
    assert not _cached_patch_matches({**planned_row, "center_y": 21}, cached_record, patch_path)
    assert not _cached_patch_matches(
        planned_row, replace(cached_record, checksum_sha256="0" * 64), patch_path
    )


def test_mars_surface_distance_uses_mars_radius_and_wraps_east_longitude():
    one_degree = mars_surface_distance_m(0, 0, 1, 0)
    across_longitude_wrap = mars_surface_distance_m(359, 0, 0, 0)

    assert one_degree == pytest.approx(59_276.2, rel=1e-4)
    assert across_longitude_wrap == pytest.approx(one_degree)


def test_linear_dune_positions_stay_in_field_and_respect_crop_spacing():
    field = shapefile.Shape(
        shapeType=shapefile.POLYGON,
        points=[(-2, -2), (2, -2), (2, 2), (-2, 2), (-2, -2)],
        parts=[0],
    )
    projected_crs = CRS.from_proj4(
        "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +R=3396190 +units=m +no_defs"
    )

    offsets = _dune_positions(
        field,
        0,
        0,
        (0, 0),
        projected_crs,
        BoundingBox(-50_000, -50_000, 50_000, 50_000),
        extent_m=2_000,
        count=3,
    )

    assert offsets == [[0.0, 0.0], [-2500.0, 0], [2500.0, 0]]
    assert all(
        abs(left[0] - right[0]) >= 2_000 or abs(left[1] - right[1]) >= 2_000
        for index, left in enumerate(offsets)
        for right in offsets[index + 1 :]
    )


def test_linear_dune_positions_skip_centers_outside_the_dune_field():
    small_field = shapefile.Shape(
        shapeType=shapefile.POLYGON,
        points=[
            (-0.02, -0.02),
            (0.02, -0.02),
            (0.02, 0.02),
            (-0.02, 0.02),
            (-0.02, -0.02),
        ],
        parts=[0],
    )
    projected_crs = CRS.from_proj4(
        "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +R=3396190 +units=m +no_defs"
    )

    offsets = _dune_positions(
        small_field,
        0,
        0,
        (0, 0),
        projected_crs,
        BoundingBox(-50_000, -50_000, 50_000, 50_000),
        extent_m=2_000,
        count=3,
    )

    assert offsets == [[0.0, 0.0]]


def test_mars_surface_distance_rejects_invalid_coordinates():
    with pytest.raises(ValueError, match="finite"):
        mars_surface_distance_m(float("nan"), 0, 1, 0)
    with pytest.raises(ValueError, match="latitude"):
        mars_surface_distance_m(0, 91, 1, 0)


def test_ring_contains_uses_unmodified_coordinates():
    ring = [(10, 10), (20, 10), (20, 20), (10, 20), (10, 10)]

    assert ring_contains(ring, 15, 15)
    assert not ring_contains(ring, 5, 15)


def test_mgd3_polygon_contains_signed_and_0_to_360_mars_longitudes():
    geometry = shapefile.Shape(
        shapeType=shapefile.POLYGON,
        points=[(-51, -10), (-49, -10), (-49, -8), (-51, -8), (-51, -10)],
        parts=[0],
    )

    assert shape_contains(geometry, -50, -9)
    assert shape_contains(geometry, 310, -9)
    assert not shape_contains(geometry, 308, -9)
