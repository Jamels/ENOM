from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from twinworld.patching import extract_metric_patch


def create_raster(path: Path, crs: str) -> None:
    values = np.arange(400 * 400, dtype=np.uint16).reshape(400, 400)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=400,
        height=400,
        count=1,
        dtype="uint16",
        crs=crs,
        transform=from_origin(0, 4000, 10, 10),
        nodata=0,
    ) as dataset:
        dataset.write(values, 1)


def test_metric_patch_has_requested_ground_extent(tmp_path: Path):
    source = tmp_path / "source.tif"
    output = tmp_path / "patch.tif"
    create_raster(source, "EPSG:32633")

    geometry = extract_metric_patch(
        source,
        output,
        center_x=2000,
        center_y=2000,
        extent_m=1000,
        native_gsd_m=10,
    )

    assert geometry.width_pixels == 100
    assert geometry.width_m == pytest.approx(1000)
    assert geometry.pixel_size_m == pytest.approx(10)
    with rasterio.open(output) as patch:
        assert patch.crs.to_epsg() == 32633
        assert patch.width == patch.height == 100
        assert np.isfinite(patch.read(1, masked=True).compressed()).any()
    assert output.with_suffix(".tif.json").is_file()


def test_metric_patch_rejects_unprojected_source(tmp_path: Path):
    source = tmp_path / "geographic.tif"
    create_raster(source, "EPSG:4326")
    with pytest.raises(ValueError, match="projected map CRS"):
        extract_metric_patch(
            source,
            tmp_path / "out.tif",
            center_x=0,
            center_y=0,
            extent_m=1000,
            native_gsd_m=10,
        )


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("parameter", ["extent_m", "native_gsd_m"])
def test_metric_patch_rejects_non_finite_physical_scales(tmp_path, parameter, invalid_value):
    arguments = {"extent_m": 1000.0, "native_gsd_m": 10.0}
    arguments[parameter] = invalid_value

    with pytest.raises(ValueError, match="must be finite and positive"):
        extract_metric_patch(
            tmp_path / "does-not-need-to-exist.tif",
            tmp_path / "out.tif",
            center_x=2000,
            center_y=2000,
            **arguments,
        )
