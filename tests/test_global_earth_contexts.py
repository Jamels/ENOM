import json

import numpy as np
import pytest
from rasterio.transform import array_bounds

from scripts.build_global_earth_contexts import (
    CELLS,
    CONTEXT_M,
    SURFACE_CELLS,
    SphericalSpacingIndex,
    TransferCounter,
    context_footprint_area_km2,
    copdem_tile_name,
    geographic_band,
    is_bounded_source_request,
    metric_grid,
    parse_proxy_path,
    surface_grid,
    worldcover_fractions,
    worldcover_tile_name,
)


def test_metered_proxy_routes_source_paths_after_leading_slash():
    assert parse_proxy_path(
        "/copdem/Copernicus_DSM_COG_30_N08_00_E031_00_DEM/file.tif"
    ) == (
        "copdem",
        "copernicus-dem-90m.s3.eu-central-1.amazonaws.com",
        "Copernicus_DSM_COG_30_N08_00_E031_00_DEM/file.tif",
    )
    assert parse_proxy_path("/worldcover/v200/2021/map/tile.tif") == (
        "worldcover",
        "esa-worldcover.s3.eu-central-1.amazonaws.com",
        "v200/2021/map/tile.tif",
    )
    assert parse_proxy_path("/unknown/file.tif") is None
    assert is_bounded_source_request("GET", {"Range": "bytes=0-1023"})
    assert is_bounded_source_request("HEAD", {})
    assert not is_bounded_source_request("GET", {})
    assert not is_bounded_source_request("POST", {"Range": "bytes=0-1023"})


def test_metered_proxy_rejects_full_reads_and_counts_range_bodies(monkeypatch):
    import requests

    from scripts.build_global_earth_contexts import metered_proxy

    counter = TransferCounter()
    upstream_calls = []
    original_request = requests.sessions.Session.request

    class FakeRangeResponse:
        status_code = 206
        headers = {
            "Content-Length": "4",
            "Content-Range": "bytes 0-3/100",
            "Accept-Ranges": "bytes",
        }

        def iter_content(self, _chunk_size):
            yield b"data"

        def close(self):
            return None

    def request(session, method, url, *args, **kwargs):
        if url.startswith("http://127.0.0.1:"):
            return original_request(session, method, url, *args, **kwargs)
        upstream_calls.append((method, url, kwargs.get("headers", {}).get("Range")))
        return FakeRangeResponse()

    monkeypatch.setattr(requests.sessions.Session, "request", request)
    with metered_proxy(counter) as proxy:
        unbounded = requests.get(f"{proxy}/copdem/tile/file.tif")
        assert unbounded.status_code == 400
        assert upstream_calls == []
        bounded = requests.get(
            f"{proxy}/copdem/tile/file.tif", headers={"Range": "bytes=0-3"}
        )
        assert bounded.status_code == 206
        assert bounded.content == b"data"
    assert upstream_calls == [
        (
            "GET",
            "https://copernicus-dem-90m.s3.eu-central-1.amazonaws.com/tile/file.tif",
            "bytes=0-3",
        )
    ]
    assert counter.snapshot()["total_bytes"] == 4
    assert counter.snapshot()["range_responses_by_source"] == {
        "copernicus-dem-90m.s3.eu-central-1.amazonaws.com": 1
    }


def test_proxy_counts_received_chunk_when_local_reader_disconnects():
    from scripts.build_global_earth_contexts import forward_response_body

    def disconnect(_block):
        raise BrokenPipeError

    received = forward_response_body(iter((b"source-chunk", b"not-requested")), disconnect)
    assert received == len(b"source-chunk")


def test_transfer_counter_checkpoints_and_resumes_total_bytes(tmp_path):
    progress = tmp_path / "transfer.json"
    counter = TransferCounter(progress_path=progress)
    counter.add("copernicus", 1024, ranged=True)
    counter.add("worldcover", 256, ranged=True)
    resumed = TransferCounter(json.loads(progress.read_text()))
    resumed.add("copernicus", 512, ranged=False)
    assert resumed.snapshot() == {
        "bytes_by_source": {"copernicus": 1536, "worldcover": 256},
        "range_responses_by_source": {"copernicus": 1, "worldcover": 1},
        "total_bytes": 1792,
    }


def test_surface_classification_grid_matches_terrain_footprint():
    _, terrain_transform = metric_grid(31.4, 8.5)
    cover_transform = surface_grid(terrain_transform)
    terrain_bounds = array_bounds(CELLS, CELLS, terrain_transform)
    cover_bounds = array_bounds(SURFACE_CELLS, SURFACE_CELLS, cover_transform)
    assert cover_bounds == pytest.approx(terrain_bounds)
    assert cover_bounds[2] - cover_bounds[0] == pytest.approx(CONTEXT_M)
    assert cover_bounds[3] - cover_bounds[1] == pytest.approx(CONTEXT_M)


def test_ground_footprint_area_uses_inverse_projected_edge_distances(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    posting = CONTEXT_M / CELLS
    raster = tmp_path / "context.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=CELLS,
        height=CELLS,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500_000 - CONTEXT_M / 2, CONTEXT_M / 2, posting, posting),
    ) as destination:
        destination.write(np.zeros((CELLS, CELLS), dtype=np.float32), 1)
    assert context_footprint_area_km2(raster) == pytest.approx(
        (CONTEXT_M / 1000) ** 2, rel=0.01
    )


def test_equal_area_coverage_bins_handle_southern_and_wrapped_longitudes():
    assert geographic_band(-0.1, -0.1) == "-10_to_+00|330_to_360"


def test_spherical_spacing_index_handles_dateline_and_polar_neighbors():
    spacing = SphericalSpacingIndex(100)
    spacing.add(179.8, 0)
    assert spacing.is_too_close(-179.8, 0)
    assert not spacing.is_too_close(-177, 0)
    spacing.add(0, 89.5)
    assert spacing.is_too_close(30, 89.5)


def test_spherical_spacing_index_matches_great_circle_threshold():
    from scripts.build_global_earth_contexts import _great_circle_km

    spacing = SphericalSpacingIndex(100)
    spacing.add(10, 10)
    for longitude, latitude in ((10.1, 10), (10.5, 10), (9.7, 10.6), (20, 20)):
        expected = _great_circle_km((10, 10), (longitude, latitude)) < 100
        assert spacing.is_too_close(longitude, latitude) is expected
    with pytest.raises(ValueError, match="half a circumference"):
        SphericalSpacingIndex(20_100)


def test_negative_coordinates_use_south_and_west_tile_origins():
    assert copdem_tile_name(-0.1, -0.1) == "Copernicus_DSM_COG_30_S01_00_W001_00_DEM"
    assert worldcover_tile_name(-0.1, -0.1) == "S03W003"


def test_worldcover_fractions_preserve_nodata_and_group_classes():
    values = np.array([[10, 10, 50], [80, 0, 60]], dtype=np.uint8)
    result = worldcover_fractions(values)
    assert result["valid_fraction"] == pytest.approx(5 / 6)
    assert result["sample_count"] == 5
    assert result["group_fractions"]["forest"] == pytest.approx(2 / 5)
    assert result["group_fractions"]["built_up"] == pytest.approx(1 / 5)
    assert result["group_fractions"]["water"] == pytest.approx(1 / 5)
    unknown = worldcover_fractions(np.array([[10, 200]], dtype=np.uint8))
    assert unknown["valid_fraction"] == pytest.approx(1 / 2)
