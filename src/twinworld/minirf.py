"""Small, bounded reader for the official LRO Mini-RF south-polar CPR mosaic."""

from __future__ import annotations

import math
import struct
from typing import Any

from twinworld.pds import read_byte_range as _read_pds_byte_range

DATASET_ID = "lro-mini-rf-south-polar-cpr"
PRODUCT_ID = "LSZ_XXXXX_3CP_PFU_90S000_V1"
LABEL_URL = (
    "https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/"
    "lromrf_0005/data/sar/mosaics/lsz_xxxxx_3cp_pfu_90s000_v1.lbl"
)
IMAGE_URL = LABEL_URL[:-4] + ".img"
GRID_SIZE = 1294
RECORD_BYTES = 5176
PIXEL_SCALE_KM = 0.94760470075467
MOON_RADIUS_KM = 1737.4
MAP_OFFSET = 647.5
NULL_BITS = {0xFF7FFFFB, 0xFF7FFFFC, 0xFF7FFFFD, 0xFF7FFFFE, 0xFF7FFFFF}


def polar_pixel(longitude_east_deg: float, latitude_deg: float) -> tuple[int, int]:
    """Return (column, row) for the label's south-polar stereographic grid."""
    if not (-90.0 <= latitude_deg <= -70.0):
        raise ValueError("Mini-RF south-polar mosaic covers latitudes -90 to -70 degrees")
    rho = 2.0 * MOON_RADIUS_KM * math.tan(
        math.pi / 4.0 - math.radians(abs(latitude_deg)) / 2.0
    )
    longitude = math.radians(longitude_east_deg % 360.0)
    x = rho * math.sin(longitude)
    y = rho * math.cos(longitude)
    column = round(MAP_OFFSET + x / PIXEL_SCALE_KM - 1.0)
    row = round(MAP_OFFSET - y / PIXEL_SCALE_KM - 1.0)
    if not (0 <= column < GRID_SIZE and 0 <= row < GRID_SIZE):
        raise ValueError("Coordinate falls outside the Mini-RF image grid")
    return column, row


def read_byte_range(url: str, start: int, end: int, timeout: int = 30) -> bytes:
    return _read_pds_byte_range(
        url, start, end, timeout=timeout, product_name=PRODUCT_ID
    )


def _float_is_valid(value_bytes: bytes) -> bool:
    return struct.unpack("<I", value_bytes)[0] not in NULL_BITS


def read_cpr_neighborhood(
    longitude_east_deg: float, latitude_deg: float, radius_pixels: int = 2
) -> dict[str, Any]:
    """Read only the rows and columns surrounding one site; CPR is dimensionless."""
    if radius_pixels < 0 or radius_pixels > 5:
        raise ValueError("radius_pixels must be between 0 and 5")
    column, row = polar_pixel(longitude_east_deg, latitude_deg)
    first_col, last_col = max(0, column - radius_pixels), min(GRID_SIZE - 1, column + radius_pixels)
    first_row, last_row = max(0, row - radius_pixels), min(GRID_SIZE - 1, row + radius_pixels)
    values: list[float] = []
    grid_values: list[list[float | None]] = []
    for line in range(first_row, last_row + 1):
        start = line * RECORD_BYTES + first_col * 4
        raw = read_byte_range(IMAGE_URL, start, start + (last_col - first_col + 1) * 4 - 1)
        grid_line: list[float | None] = []
        for offset in range(0, len(raw), 4):
            pixel = raw[offset : offset + 4]
            if _float_is_valid(pixel):
                value = struct.unpack("<f", pixel)[0]
                if math.isfinite(value):
                    values.append(value)
                    grid_line.append(value)
                else:
                    grid_line.append(None)
            else:
                grid_line.append(None)
        grid_values.append(grid_line)
    if not values:
        raise ValueError("Mini-RF CPR neighborhood has no valid measurements")
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    median = (
        sorted_values[middle]
        if len(sorted_values) % 2
        else (sorted_values[middle - 1] + sorted_values[middle]) / 2
    )
    return {
        "grid_column": column,
        "grid_row": row,
        "window_pixels": [last_col - first_col + 1, last_row - first_row + 1],
        "valid_pixel_count": len(values),
        "sample_count": (last_col - first_col + 1) * (last_row - first_row + 1),
        "median_cpr": median,
        "minimum_cpr": min(values),
        "maximum_cpr": max(values),
        "grid_values": grid_values,
    }
