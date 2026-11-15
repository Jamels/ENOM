"""Bounded reader for LEND's averaged south-polar ALDS count-rate tables."""

from __future__ import annotations

import math
import struct
from typing import Any

from twinworld.pds import read_byte_range as _read_pds_byte_range

DATASET_ID = "lro-lend-south-polar-alds"
BASE_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lend-2-edr-v1/lrolen_0xxx/data"
ALDS_PRODUCTS = (
    {
        "product_id": "LEND_RDR_ALDS_20090915_DAT",
        "date_path": "2009/20090915",
        "start_time": "2009-09-15T00:00:00",
        "stop_time": "2011-12-11T00:00:00",
    },
    {
        "product_id": "LEND_RDR_ALDS_20111211_DAT",
        "date_path": "2011/20111211",
        "start_time": "2011-12-11T00:00:00",
        "stop_time": "2016-09-14T00:00:00",
    },
)
GRID_LATITUDE_BANDS = 20
GRID_LONGITUDE_BANDS = 720
GRID_STEP_DEG = 0.5
ROW_BYTES = 310
CSETN_EXPOSURE_OFFSET = 106
CSETN_RATE_OFFSET = 110
CSETN_ERROR_OFFSET = 114


def south_polar_grid_cell(longitude_east_deg: float, latitude_deg: float) -> tuple[int, int]:
    """Return (latitude band, longitude band) for the ALDS 0.5 degree grid."""
    if not math.isfinite(longitude_east_deg) or not math.isfinite(latitude_deg):
        raise ValueError("LEND coordinates must be finite")
    if not (-90.0 <= latitude_deg < -80.0):
        raise ValueError("LEND ALDS south-polar grid covers latitudes -90 to -80 degrees")
    lat_band = min(GRID_LATITUDE_BANDS - 1, int((latitude_deg + 90.0) / GRID_STEP_DEG))
    lon_band = int((longitude_east_deg % 360.0) / GRID_STEP_DEG)
    return lat_band, lon_band


def read_alds_cell(
    longitude_east_deg: float,
    latitude_deg: float,
    product: dict[str, str],
) -> dict[str, Any]:
    """Read one 310-byte map-cell record, preserving the product's missing values."""
    lat_band, lon_band = south_polar_grid_cell(longitude_east_deg, latitude_deg)
    record_index = lat_band * GRID_LONGITUDE_BANDS + lon_band
    filename = f"lend_rdr_alds_{product['date_path'][-8:]}.dat"
    url = f"{BASE_URL}/{product['date_path']}/{filename}"
    raw = _read_pds_byte_range(
        url,
        record_index * ROW_BYTES,
        (record_index + 1) * ROW_BYTES - 1,
        timeout=30,
        product_name=product["product_id"],
    )
    if len(raw) != ROW_BYTES:
        raise OSError("LEND ALDS record did not match the 310-byte PDS row")
    start = raw[:23].decode("ascii").strip()
    stop = raw[23:46].decode("ascii").strip()
    cell_latitude, cell_longitude = struct.unpack(">ff", raw[46:54])
    expected_latitude = -89.75 + lat_band * GRID_STEP_DEG
    expected_longitude = 0.25 + lon_band * GRID_STEP_DEG
    if (
        abs(cell_latitude - expected_latitude) > 1e-4
        or abs(cell_longitude - expected_longitude) > 1e-4
    ):
        raise ValueError("LEND ALDS record coordinates do not match the requested grid cell")
    exposure, rate, error = struct.unpack(
        ">fff",
        raw[CSETN_EXPOSURE_OFFSET : CSETN_ERROR_OFFSET + 4],
    )
    observed = (
        all(math.isfinite(item) for item in (exposure, rate, error))
        and exposure > 0
        and rate >= 0
        and error >= 0
    )
    return {
        "product_id": product["product_id"],
        "source_url": url.replace(".dat", ".lbl"),
        "grid_cell": {"latitude_deg": cell_latitude, "longitude_east_deg": cell_longitude},
        "grid_spacing_deg": GRID_STEP_DEG,
        "record_index": record_index,
        "temporal_coverage": f"{start} to {stop}",
        "exposure_field_value": exposure,
        "value": rate if observed else None,
        "statistical_error": error if observed else None,
        "availability": "available" if observed else "not_observed",
        "measurement_name": "LEND CSETN normalized neutron count rate",
        "units": "counts/s",
        "uncertainty": (
            "CSETN_ERR is the product's statistical error for this map cell; it "
            "does not include all spatial-footprint or systematic uncertainty."
        ),
        "interpretation": (
            "LEND neutron measurements can provide indirect context for lunar "
            "hydrogen. This count-rate product does not directly measure water "
            "or ice, and it is not a usable-resource estimate."
        ),
    }
