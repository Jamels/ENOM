"""Bounded PDS LOLA south-polar DEM and direct-shot crop reader."""

from __future__ import annotations

import math

import numpy as np
from rasterio.crs import CRS
from rasterio.warp import transform

from twinworld.lunar import MOON_REFERENCE_RADIUS_M, polar_stereographic_crs
from twinworld.pds import read_byte_range

LOLA_POLAR_BASE = (
    "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img"
)
DEM_PRODUCT = "LDEM_75S_120M"
COUNT_PRODUCT = "LDEC_75S_120M"
DEM_URL = f"{LOLA_POLAR_BASE}/ldem_75s_120m.img"
DEM_LABEL_URL = f"{LOLA_POLAR_BASE}/ldem_75s_120m.lbl"
COUNT_URL = f"{LOLA_POLAR_BASE}/ldec_75s_120m.img"
COUNT_LABEL_URL = f"{LOLA_POLAR_BASE}/ldec_75s_120m.lbl"
GRID_SIZE = 7624
RECORD_BYTES = GRID_SIZE * 2
NATIVE_PIXEL_M = 120.0
SAMPLE_PROJECTION_OFFSET = 3811.5
LINE_PROJECTION_OFFSET = 3811.5
DEM_MIN_DN = -15526
DEM_MAX_DN = 14050
COUNT_MAX_DN = 536
DEFAULT_HALF_WIDTH = 48
OUTPUT_SIZE = 22
OUTPUT_PIXEL_M = 463.05766716974557
MIN_DIRECT_SUPPORT_FRACTION = 0.25


def lunar_polar_pixel(longitude_east_deg: float, latitude_deg: float) -> tuple[int, int]:
    """Map a lunar lon/lat in the LOLA label frame to its nearest image pixel."""
    if not math.isfinite(longitude_east_deg) or not math.isfinite(latitude_deg):
        raise ValueError("lunar coordinates must be finite")
    if not -90.0 <= latitude_deg <= -75.0:
        raise ValueError("LOLA 75S polar product covers latitudes from 75S to the pole")
    longitude = longitude_east_deg % 360.0
    geographic = CRS.from_proj4(f"+proj=longlat +R={MOON_REFERENCE_RADIUS_M:g} +no_defs")
    projected = polar_stereographic_crs("south")
    xs, ys = transform(geographic, projected, [longitude], [latitude_deg])
    column = round(xs[0] / NATIVE_PIXEL_M + SAMPLE_PROJECTION_OFFSET)
    row = round(LINE_PROJECTION_OFFSET - ys[0] / NATIVE_PIXEL_M)
    if not (0 <= column < GRID_SIZE and 0 <= row < GRID_SIZE):
        raise ValueError("lunar coordinate falls outside the LOLA polar raster")
    return column, row


def read_lola_polar_crop(
    longitude_east_deg: float,
    latitude_deg: float,
    *,
    half_width_pixels: int = DEFAULT_HALF_WIDTH,
    session=None,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Range-read matching LOLA elevation and shot-count windows.

    Returns elevation metres relative to the LOLA 1,737.4 km sphere, a direct
    observation count array, and the first zero-based sample/line indices.
    Cells with zero direct shots are NaN in the elevation array, even where the
    gridded DEM contains a surface-interpolated value.
    """
    if isinstance(half_width_pixels, bool) or not 8 <= half_width_pixels <= 128:
        raise ValueError("half_width_pixels must be between 8 and 128")
    center_col, center_row = lunar_polar_pixel(longitude_east_deg, latitude_deg)
    width = 2 * half_width_pixels
    first_col = center_col - half_width_pixels
    first_row = center_row - half_width_pixels
    if (
        first_col < 0
        or first_row < 0
        or first_col + width > GRID_SIZE
        or first_row + width > GRID_SIZE
    ):
        raise ValueError("requested crop crosses the LOLA polar product edge")
    start_byte = first_row * RECORD_BYTES + first_col * 2
    end_byte = (first_row + width - 1) * RECORD_BYTES + (first_col + width) * 2 - 1

    def decode(url: str, product: str, dtype: str) -> np.ndarray:
        raw = read_byte_range(
            url, start_byte, end_byte, timeout=90, session=session, product_name=product
        )
        rows = [
            np.frombuffer(
                raw[offset * RECORD_BYTES : offset * RECORD_BYTES + width * 2],
                dtype=dtype,
                count=width,
            ).copy()
            for offset in range(width)
        ]
        return np.stack(rows)

    dem_dn = decode(DEM_URL, DEM_PRODUCT, "<i2")
    counts = decode(COUNT_URL, COUNT_PRODUCT, "<i2")
    if int(dem_dn.min()) < DEM_MIN_DN or int(dem_dn.max()) > DEM_MAX_DN:
        raise ValueError("LOLA elevation values exceed the PDS label's declared range")
    if int(counts.min()) < 0 or int(counts.max()) > COUNT_MAX_DN:
        raise ValueError("LOLA shot counts exceed the PDS label's declared range")
    elevation = dem_dn.astype(np.float32) * 0.5
    elevation[counts == 0] = np.nan
    if int(np.isfinite(elevation).sum()) < 9:
        raise ValueError("LOLA crop has fewer than nine directly observed elevation cells")
    return elevation, counts, first_col, first_row
