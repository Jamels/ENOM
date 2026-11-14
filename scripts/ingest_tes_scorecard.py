"""Ingest a bounded MGS TES nightside thermal-inertia crop for a Mars site.

Thermal inertia is surfaced as planetary environmental evidence only. It is
not surface temperature and is excluded from terrain similarity and mission
suitability until a scientifically matched Earth data set is available.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS

from twinworld.pds import read_byte_range

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data"
PRODUCT_ID = "GLOBAL_TI_NIGHT_2007"
DATA_SET_ID = "MGS-M-TES-5-TIMAP-V1.0"
MAP_URL = f"{BASE_URL}/global_ti_night_2007.img"
LABEL_URL = f"{BASE_URL}/global_ti_night_2007.lbl"
MASK_URL = f"{BASE_URL}/global_ti_msk_night_2007.img"
MASK_LABEL_URL = f"{BASE_URL}/global_ti_msk_night_2007.lbl"
PPD = 20
LINES = 3600
SAMPLES = 7200
MAP_RECORD_BYTES = SAMPLES * 2
MASK_RECORD_BYTES = SAMPLES
MARS_RADIUS_M = 3_396_000.0
HALF_WIDTH = 4  # 8×8 native cells, approximately 23.7 km at the equator.


def _range_row(
    url: str,
    row: int,
    first_col: int,
    width: int,
    record_bytes: int,
    *,
    session: requests.Session,
) -> bytes:
    start = row * record_bytes + first_col * (2 if record_bytes == MAP_RECORD_BYTES else 1)
    byte_width = width * (2 if record_bytes == MAP_RECORD_BYTES else 1)
    end = start + byte_width - 1
    return read_byte_range(
        url,
        start,
        end,
        timeout=60,
        session=session,
        product_name="TES",
    )


def fetch_crop(
    longitude_east_deg: float,
    latitude_deg: float,
    *,
    session: requests.Session | None = None,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Fetch only the requested map and interpolation-mask rows."""
    if not -180.0 <= longitude_east_deg < 180.0:
        raise ValueError("longitude_east_deg must be in [-180, 180)")
    if not -89.0 <= latitude_deg <= 89.0:
        raise ValueError("latitude_deg must be in [-89, 89]")
    client = session or requests.Session()

    # PDS line/sample coordinates are one-based pixel centres. The TES map
    # stores southern rows first and reverses east longitude along samples.
    center_row = int(round(1800.5 + PPD * latitude_deg)) - 1
    center_col = int(round(3600.5 - PPD * longitude_east_deg)) - 1
    width = HALF_WIDTH * 2
    first_row = center_row - HALF_WIDTH + 1
    first_col = center_col - HALF_WIDTH
    if first_row < 0 or first_row + width > LINES or first_col < 0 or first_col + width > SAMPLES:
        raise ValueError("TES crop falls outside the product grid")

    ti_rows, mask_rows = [], []
    for row in range(first_row, first_row + width):
        ti_rows.append(
            np.frombuffer(
                _range_row(MAP_URL, row, first_col, width, MAP_RECORD_BYTES, session=client),
                dtype=">i2",
            ).astype(np.float32)
        )
        mask_rows.append(
            np.frombuffer(
                _range_row(MASK_URL, row, first_col, width, MASK_RECORD_BYTES, session=client),
                dtype="u1",
            ).copy()
        )

    # Convert PDS south-to-north rows / east-to-west samples to a north-up,
    # west-to-east raster. A mask value 0 denotes interpolation.
    values = np.flipud(np.fliplr(np.stack(ti_rows)))
    mask = np.flipud(np.fliplr(np.stack(mask_rows)))
    valid = (mask != 0) & (values >= 5) & (values <= 5000)
    values = np.where(valid, values, np.nan).astype(np.float32)
    if int(valid.sum()) < 4:
        raise RuntimeError("TES crop has fewer than four directly mapped pixels")
    return values, valid, first_col, first_row


