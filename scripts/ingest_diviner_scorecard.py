"""Fetch a bounded Diviner nighttime regolith-temperature crop for a Moon site.

The adapter reads one window from a public PDS3 IMG by HTTP byte range. The
product is shown as lunar environmental evidence and is not mixed into the
terrain similarity score.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS

from twinworld.pds import read_byte_range

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "DGDR_ST_CLC_CYL_20120114N_128_IMG"
DATA_SET_ID = "LRO-L-DLRE-5-GDR-V1.0"
PRODUCT_VERSION = "PDS3 V6.0"
BASE_URL = (
    "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/"
    "data_derived_gdr_l3/2012/cylindrical/img"
)
PRODUCT_URL = f"{BASE_URL}/{PRODUCT_ID.lower()}.img"
LABEL_URL = f"{BASE_URL}/{PRODUCT_ID.lower()}.lbl"
PPD = 128
LINES = 20_480
SAMPLES = 46_080
RECORD_BYTES = 92_160
MISSING_DN = -32_768
SCALE_K = 0.02
LUNAR_RADIUS_M = 1_737_400.0
HALF_WIDTH_PIXELS = 22  # 44×44 samples span about 10.3 km near the demo site.


def fetch_crop(
    longitude_east_deg: float,
    latitude_deg: float,
    *,
    session: requests.Session | None = None,
) -> tuple[np.ndarray, int, int]:
    """Read a local 44×44 sample window; never download the global IMG."""
    if not 0.0 <= longitude_east_deg < 360.0:
        raise ValueError("longitude_east_deg must be in [0, 360)")
    if not -80.0 <= latitude_deg <= 80.0:
        raise ValueError("Diviner ST CLC coverage is limited to 80S–80N")

    width = 2 * HALF_WIDTH_PIXELS
    center_col = int(round(longitude_east_deg * PPD - 0.5))
    center_row = int(round((80.0 - latitude_deg) * PPD - 0.5))
    first_col, first_row = center_col - HALF_WIDTH_PIXELS, center_row - HALF_WIDTH_PIXELS
    if first_col < 0 or first_col + width > SAMPLES:
        raise ValueError("Diviner crop crosses the 0/360-degree longitude seam")
    if first_row < 0 or first_row + width > LINES:
        raise ValueError("Diviner crop exceeds the product latitude grid")

    start = first_row * RECORD_BYTES + first_col * 2
    end = (first_row + width - 1) * RECORD_BYTES + (first_col + width) * 2 - 1
    client = session or requests.Session()
    raw = read_byte_range(
        PRODUCT_URL,
        start,
        end,
        timeout=90,
        session=client,
        product_name="Diviner",
    )
    rows = [
        np.frombuffer(
            raw[row * RECORD_BYTES : row * RECORD_BYTES + width * 2], dtype="<i2"
        ).copy()
        for row in range(width)
    ]
    dn = np.stack(rows)
    valid = dn != MISSING_DN
    temperature = np.where(valid, dn.astype(np.float32) * SCALE_K, np.nan)
    if int(valid.sum()) < 9:
        raise RuntimeError("The Diviner crop has fewer than nine valid temperature samples")
    if float(np.nanmin(temperature)) < 40 or float(np.nanmax(temperature)) > 178:
        raise RuntimeError("Diviner samples fall outside the PDS label's derived range")
    return temperature, first_col, first_row


def ingest(
    longitude_east_deg: float = 31.4,
    latitude_deg: float = 8.5,
    *,
    output_id: str = "moon_mare_tranquillitatis_01",
    session: requests.Session | None = None,
) -> dict[str, object]:
    """Write the measured crop and provenance sidecar for one lunar site."""
    if not output_id.replace("_", "").isalnum():
        raise ValueError("output_id may contain only letters, numbers and underscores")
    crop, first_col, first_row = fetch_crop(
        longitude_east_deg, latitude_deg, session=session
    )
    valid = np.isfinite(crop)
    values = crop[valid]
    center_lat = 80.0 - (first_row + crop.shape[0] / 2) / PPD
    center_lon = (first_col + crop.shape[1] / 2) / PPD
    pixel_y = math.pi * LUNAR_RADIUS_M / (180 * PPD)
    pixel_x = pixel_y * math.cos(math.radians(center_lat))
    crs = CRS.from_proj4(
        f"+proj=eqc +lat_ts={center_lat:.10f} +lat_0=0 +lon_0=180 "
        f"+R={LUNAR_RADIUS_M:g} +units=m +no_defs"
    )
    center_x = (center_lon - 180.0) * math.pi * LUNAR_RADIUS_M / 180 * math.cos(
        math.radians(center_lat)
    )
    center_y = center_lat * math.pi * LUNAR_RADIUS_M / 180
    transform = Affine(
        pixel_x,
        0,
        center_x - crop.shape[1] / 2 * pixel_x,
        0,
        -pixel_y,
        center_y + crop.shape[0] / 2 * pixel_y,
    )
    output = ROOT / "data/terrain" / f"diviner_{output_id}.tif"
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": crop.shape[1],
        "height": crop.shape[0],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(output, "w", **profile) as destination:
        destination.write(crop, 1)
        destination.update_tags(
            source_product_id=PRODUCT_ID,
            source_url=PRODUCT_URL,
            label_url=LABEL_URL,
            units="K",
            local_time_filter="19:30 through 05:30",
            processing_method="PDS3 little-endian int16 DN × 0.02 K; bounded byte-range crop",
        )

    measurement = {
        "name": "Nighttime rock-free regolith surface temperature",
        "value": float(np.median(values)),
        "units": "K",
        "availability": "available",
        "spatial_scale_m": float(crop.shape[0] * math.sqrt(pixel_x * pixel_y)),
        "summary": {
            "mean_k": float(np.mean(values)),
            "median_k": float(np.median(values)),
            "p10_k": float(np.percentile(values, 10)),
            "p90_k": float(np.percentile(values, 90)),
        },
        "uncertainty": {
            "description": (
                "Product-derived rock-free regolith temperature, not a direct in-situ "
                "measurement. The PDS label reports most surfaces have only one observation; "
                "per-pixel uncertainty and repeat-observation counts are not supplied here."
            )
        },
        "provenance": {"source_url": LABEL_URL, "source_product_id": PRODUCT_ID},
    }
    metadata: dict[str, object] = {
        "observation_id": output_id,
        "body": "moon",
        "dataset_id": "lro-diviner-gdr-level3-st-clc",
        "provider": "NASA LRO Diviner / PDS Geosciences Node",
        "source_product_id": PRODUCT_ID,
        "data_set_id": DATA_SET_ID,
        "product_version": PRODUCT_VERSION,
        "source_url": PRODUCT_URL,
        "label_url": LABEL_URL,
        "retrieved_at": date.today().isoformat(),
        "product_start_time": "2012-01-14T08:43:24.167Z",
        "product_stop_time": "2012-02-10T15:57:54.922Z",
        "source_description": (
            "The product algorithm uses Diviner data acquired 2009-07-05 through "
            "2016-10-10, local times 19:30–05:30, solar incidence >90°, emission angle "
            "<15°, and its stated temperature and quality filters."
        ),
        "longitude_east_deg": longitude_east_deg,
        "latitude_deg": latitude_deg,
        "source_resolution_m_at_equator": 236.901175,
        "context_size_m": float(crop.shape[0] * math.sqrt(pixel_x * pixel_y)),
        "grid_shape": list(crop.shape),
        "valid_sample_count": int(valid.sum()),
        "sample_count": int(valid.size),
        "valid_sample_fraction": float(valid.mean()),
        "units": "K; signed 16-bit little-endian DN × 0.02 K; -32768 is missing",
        "latitude_type": "planetocentric",
        "coordinate_reference_system": crs.to_string(),
        "data_coverage_note": (
            "Valid fraction is the fraction of non-missing raster cells, not observation "
            "count or independent spatial support."
        ),
        "earth_comparison_status": "not_compared",
        "scorecard_role": "environmental_evidence_only; excluded from terrain ranking",
        "measurement": measurement,
        "output": str(output.relative_to(ROOT)),
    }
    sidecar = output.with_suffix(".tif.json")
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longitude", type=float, default=31.4)
    parser.add_argument("--latitude", type=float, default=8.5)
    parser.add_argument("--output-id", default="moon_mare_tranquillitatis_01")
    args = parser.parse_args()
    print(
        json.dumps(
            ingest(args.longitude, args.latitude, output_id=args.output_id), indent=2
        )
    )


if __name__ == "__main__":
    main()
