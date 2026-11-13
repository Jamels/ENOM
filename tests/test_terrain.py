from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from twinworld.science import Availability, PlanetaryBody
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


def test_planetary_body_enum_includes_moon():
    assert PlanetaryBody.MOON.value == "moon"
