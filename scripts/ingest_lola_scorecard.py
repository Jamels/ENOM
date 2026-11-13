"""Fetch a bounded LRO LOLA GDR crop and compute scale-matched scorecard terrain."""

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
from rasterio.warp import Resampling, reproject

from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
BASE = (
    "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
    "lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG"
)
PRODUCT = "LDEM_64"
PRODUCT_URL = f"{BASE}/ldem_64.img"
LABEL_URL = f"{BASE}/ldem_64.lbl"
PPD = 64
LINES = 11520
SAMPLES = 23040
RECORD_BYTES = 46080
SCALE_FACTOR_M = 0.5
MINIMUM_DN = -18251
MAXIMUM_DN = 21546
LUNAR_RADIUS_M = 1_737_400.0
EARTH_GRID_M = 463.05766716974557


def fetch_lola_crop(
    longitude_east_deg: float, latitude_deg: float, *, half_width_pixels: int = 16
) -> tuple[np.ndarray, int, int]:
    """Read only a small byte-range window from the global PDS3 LDEM_64 image."""
    if not -75.0 <= latitude_deg <= 75.0:
        raise ValueError("This cylindrical crop adapter supports latitudes from 75S to 75N")
    if half_width_pixels < 8 or half_width_pixels > 128:
        raise ValueError("half_width_pixels must be between 8 and 128")
    longitude = longitude_east_deg % 360.0
    # PDS projection offsets are pixel registered: map coordinates at the pixel centres.
    center_col = int(round((longitude - 180.0) * PPD + (SAMPLES + 1) / 2 - 1))
    center_row = int(round((90.0 - latitude_deg) * PPD - 0.5))
    first_col, first_row = center_col - half_width_pixels, center_row - half_width_pixels
    width = height = 2 * half_width_pixels
    if first_col < 0 or first_col + width > SAMPLES:
        raise ValueError("Crop crosses the 0/360-degree longitude seam")
    if first_row < 0 or first_row + height > LINES:
        raise ValueError("Crop exceeds the LOLA latitude grid")

    start_byte = first_row * RECORD_BYTES + first_col * 2
    end_byte = (first_row + height - 1) * RECORD_BYTES + (first_col + width) * 2 - 1
    response = requests.get(
        PRODUCT_URL,
        headers={"Range": f"bytes={start_byte}-{end_byte}"},
        timeout=90,
    )
    response.raise_for_status()
    expected_range = f"bytes {start_byte}-{end_byte}/"
    if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(
        expected_range
    ):
        raise RuntimeError("PDS did not honor the bounded LOLA byte-range request")
    raw = response.content
    if len(raw) != end_byte - start_byte + 1:
        raise RuntimeError("LOLA byte-range response length does not match the requested window")
    rows = []
    for row_index in range(height):
        offset = row_index * RECORD_BYTES
        rows.append(np.frombuffer(raw[offset : offset + width * 2], dtype="<i2").copy())
    dn = np.stack(rows)
    if int(dn.min()) < MINIMUM_DN or int(dn.max()) > MAXIMUM_DN:
        raise RuntimeError(
            "LOLA sample falls outside the PDS label's declared product minimum/maximum"
        )
    elevations = dn.astype(np.float32) * SCALE_FACTOR_M
    if np.isfinite(elevations).sum() < 9:
        raise RuntimeError("The bounded LOLA crop has fewer than nine finite elevation samples")
    return elevations, first_col, first_row


