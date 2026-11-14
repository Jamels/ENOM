"""Ingest bounded LOLA south-polar DEM and direct-shot crops for ENOM sites."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject

from twinworld.lola_polar import (
    COUNT_LABEL_URL,
    COUNT_URL,
    DEM_LABEL_URL,
    DEM_PRODUCT,
    DEM_URL,
    MIN_DIRECT_SUPPORT_FRACTION,
    NATIVE_PIXEL_M,
    OUTPUT_PIXEL_M,
    OUTPUT_SIZE,
    SAMPLE_PROJECTION_OFFSET,
    LINE_PROJECTION_OFFSET,
    read_lola_polar_crop,
)
from twinworld.lunar import polar_stereographic_crs
from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"


def ingest_candidate(candidate: dict[str, object]) -> dict[str, object]:
    place_id = str(candidate["id"])
    longitude = float(candidate["longitude_east_deg"])
    latitude = float(candidate["latitude_deg"])
    slug = place_id.replace("-", "_")
    observation_id = f"lola_polar_{slug}"
    elevation, counts, first_col, first_row = read_lola_polar_crop(longitude, latitude)

    source_crs = polar_stereographic_crs("south")
    xs, ys = rasterio.warp.transform(
        rasterio.crs.CRS.from_proj4("+proj=longlat +R=1737400 +no_defs"),
        source_crs,
        [longitude % 360.0],
        [latitude],
    )
    center_x, center_y = xs[0], ys[0]
    source_transform = Affine(
        NATIVE_PIXEL_M,
        0,
        (first_col - SAMPLE_PROJECTION_OFFSET - 0.5) * NATIVE_PIXEL_M,
        0,
        -NATIVE_PIXEL_M,
        (LINE_PROJECTION_OFFSET - first_row + 0.5) * NATIVE_PIXEL_M,
    )
    target_transform = Affine(
        OUTPUT_PIXEL_M,
        0,
        center_x - OUTPUT_SIZE * OUTPUT_PIXEL_M / 2,
        0,
        -OUTPUT_PIXEL_M,
        center_y + OUTPUT_SIZE * OUTPUT_PIXEL_M / 2,
    )

    support = (counts > 0).astype(np.float32)
    support_fraction = np.full((OUTPUT_SIZE, OUTPUT_SIZE), -9999.0, dtype=np.float32)
    reproject(
        source=support,
        destination=support_fraction,
        src_transform=source_transform,
        src_crs=source_crs,
        dst_transform=target_transform,
        dst_crs=source_crs,
        src_nodata=None,
        dst_nodata=-9999.0,
        resampling=Resampling.average,
    )
    projected = np.full((OUTPUT_SIZE, OUTPUT_SIZE), np.nan, dtype=np.float32)
    reproject(
        source=elevation,
        destination=projected,
        src_transform=source_transform,
        src_crs=source_crs,
        dst_transform=target_transform,
        dst_crs=source_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    valid = np.isfinite(support_fraction) & (support_fraction >= MIN_DIRECT_SUPPORT_FRACTION)
    projected[~valid] = np.nan
    if int(np.isfinite(projected).sum()) < 9:
        raise ValueError(
            f"{place_id} has fewer than nine output cells with "
            f">={MIN_DIRECT_SUPPORT_FRACTION:.0%} direct LOLA support"
        )

    terrain_dir = ROOT / "data/terrain"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    dem_path = terrain_dir / f"{observation_id}.tif"
    count_path = terrain_dir / f"{observation_id}-counts.tif"
    raster_profile = {
        "driver": "GTiff",
        "width": OUTPUT_SIZE,
        "height": OUTPUT_SIZE,
        "count": 1,
        "dtype": "float32",
        "crs": source_crs,
        "transform": target_transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(dem_path, "w", **raster_profile) as dst:
        dst.write(projected, 1)
        dst.update_tags(
            source_product_id=DEM_PRODUCT,
            source_url=DEM_URL,
            counts_source_url=COUNT_URL,
            source_resolution_m=NATIVE_PIXEL_M,
            output_pixel_size_m=OUTPUT_PIXEL_M,
            processing_crs=source_crs.to_string(),
            missing_data_semantics=(
                "Cells with less than 25% directly observed 120 m LOLA source pixels "
                "inside the output cell are masked; the original LDEC support crop is retained."
            ),
        )
    count_profile = {
        **raster_profile,
        "width": counts.shape[1],
        "height": counts.shape[0],
        "dtype": "int16",
        "transform": source_transform,
        "nodata": -1,
    }
    with rasterio.open(count_path, "w", **count_profile) as dst:
        dst.write(counts.astype(np.int16), 1)
        dst.update_tags(
            source_product_id="LDEC_75S_120M",
            source_url=COUNT_URL,
            label_url=COUNT_LABEL_URL,
            native_pixel_size_m=NATIVE_PIXEL_M,
            crs=source_crs.to_string(),
            meaning="Number of LOLA altimeter observations used per 120 m polar grid cell.",
        )

    measurements = [
        item.model_dump(mode="json")
        for item in terrain_features(
            dem_path,
            observation_id=observation_id,
            provider="NASA LRO LOLA / PDS Geosciences Node",
            product_id=DEM_PRODUCT,
            source_url=DEM_URL,
            processing_method=(
                "Bounded PDS3 HTTP range reads of the 120 m LDEM and paired LDEC shot-count "
                "products; elevation is DN × 0.5 m; direct-support fraction is averaged into "
                "the 463.0577 m comparison grid; cells below 25% are excluded."
            ),
        )
    ]
    observed_count = int(valid.sum())
    metadata: dict[str, object] = {
        "observation_id": observation_id,
        "place_id": place_id,
        "body": "moon",
        "name": f"LOLA south-polar terrain · {candidate['name']}",
        "latitude_deg": latitude,
        "longitude_east_deg": longitude,
        "location_precision": "candidate_region_locator",
        "spatial_relation": (
            "The candidate coordinate is a regional locator from the candidate catalogue, "
            "not a landing ellipse or rover traverse."
        ),
        "dataset_id": "lro-lola-gdr-polar-ldem-120m",
        "provider": "NASA LRO LOLA / PDS Geosciences Node",
        "source_product_id": DEM_PRODUCT,
        "count_product_id": "LDEC_75S_120M",
        "data_set_id": "LRO-L-LOLA-4-GDR-V1.0",
        "source_url": DEM_URL,
        "label_url": DEM_LABEL_URL,
        "counts_source_url": COUNT_URL,
        "counts_label_url": COUNT_LABEL_URL,
        "retrieved_at": date.today().isoformat(),
        "observation_period": "LOLA data acquired through 2017-02-02; PDS polar DEM product V2.1",
        "native_resolution_m": NATIVE_PIXEL_M,
        "output_pixel_size_m": OUTPUT_PIXEL_M,
        "context_size_m": OUTPUT_SIZE * OUTPUT_PIXEL_M,
        "crs": source_crs.to_string(),
        "processing_crs": source_crs.to_string(),
        "coordinate_frame": "Mean Earth / polar axis of DE421; planetocentric latitude; east-positive longitude",
        "units": "m relative to the LOLA 1,737.4 km reference sphere",
        "observed_cell_count": observed_count,
        "grid_cell_count": int(valid.size),
        "observed_cell_fraction": float(observed_count / valid.size),
        "native_count_crop_fraction": float((counts > 0).mean()),
        "minimum_direct_support_fraction_per_output_cell": MIN_DIRECT_SUPPORT_FRACTION,
        "count_raster": str(count_path.relative_to(ROOT)),
        "observation_coverage": (
            "Paired LDEC product gives direct observation counts at 120 m. Output DEM cells "
            "are retained only when at least 25% of the contributing native grid is directly observed."
        ),
        "missing_data_semantics": (
            "LDEC count 0 means no direct LOLA observations contributed to that native cell; "
            "such cells are not used as elevation evidence."
        ),
        "uncertainty_note": (
            "Direct-shot counts describe support, not vertical uncertainty. The PDS product "
            "does not provide a per-cell elevation uncertainty layer; vertical error is not propagated."
        ),
        "processing_method": (
            "Only the selected 96×96 native-cell windows were fetched by verified HTTP byte-range "
            "requests; no whole polar raster was downloaded. DEM elevations were averaged to the "
            "463.0577 m comparison grid after masking unsupported source cells."
        ),
        "output": str(dem_path.relative_to(ROOT)),
        "measurements": measurements,
    }
    dem_path.with_suffix(".tif.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    candidates = [
        entry
        for entry in catalogue["entries"]
        if entry.get("body") == "moon" and entry.get("candidate_type") == "lunar_south_polar"
    ]
    results = []
    for candidate in candidates:
        try:
            metadata = ingest_candidate(candidate)
            results.append({
                "place_id": candidate["id"],
                "status": "available",
                "observed_cell_fraction": metadata["observed_cell_fraction"],
                "native_count_crop_fraction": metadata["native_count_crop_fraction"],
            })
        except Exception as error:
            results.append({"place_id": candidate["id"], "status": "unavailable", "reason": str(error)})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
