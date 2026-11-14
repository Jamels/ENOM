from __future__ import annotations

from typing import get_args

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from twinworld.records import Body
from twinworld.science import Availability
from twinworld.terrain import terrain_features


def _write_dem(path, data, crs="EPSG:32633"):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(500000, 1000, 30, 30),
        nodata=-9999,
    ) as dataset:
        dataset.write(data.astype(np.float32), 1)


def test_flat_dem_features_have_zero_slope_and_relief(tmp_path):
    path = tmp_path / "flat.tif"
    _write_dem(path, np.full((9, 9), 125.0))
    metrics = terrain_features(
        path,
        observation_id="earth-flat",
        provider="test fixture",
        product_id="flat-1",
        source_url="https://example.invalid/flat-1",
    )
    values = {item.name: item.value for item in metrics}
    assert values["elevation_range"] == 0
    assert values["mean_slope"] == pytest.approx(0)
    assert values["median_local_relief_3x3"] == pytest.approx(0)
    assert next(item for item in metrics if item.name == "elevation_range").spatial_scale_m == 270
    assert all(item.availability == Availability.AVAILABLE for item in metrics)
    assert all(
        item.provenance and item.provenance.source_product_id == "flat-1" for item in metrics
    )


def test_nodata_hole_does_not_create_terrain_features(tmp_path):
    path = tmp_path / "flat-with-hole.tif"
    values = np.full((11, 11), 125.0, dtype=np.float32)
    values[5, 5] = -9999
    _write_dem(path, values)

    metrics = terrain_features(
        path,
        observation_id="earth-flat-hole",
        provider="test fixture",
        product_id="flat-hole-1",
        source_url="https://example.invalid/flat-hole-1",
    )

    values_by_name = {item.name: item.value for item in metrics}
    assert values_by_name["elevation_range"] == 0
    assert values_by_name["mean_slope"] == pytest.approx(0)
    assert values_by_name["slope_p90"] == pytest.approx(0)
    assert values_by_name["median_local_relief_3x3"] == pytest.approx(0)
    assert values_by_name["median_roughness_3x3"] == pytest.approx(0)
    assert values_by_name["median_curvature"] == pytest.approx(0)


def test_sloping_plane_uses_metric_grid_spacing(tmp_path):
    path = tmp_path / "slope.tif"
    # 30 m cells and 2 m rise per metre eastward.
    values = np.tile(np.arange(9, dtype=np.float32) * 60, (9, 1))
    _write_dem(path, values)
    metrics = terrain_features(
        path,
        observation_id="earth-slope",
        provider="test fixture",
        product_id="slope-1",
        source_url="https://example.invalid/slope-1",
    )
    slope = next(item for item in metrics if item.name == "mean_slope")
    assert slope.value == pytest.approx(np.degrees(np.arctan(2)), abs=1e-5)
    assert slope.spatial_scale_m == 60


def test_slope_summaries_exclude_one_sided_raster_boundary_derivatives(tmp_path):
    path = tmp_path / "boundary-step.tif"
    values = np.zeros((9, 9), dtype=np.float32)
    values[0, :] = 300
    _write_dem(path, values)

    gy, gx = np.gradient(values, 30, 30)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    interior = slope[1:-1, 1:-1]
    measurements = terrain_features(
        path,
        observation_id="earth-boundary-step",
        provider="test fixture",
        product_id="boundary-step-1",
        source_url="https://example.invalid/boundary-step-1",
    )
    by_name = {item.name: item.value for item in measurements}

    assert by_name["mean_slope"] == pytest.approx(float(interior.mean()))
    assert by_name["slope_p90"] == pytest.approx(float(np.percentile(interior, 90)))


def test_curved_surface_has_expected_laplacian_and_nonzero_roughness(tmp_path):
    path = tmp_path / "bowl.tif"
    y, x = np.mgrid[-4:5, -4:5]
    values = (x * 30) ** 2 * 1e-4 + (y * 30) ** 2 * 1e-4
    _write_dem(path, values)
    metrics = terrain_features(
        path,
        observation_id="earth-bowl",
        provider="test fixture",
        product_id="bowl-1",
        source_url="https://example.invalid/bowl-1",
    )
    by_name = {item.name: item for item in metrics}
    assert by_name["median_curvature"].value == pytest.approx(0.0004, abs=1e-8)
    assert by_name["median_roughness_3x3"].value > 0
    assert by_name["slope_p90"].value > by_name["mean_slope"].value


def test_geographic_dem_is_rejected(tmp_path):
    path = tmp_path / "geographic.tif"
    _write_dem(path, np.ones((9, 9)), crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected CRS"):
        terrain_features(
            path,
            observation_id="bad",
            provider="test fixture",
            product_id="bad-1",
            source_url="https://example.invalid/bad-1",
        )


def test_dem_smaller_than_neighborhood_is_rejected(tmp_path):
    path = tmp_path / "single-row.tif"
    _write_dem(path, np.full((1, 9), 125.0))

    with pytest.raises(ValueError, match="at least 3x3 cells"):
        terrain_features(
            path,
            observation_id="too-small",
            provider="test fixture",
            product_id="too-small-1",
            source_url="https://example.invalid/too-small-1",
        )


def test_manifest_body_type_includes_moon():
    assert "moon" in get_args(Body)
