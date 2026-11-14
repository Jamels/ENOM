"""DEM ingestion adapter and scale-explicit morphology measurements."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from twinworld.science import (
    Availability,
    PhysicalMeasurement,
    ProvenanceRecord,
    Uncertainty,
)


def terrain_features(
    dem_path: Path,
    *,
    observation_id: str,
    provider: str,
    product_id: str,
    source_url: str,
    processing_method: str = "Central finite differences on projected DEM grid",
) -> list[PhysicalMeasurement]:
    """Derive scale-explicit morphology measurements from a projected DEM.

    Elevation range is max minus min over valid cells. Slope is the angle
    ``atan(sqrt((dz/dx)^2 + (dz/dy)^2))`` from NumPy's finite differences;
    this function reports the mean and 90th percentile in degrees. NumPy uses
    central differences inside the raster and one-sided differences at its
    boundary, so boundary cells are excluded from both slope summaries (see
    https://numpy.org/doc/stable/reference/generated/numpy.gradient.html).
    The 3x3 local relief is neighborhood max minus min. Roughness at cell ``i`` is
    ``abs(z_i - mean(z_3x3))``; the reported statistic is its median.
    Curvature is the Laplacian ``d²z/dx² + d²z/dy²``, with units of inverse
    metres. Local relief and roughness are project descriptors, not claims to
    implement a named standardized roughness index.

    Derivative scales describe the grid support: slope uses a two-cell
    central-difference baseline, while 3x3 statistics use three cells.
    Incomplete neighborhoods are excluded from local relief, roughness, and
    curvature summaries. For neighborhood calculations, nodata cells are
    temporarily filled with the median valid elevation so filters can run;
    incomplete neighborhoods are then masked from the reported statistics.
    Slope also excludes non-finite
    derivatives. Elevation range uses all valid cells.

    The input CRS must use metres. Geographic-degree rasters are rejected so
    pixel dimensions are not mistaken for physical ground distances. These
    are DEM-derived descriptors, not uncertainty-propagated estimates; source
    interpolation and vertical error are not modeled here.
    """
    with rasterio.open(dem_path) as src:
        if src.width < 3 or src.height < 3:
            raise ValueError("DEM grid must be at least 3x3 cells for terrain features")
        if src.crs is None or src.crs.is_geographic:
            raise ValueError("DEM must have a projected CRS with linear units")
        units = (src.crs.linear_units or "").lower()
        if "met" not in units:
            raise ValueError("DEM CRS axes must be expressed in metres")
        dx = float(np.hypot(src.transform.a, src.transform.d))
        dy = float(np.hypot(src.transform.b, src.transform.e))
        extent_x = float(np.hypot(src.transform.a * src.width, src.transform.d * src.width))
        extent_y = float(np.hypot(src.transform.b * src.height, src.transform.e * src.height))
        if dx <= 0 or dy <= 0:
            raise ValueError("DEM grid spacing must be positive")
        band = src.read(1, masked=True).astype(np.float64)
        values = band.filled(np.nan)
        valid = np.isfinite(values)
        if src.nodata is not None:
            valid &= values != src.nodata
        if valid.sum() < 9:
            raise ValueError("DEM has fewer than nine valid samples")

    # Use valid data for elevation range; gradients require complete neighbouring cells.
    elevation = values[valid]
    gy, gx = np.gradient(values, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    slope_valid = valid & np.isfinite(slope)
    slope_valid[[0, -1], :] = False
    slope_valid[:, [0, -1]] = False
    local_min = np.full(values.shape, np.nan)
    local_max = np.full(values.shape, np.nan)
    # The 3x3 footprint uses a physically explicit scale of approximately 3 pixels.
    from scipy.ndimage import maximum_filter, minimum_filter, uniform_filter

    filled = np.where(valid, values, np.nanmedian(elevation))
    local_min[:] = minimum_filter(filled, size=3, mode="nearest")
    local_max[:] = maximum_filter(filled, size=3, mode="nearest")
    relief = local_max - local_min
    relief_valid = slope_valid & (minimum_filter(valid.astype(np.uint8), size=3) == 1)
    relief_valid[[0, -1], :] = False
    relief_valid[:, [0, -1]] = False
    common = ProvenanceRecord(
        source_product_id=product_id,
        source_url=source_url,
        provider=provider,
        processing_method=processing_method,
    )
    slope_scale = 2.0 * max(dx, dy)
    relief_scale = 3.0 * max(dx, dy)
    complete = minimum_filter(valid.astype(np.uint8), size=3, mode="constant") == 1
    complete[[0, -1], :] = False
    complete[:, [0, -1]] = False
    neighborhood_mean = uniform_filter(filled, size=3, mode="nearest")
    roughness = np.abs(filled - neighborhood_mean)
    curvature = np.gradient(np.gradient(values, dx, axis=1), dx, axis=1) + np.gradient(
        np.gradient(values, dy, axis=0), dy, axis=0
    )
    curvature_valid = complete & np.isfinite(curvature)
    return [
        PhysicalMeasurement(
            name="elevation_range",
            value=float(np.max(elevation) - np.min(elevation)),
            units="m",
            availability=Availability.AVAILABLE,
            spatial_scale_m=max(extent_x, extent_y),
            uncertainty=Uncertainty(description="Input DEM uncertainty not supplied by adapter"),
            provenance=common,
        ),
        PhysicalMeasurement(
            name="mean_slope",
            value=float(np.mean(slope[slope_valid])),
            units="degree",
            availability=Availability.AVAILABLE,
            spatial_scale_m=slope_scale,
            uncertainty=Uncertainty(description="Derived from neighbouring DEM elevations"),
            provenance=common,
        ),
        PhysicalMeasurement(
            name="median_local_relief_3x3",
            value=float(np.median(relief[relief_valid])),
            units="m",
            availability=Availability.AVAILABLE,
            spatial_scale_m=relief_scale,
            uncertainty=Uncertainty(description="Derived from a 3x3 pixel moving window"),
            provenance=common,
        ),
        PhysicalMeasurement(
            name="slope_p90",
            value=float(np.percentile(slope[slope_valid], 90)),
            units="degree",
            availability=Availability.AVAILABLE,
            spatial_scale_m=slope_scale,
            uncertainty=Uncertainty(description="90th percentile of central-difference slope"),
            provenance=common,
        ),
        PhysicalMeasurement(
            name="median_roughness_3x3",
            value=float(np.median(roughness[complete])),
            units="m",
            availability=Availability.AVAILABLE,
            spatial_scale_m=relief_scale,
            uncertainty=Uncertainty(description="Median absolute deviation from the 3x3 mean"),
            provenance=common,
        ),
        PhysicalMeasurement(
            name="median_curvature",
            value=float(np.median(curvature[curvature_valid])),
            units="m^-1",
            availability=Availability.AVAILABLE,
            spatial_scale_m=3.0 * max(dx, dy),
            uncertainty=Uncertainty(
                description="Finite-difference Laplacian; grid-scale dependent"
            ),
            provenance=common,
        ),
    ]
