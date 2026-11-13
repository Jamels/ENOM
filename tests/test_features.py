import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from twinworld.features import classical_descriptor, read_grayscale
from twinworld.vision import embedding_cache_stem


def test_rgb_nodata_is_filled_before_grayscale_and_descriptors(tmp_path: Path):
    source = tmp_path / "rgb-with-nodata.tif"
    yy, xx = np.mgrid[0:64, 0:64]
    image = np.stack((xx, yy, xx + yy), axis=0).astype(np.float32)
    image[:, 3:8, 4:10] = np.nan
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=3,
        dtype="float32",
        crs="EPSG:32633",
        transform=from_origin(500_000, 7_000_000, 10, 10),
        nodata=np.nan,
    ) as dataset:
        dataset.write(image)

    grayscale = read_grayscale(source, size=64)
    assert np.isfinite(grayscale).all()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        descriptor = classical_descriptor(source, size=64)
    assert np.isfinite(descriptor).all()
    assert np.linalg.norm(descriptor) == pytest.approx(1.0)


def test_dinov2_profiles_keep_distinct_embedding_cache_names():
    assert embedding_cache_stem("facebook/dinov2-small") == "embeddings_dinov2"
    assert embedding_cache_stem("facebook/dinov2-base") == "embeddings_dinov2_base"
