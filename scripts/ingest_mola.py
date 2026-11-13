"""Fetch a bounded MOLA MEGDR topography/count window for an indexed Mars crop."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS

from twinworld.records import read_jsonl
from twinworld.science import (
    Availability,
    PhysicalMeasurement,
    ProvenanceRecord,
    Uncertainty,
)

ROOT = Path(__file__).resolve().parents[1]
PDS_BASE = "https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg128"
PDS_PAGE = "https://pds-geosciences.wustl.edu/missions/mgs/megdr.html"
MARS_RADIUS_M = 3_396_000.0
PIXELS_PER_DEGREE = 128
TILE_COLUMNS = 90 * PIXELS_PER_DEGREE
TILE_ROWS = 44 * PIXELS_PER_DEGREE
PDS_PRODUCT_PREFIX = "urn:nasa:pds:mgs_mola_topography_derived:data_meg128"


def tile_for(longitude_east_deg: float, latitude_deg: float) -> tuple[str, float, float]:
    """Return a MEG128 tile basename and its west/north tile edges."""
    if not -44 <= latitude_deg < 44:
        raise ValueError("This bounded adapter currently supports MOLA tiles between 44S and 44N")
    longitude = longitude_east_deg % 360.0
    west = math.floor(longitude / 90.0) * 90.0
    if latitude_deg >= 0:
        north, lat_code = 44.0, "44n"
    else:
        north, lat_code = 0.0, "00n"
    return f"{lat_code}{int(west):03d}hb", west, north


def read_range_window(url: str, *, start_byte: int, end_byte: int) -> bytes:
    """Read one small verified HTTP range without accepting a full-file response."""
    response = requests.get(
        url,
        headers={"Range": f"bytes={start_byte}-{end_byte}"},
        stream=True,
        timeout=60,
    )
    try:
        if response.status_code != 206:
            raise RuntimeError(
                f"PDS server did not honor the byte-range request ({response.status_code})"
            )
        content_range = response.headers.get("Content-Range", "")
        expected_prefix = f"bytes {start_byte}-{end_byte}/"
        if not content_range.startswith(expected_prefix):
            raise RuntimeError(f"Unexpected PDS Content-Range: {content_range}")
        data = response.content
        if len(data) != end_byte - start_byte + 1:
            raise RuntimeError("PDS range response length does not match the requested interval")
        return data
    finally:
        response.close()


def _read_crop(
    url: str, row: int, column: int, *, width: int, height: int, bytes_per_sample: int, dtype: str
) -> np.ndarray:
    start_sample = row * TILE_COLUMNS + column
    end_sample = (row + height - 1) * TILE_COLUMNS + column + width - 1
    start_byte = start_sample * bytes_per_sample
    end_byte = (end_sample + 1) * bytes_per_sample - 1
    payload = read_range_window(url, start_byte=start_byte, end_byte=end_byte)
    row_bytes = TILE_COLUMNS * bytes_per_sample
    crop_bytes = width * bytes_per_sample
    return np.stack(
        [
            np.frombuffer(
                payload[index * row_bytes : index * row_bytes + crop_bytes], dtype=dtype
            ).copy()
            for index in range(height)
        ]
    )


def ingest(observation_id: str, output: Path, *, context_cells: int = 22) -> dict[str, object]:
    if context_cells < 5 or context_cells > 256:
        raise ValueError("context_cells must be between 5 and 256")
    manifest = read_jsonl(ROOT / "data/manifests/pilot-100.jsonl")
    record = next((item for item in manifest if item.image_id == observation_id), None)
    if record is None or record.body != "mars":
        raise ValueError("observation_id must identify a Mars observation in pilot-100")
    product_stem, west, north = tile_for(record.longitude, record.latitude)
    center_column = math.floor((record.longitude % 360.0 - west) * PIXELS_PER_DEGREE)
    center_row = math.floor((north - record.latitude) * PIXELS_PER_DEGREE)
    column = center_column - context_cells // 2
    row = center_row - context_cells // 2
    if (
        column < 0
        or row < 0
        or column + context_cells > TILE_COLUMNS
        or row + context_cells > TILE_ROWS
    ):
        raise ValueError("requested context window crosses the selected MOLA tile boundary")

    topo_id = f"megt{product_stem}"
    count_id = f"megc{product_stem}"
    topo_url = f"{PDS_BASE}/{topo_id}.img"
    counts_url = f"{PDS_BASE}/{count_id}.img"
    topography = _read_crop(
        topo_url,
        row,
        column,
        width=context_cells,
        height=context_cells,
        bytes_per_sample=2,
        dtype=">i2",
    )
    counts = _read_crop(
        counts_url,
        row,
        column,
        width=context_cells,
        height=context_cells,
        bytes_per_sample=1,
        dtype="u1",
    )
    observed = counts > 0
    if observed.sum() < 9:
        raise ValueError("fewer than nine MOLA grid cells have observed altimetry in this context")

    pixel_m = 2 * math.pi * MARS_RADIUS_M / (PIXELS_PER_DEGREE * 360)
    x_left = (west - 180.0) * math.pi * MARS_RADIUS_M / 180 + column * pixel_m
    y_top = north * math.pi * MARS_RADIUS_M / 180 - row * pixel_m
    crs = CRS.from_proj4(
        f"+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=180 +x_0=0 +y_0=0 "
        f"+R={MARS_RADIUS_M:g} +units=m +no_defs"
    )
    transform = Affine(pixel_m, 0, x_left, 0, -pixel_m, y_top)
    output.parent.mkdir(parents=True, exist_ok=True)
    masked = np.where(observed, topography, -32768).astype(np.int16)
    profile = {
        "driver": "GTiff",
        "width": context_cells,
        "height": context_cells,
        "count": 1,
        "dtype": "int16",
        "crs": crs,
        "transform": transform,
        "nodata": -32768,
        "compress": "deflate",
    }
    with rasterio.open(output, "w", **profile) as destination:
        destination.write(masked, 1)
        destination.update_tags(
            source_product_id=topo_id,
            source_count_product_id=count_id,
            source_url=topo_url,
            count_source_url=counts_url,
            body="Mars",
            reference_radius_m=MARS_RADIUS_M,
            grid_cells_with_observations=int(observed.sum()),
            grid_cell_count=int(observed.size),
            missing_data_semantics=(
                "Zero-count MEGDR bins masked; original interpolated values excluded"
            ),
        )
    counts_path = output.with_name(output.stem + "-counts.tif")
    count_profile = profile | {"dtype": "uint8", "nodata": None}
    with rasterio.open(counts_path, "w", **count_profile) as destination:
        destination.write(counts.astype(np.uint8), 1)

    observed_values = topography[observed].astype(np.float64)
    coverage_fraction = float(observed.sum() / observed.size)
    provenance = ProvenanceRecord(
        source_product_id=topo_id,
        source_url=topo_url,
        provider="NASA Planetary Data System Geosciences Node / MGS MOLA",
        processing_method=(
            "PDS4 MEG128 byte-range crop; count-grid mask excludes interpolated bins; "
            "range over observed median-topography cells"
        ),
    )
    measurement = PhysicalMeasurement(
        name="elevation_range",
        value=float(np.max(observed_values) - np.min(observed_values)),
        units="m",
        availability=Availability.AVAILABLE,
        spatial_scale_m=context_cells * pixel_m,
        uncertainty=Uncertainty(
            description=(
                f"Range uses observed MOLA bins only; {observed.sum()}/{observed.size} "
                f"bins ({coverage_fraction:.1%}) contain altimetry. Empty-bin interpolations "
                "are excluded; this sampled range does not estimate unsampled local extrema."
            )
        ),
        provenance=provenance,
    )
    metadata: dict[str, object] = {
        "observation_id": observation_id,
        "dataset_id": "mola-meg128",
        "provider": "NASA Planetary Data System Geosciences Node / MGS MOLA",
        "source_product_id": f"{PDS_PRODUCT_PREFIX}:{topo_id}",
        "counts_product_id": f"{PDS_PRODUCT_PREFIX}:{count_id}",
        "source_url": topo_url,
        "counts_source_url": counts_url,
        "dataset_reference_url": PDS_PAGE,
        "dataset_version": "PDS4 bundle label 1.1; MEGDR final topography product",
        "observation_period": "MGS MOLA mapping data, 1999-03-08 through 2001-06-30",
        "native_resolution_m_at_equator": pixel_m,
        "grid_crs": crs.to_string(),
        "grid_convention": (
            "Mars equirectangular, east longitude, central meridian 180 degrees, "
            "areocentric latitude"
        ),
        "context_size_m": context_cells * pixel_m,
        "context_cells": context_cells,
        "observed_cell_count": int(observed.sum()),
        "grid_cell_count": int(observed.size),
        "observed_cell_fraction": coverage_fraction,
        "zero_count_bins": int((~observed).sum()),
        "missing_data_semantics": (
            "PDS documentation says bins without observations contain interpolated topography; "
            "these bins are masked from terrain metrics"
        ),
        "processing_method": "Bounded PDS4 MEG128 topography and count window; no local CUDA",
        "terrain_raster": str(output.relative_to(ROOT)),
        "count_raster": str(counts_path.relative_to(ROOT)),
        "measurements": [measurement.model_dump(mode="json")],
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", default="mars-dune-barchan_crescent_dune-0067+071")
    parser.add_argument("--context-cells", type=int, default=22)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/terrain/mola-meg128-meroe-01.tif"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            ingest(args.observation, args.output, context_cells=args.context_cells), indent=2
        )
    )


if __name__ == "__main__":
    main()