def ingest(
    longitude_east_deg: float = 149.99156469757094,
    latitude_deg: float = -3.0,
    *,
    output_id: str = "mars_aeolis_nondune-01",
    session: requests.Session | None = None,
) -> dict[str, object]:
    if not output_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("output_id may contain only letters, numbers, underscores and hyphens")
    crop, valid, first_col, first_row = fetch_crop(
        longitude_east_deg, latitude_deg, session=session
    )
    values = crop[valid]
    # The PDS image spans 360° east-to-west; pixel centres are at 179.975°
    # and then descend. Derive the actual centre of the reversed crop.
    center_lon = (3600.0 - first_col - crop.shape[1] / 2) / PPD
    center_lon = ((center_lon + 180) % 360) - 180
    center_lat = (first_row + crop.shape[0] / 2 - 1800.0) / PPD
    pixel_y = np.pi * MARS_RADIUS_M / (180 * PPD)
    pixel_x_ground = pixel_y * np.cos(np.radians(center_lat))
    pixel_x_map = pixel_y
    crs = CRS.from_proj4(
        f"+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +R={MARS_RADIUS_M:g} +units=m +no_defs"
    )
    center_x = center_lon * np.pi * MARS_RADIUS_M / 180
    center_y = center_lat * np.pi * MARS_RADIUS_M / 180
    transform = Affine(
        pixel_x_map,
        0,
        center_x - crop.shape[1] * pixel_x_map / 2,
        0,
        -pixel_y,
        center_y + crop.shape[0] * pixel_y / 2,
    )
    output = ROOT / "data/terrain" / f"tes-{output_id}.tif"
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
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(crop, 1)
        dst.update_tags(
            source_product_id=PRODUCT_ID,
            source_url=MAP_URL,
            label_url=LABEL_URL,
            mask_url=MASK_URL,
            units="J/(m^2*K*sqrt(s))",
            processing_method=(
                "PDS3 MSB signed int16; bounded rows; mask-zero interpolated pixels excluded"
            ),
        )

    metadata: dict[str, object] = {
        "observation_id": output_id,
        "body": "mars",
        "dataset_id": "mgs-tes-derived-thermal-inertia",
        "provider": "NASA MGS TES / PDS Geosciences Node",
        "source_product_id": PRODUCT_ID,
        "data_set_id": DATA_SET_ID,
        "product_version": "PDS3 archive; product created 2007-01-30",
        "source_url": MAP_URL,
        "label_url": LABEL_URL,
        "mask_url": MASK_URL,
        "mask_label_url": MASK_LABEL_URL,
        "retrieved_at": date.today().isoformat(),
        "source_description": (
            "Nightside thermal inertia derived from TES bolometer temperature observations. "
            "The paired PDS mask identifies interpolated cells; only non-interpolated cells "
            "in the crop are summarized."
        ),
        "observation_period": "TES observations, 1999-02 through 2004-04 (orbits 1583–24346)",
        "longitude_east_deg": longitude_east_deg,
        "latitude_deg": latitude_deg,
        "native_resolution_m_at_equator": 2960.0,
        "context_size_m": float(crop.shape[0] * np.sqrt(pixel_x_ground * pixel_y)),
        "grid_shape": list(crop.shape),
        "valid_sample_count": int(valid.sum()),
        "sample_count": int(valid.size),
        "valid_sample_fraction": float(valid.mean()),
        "units": "J/(m^2*K*sqrt(s)); product values outside 5–5000 are not computed",
        "latitude_type": "planetocentric",
        "coordinate_reference_system": crs.to_string(),
        "data_coverage_note": (
            "Mask-zero cells are TES map values infilled by interpolation and excluded."
        ),
        "earth_comparison_status": "not_compared",
        "scorecard_role": "environmental_evidence_only; excluded from terrain ranking",
        "measurement": {
            "name": "Nightside derived surface thermal inertia",
            "value": float(np.median(values)),
            "units": "J/(m^2*K*sqrt(s))",
            "availability": "available",
            "spatial_scale_m": float(crop.shape[0] * np.sqrt(pixel_x_ground * pixel_y)),
            "summary": {
                "mean": float(np.mean(values)),
                "median": float(np.median(values)),
                "p10": float(np.percentile(values, 10)),
                "p90": float(np.percentile(values, 90)),
            },
            "uncertainty": {
                "description": (
                    "Global derived map at ~2.96 km/pixel; "
                    "no per-cell uncertainty is included here."
                )
            },
            "provenance": {
                "source_url": LABEL_URL,
                "source_product_id": PRODUCT_ID,
                "mask_url": MASK_URL,
            },
        },
        "output": str(output.relative_to(ROOT)),
    }
    output.with_suffix(".tif.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longitude", type=float, default=149.99156469757094)
    parser.add_argument("--latitude", type=float, default=-3.0)
    parser.add_argument("--output-id", default="mars_aeolis_nondune-01")
    args = parser.parse_args()
    print(json.dumps(ingest(args.longitude, args.latitude, output_id=args.output_id), indent=2))


if __name__ == "__main__":
    main()