def ingest(
    longitude_east_deg: float = 31.4,
    latitude_deg: float = 8.5,
    *,
    output_id: str = "moon_mare_tranquillitatis_01",
) -> dict[str, object]:
    """Create a source-traceable LOLA terrain context for a catalogue site."""
    if not output_id.replace("_", "").isalnum():
        raise ValueError("output_id may contain only letters, numbers and underscores")
    source, first_col, first_row = fetch_lola_crop(longitude_east_deg, latitude_deg)
    center_lat = 90.0 - (first_row + source.shape[0] / 2 + 0.5) / PPD
    center_lon = (first_col + source.shape[1] / 2 + 0.5) / PPD
    native_y_m = math.pi * LUNAR_RADIUS_M / (180 * PPD)
    native_x_m = native_y_m * math.cos(math.radians(center_lat))
    source_crs = CRS.from_proj4(
        f"+proj=eqc +lat_ts={center_lat:.10f} +lat_0=0 +lon_0=180 "
        f"+R={LUNAR_RADIUS_M:g} +units=m +no_defs"
    )
    target_crs = source_crs
    center_x = (
        (center_lon - 180.0) * math.pi * LUNAR_RADIUS_M / 180 * math.cos(math.radians(center_lat))
    )
    center_y = center_lat * math.pi * LUNAR_RADIUS_M / 180
    target_transform = Affine(
        EARTH_GRID_M,
        0,
        center_x - 11 * EARTH_GRID_M,
        0,
        -EARTH_GRID_M,
        center_y + 11 * EARTH_GRID_M,
    )
    source_transform = Affine(
        native_x_m,
        0,
        center_x - source.shape[1] / 2 * native_x_m,
        0,
        -native_y_m,
        center_y + source.shape[0] / 2 * native_y_m,
    )
    output = ROOT / "data/terrain" / f"{output_id}.tif"
    output.parent.mkdir(parents=True, exist_ok=True)
    projected = np.full((22, 22), np.nan, dtype=np.float32)
    reproject(
        source=source,
        destination=projected,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    if np.isfinite(projected).sum() < 9:
        raise RuntimeError("Fewer than nine valid LOLA samples remain after reprojection")
    profile = {
        "driver": "GTiff",
        "width": 22,
        "height": 22,
        "count": 1,
        "dtype": "float32",
        "crs": target_crs,
        "transform": target_transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(projected, 1)
        dst.update_tags(
            source_product_id=PRODUCT,
            source_url=PRODUCT_URL,
            label_url=LABEL_URL,
            data_set_id="LRO-L-LOLA-4-GDR-V1.0",
            output_pixel_size_m=EARTH_GRID_M,
            processing_crs=target_crs.to_string(),
            source_resolution_m=native_y_m,
            missing_data_semantics=(
                "PDS label defines no missing-value sentinel; no fill code is inferred; "
                "interpolation coverage is not quantified"
            ),
        )
    measurements = [
        item.model_dump(mode="json")
        for item in terrain_features(
            output,
            observation_id=output_id,
            provider="NASA LRO LOLA / PDS Geosciences Node",
            product_id=PRODUCT,
            source_url=PRODUCT_URL,
            processing_method=(
                "Bounded PDS3 LDEM_64 range read; DN × 0.5 m; bilinear reprojection "
                "to 22×22 cells at 463.0577 m in local lunar-radius equirectangular CRS"
            ),
        )
    ]
    metadata: dict[str, object] = {
        "observation_id": output_id,
        "body": "moon",
        "name": "Mare Tranquillitatis (scorecard terrain window)",
        "longitude_east_deg": longitude_east_deg,
        "latitude_deg": latitude_deg,
        "dataset_id": "lro-lola-gdr-ldem-64",
        "provider": "NASA LRO LOLA / PDS Geosciences Node",
        "source_product_id": PRODUCT,
        "data_set_id": "LRO-L-LOLA-4-GDR-V1.0",
        "source_url": PRODUCT_URL,
        "label_url": LABEL_URL,
        "retrieved_at": date.today().isoformat(),
        "observation_period": "2009-07-13 through 2016-11-29",
        "dataset_version": "PDS3 product V3.1; created 2019-03-15",
        "native_resolution_m_at_equator": 473.802,
        "output_pixel_size_m": EARTH_GRID_M,
        "context_size_m": 22 * EARTH_GRID_M,
        "crs": target_crs.to_string(),
        "units": (
            "m relative to LOLA 1737.4 km reference radius; constant offset cancels "
            "in local terrain derivatives"
        ),
        "valid_pixel_count": int(np.isfinite(projected).sum()),
        "grid_cell_count": int(projected.size),
        "valid_pixel_fraction": float(np.isfinite(projected).mean()),
        "observation_coverage": (
            "not quantified by the gridded product; production method includes "
            "surface interpolation"
        ),
        "missing_data_semantics": (
            "The PDS label defines no missing-value sentinel; no fill code is inferred. "
            "The gridded image does not distinguish interpolated from directly constrained cells."
        ),
        "uncertainty_note": (
            "LOLA GDR is a shape/radius map. Its label states gridding used surface "
            "interpolation in higher-resolution regions. Product does not supply a "
            "per-pixel confidence layer; measurement uncertainty is therefore unquantified."
        ),
        "processing_method": (
            "Bounded byte-range crop and metric-grid reprojection; no whole-planet file downloaded"
        ),
        "output": str(output.relative_to(ROOT)),
        "measurements": measurements,
    }
    sidecar = output.with_suffix(".tif.json")
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--longitude", type=float, default=31.4, help="East-positive lunar longitude"
    )
    parser.add_argument("--latitude", type=float, default=8.5)
    parser.add_argument("--output-id", default="moon_mare_tranquillitatis_01")
    args = parser.parse_args()
    print(json.dumps(ingest(args.longitude, args.latitude, output_id=args.output_id), indent=2))


if __name__ == "__main__":
    main()
