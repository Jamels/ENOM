"""Create fixed-physical-size patches from already map-projected rasters."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from os import fspath
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject


@dataclass(frozen=True, slots=True)
class PatchGeometry:
    """Measured output grid geometry and valid-source coverage for a patch."""

    width_pixels: int
    height_pixels: int
    width_m: float
    height_m: float
    pixel_size_m: float
    valid_pixel_fraction: float
    crs: str
    transform: tuple[float, float, float, float, float, float]


def extract_metric_patch(
    source_path: str | Path,
    destination_path: Path,
    *,
    center_x: float,
    center_y: float,
    extent_m: float,
    native_gsd_m: float,
    bands: tuple[int, ...] = (1,),
    min_valid_fraction: float = 0.95,
) -> PatchGeometry:
    """Warp a square crop around map-coordinate ``center_x, center_y``.

    The source must already have a projected CRS with linear units. This avoids
    pretending that unprojected CTX detector coordinates are metric imagery.
    ``native_gsd_m`` is the source observation's native sampling, not the output
    grid size; output pixels can be resized later for model input.
    """
    if extent_m <= 0 or native_gsd_m <= 0:
        raise ValueError("extent_m and native_gsd_m must be positive")
    if not math.isfinite(center_x) or not math.isfinite(center_y):
        raise ValueError("center coordinates must be finite")
    if not bands:
        raise ValueError("at least one source band is required")
    if not 0 < min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must be in (0, 1]")
    if any(band < 1 for band in bands):
        raise ValueError("band indices are one-based and must be positive")

    source_reference = fspath(source_path)
    with rasterio.open(source_reference) as source:
        if source.crs is None or not source.crs.is_projected:
            raise ValueError("source must have a projected map CRS")
        if max(bands) > source.count:
            raise ValueError(f"source has {source.count} bands; requested {bands}")
        unit_name, units_to_m = source.crs.linear_units_factor
        if not math.isfinite(units_to_m) or units_to_m <= 0:
            raise ValueError(f"unsupported projected CRS linear unit: {unit_name}")

        pixel_count = max(1, round(extent_m / native_gsd_m))
        pixel_size_m = extent_m / pixel_count
        pixel_size_units = pixel_size_m / units_to_m
        extent_units = pixel_count * pixel_size_units
        transform = Affine(
            pixel_size_units,
            0,
            center_x - extent_units / 2,
            0,
            -pixel_size_units,
            center_y + extent_units / 2,
        )
        destination = np.full((len(bands), pixel_count, pixel_count), np.nan, dtype=np.float32)
        for out_index, source_band in enumerate(bands):
            reproject(
                source=rasterio.band(source, source_band),
                destination=destination[out_index],
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source.nodata,
                dst_transform=transform,
                dst_crs=source.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
                init_dest_nodata=True,
            )
        valid_mask = np.isfinite(destination).all(axis=0)
        valid_fraction = float(valid_mask.mean())
        if valid_fraction < min_valid_fraction:
            raise ValueError(
                f"valid source coverage {valid_fraction:.3f} is below "
                f"required {min_valid_fraction:.3f}"
            )
        profile = source.profile.copy()
        crs_string = source.crs.to_string()

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(
        driver="GTiff",
        width=pixel_count,
        height=pixel_count,
        count=len(bands),
        dtype="float32",
        transform=transform,
        nodata=np.nan,
        compress="deflate",
        predictor=3,
    )
    with rasterio.open(destination_path, "w", **profile) as output:
        output.write(destination)
        output.update_tags(
            source_path=Path(urlparse(source_reference).path).name,
            source_bands=",".join(map(str, bands)),
            center_x=str(center_x),
            center_y=str(center_y),
            requested_extent_m=str(extent_m),
            source_native_gsd_m=str(native_gsd_m),
            processing="projected metric warp; bilinear resampling",
        )
    geometry = PatchGeometry(
        width_pixels=pixel_count,
        height_pixels=pixel_count,
        width_m=extent_units * units_to_m,
        height_m=extent_units * units_to_m,
        pixel_size_m=pixel_size_m,
        valid_pixel_fraction=valid_fraction,
        crs=crs_string,
        transform=tuple(transform)[:6],
    )
    sidecar = destination_path.with_suffix(destination_path.suffix + ".json")
    sidecar.write_text(json.dumps(asdict(geometry), indent=2) + "\n", encoding="utf-8")
    return geometry
