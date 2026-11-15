"""Fetch small, scale-matched Copernicus DEM windows at Earth catalogue places."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coordinates
from rasterio.warp import transform_bounds

from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "cop-dem-glo-30"
MARS_RADIUS_M = 3_396_000.0
PIXEL_M = 2 * math.pi * MARS_RADIUS_M / (128 * 360)
CELLS = 22
CONTEXT_M = PIXEL_M * CELLS


def ingest(
    site: dict[str, object], catalog: Client | None = None, *, output_dir: Path | None = None
) -> dict[str, object]:
    latitude = float(str(site["latitude_deg"]))
    longitude_east = float(str(site["longitude_east_deg"]))
    longitude = (longitude_east + 180) % 360 - 180
    zone = min(60, max(1, int((longitude + 180) // 6) + 1))
    epsg = (32600 if latitude >= 0 else 32700) + zone
    target_crs = CRS.from_epsg(epsg)
    center_xs, center_ys = transform_coordinates("EPSG:4326", target_crs, [longitude], [latitude])
    center_x, center_y = center_xs[0], center_ys[0]
    transform = from_origin(center_x - CONTEXT_M / 2, center_y + CONTEXT_M / 2, PIXEL_M, PIXEL_M)
    bounds = transform_bounds(
        target_crs,
        "EPSG:4326",
        center_x - CONTEXT_M / 2,
        center_y - CONTEXT_M / 2,
        center_x + CONTEXT_M / 2,
        center_y + CONTEXT_M / 2,
        densify_pts=21,
    )
    service = catalog or Client.open(STAC_URL)
    matches = list(service.search(collections=[COLLECTION], bbox=list(bounds), limit=20).items())
    if not matches:
        raise RuntimeError(
            f"No Copernicus DEM tile intersects {site['id']} ({longitude}, {latitude})."
        )
    output_grid = np.full((CELLS, CELLS), np.nan, dtype=np.float32)
    urls = []
    product_ids = []
    for item in sorted(matches, key=lambda value: value.id):
        signed = pc.sign(item)
        url = signed.assets["data"].href
        try:
            with rasterio.open(url) as source:
                with WarpedVRT(
                    source,
                    crs=target_crs,
                    transform=transform,
                    width=CELLS,
                    height=CELLS,
                    resampling=rasterio.enums.Resampling.bilinear,
                ) as vrt:
                    sampled = vrt.read(1, masked=True).astype(np.float32).filled(np.nan)
                    valid = np.isfinite(sampled) & ~np.isfinite(output_grid)
                    output_grid[valid] = sampled[valid]
                    if valid.any():
                        urls.append(f"{STAC_URL}/collections/{COLLECTION}/items/{item.id}")
                        product_ids.append(item.id)
        except (rasterio.errors.RasterioError, OSError):
            continue
    valid_fraction = float(np.isfinite(output_grid).mean())
    if np.isfinite(output_grid).sum() < 9:
        raise RuntimeError(
            f"Copernicus DEM has insufficient valid coverage at {site['id']} "
            f"({valid_fraction:.1%})."
        )

    slug = str(site["id"]).replace("-", "_")
    output = (output_dir or ROOT / "data/terrain") / f"cop-dem-candidate-{slug}.tif"
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": CELLS,
        "height": CELLS,
        "count": 1,
        "dtype": "float32",
        "crs": target_crs,
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(output, "w", **profile) as destination:
        destination.write(output_grid, 1)
        destination.update_tags(
            source_product_ids=",".join(product_ids), body="Earth", place_id=site["id"]
        )
    source_url = urls[0]
    measurement_rows = [
        item.model_dump(mode="json")
        for item in terrain_features(
            output,
            observation_id="candidate_earth_" + slug,
            provider="Copernicus / Microsoft Planetary Computer",
            product_id=",".join(product_ids),
            source_url=source_url,
            processing_method=(
                "Candidate-region locator centred metric grid; Copernicus DEM GLO-30 "
                "warped to 22×22 at the Mars MOLA equatorial posting for exploratory "
                "cross-body comparison."
            ),
        )
    ]
    metadata = {
        "observation_id": "candidate_earth_" + slug,
        "place_id": site["id"],
        "body": "earth",
        "name": site["name"],
        "longitude_east_deg": longitude_east,
        "latitude_deg": latitude,
        "dataset_id": "cop-dem-glo-30",
        "provider": "Copernicus / Microsoft Planetary Computer",
        "source_product_id": ",".join(product_ids),
        "source_url": source_url,
        "source_catalog_urls": urls,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_resolution_m": 30,
        "output_pixel_size_m": [PIXEL_M, PIXEL_M],
        "context_size_m": CONTEXT_M,
        "processing_crs": target_crs.to_string(),
        "processing_method": (
            "Candidate place coordinate is an approximate regional locator; "
            "10.19 km Copernicus DEM window sampled to the MOLA posting."
        ),
        "observed_cell_fraction": valid_fraction,
        "valid_pixel_fraction": valid_fraction,
        "missing_data_semantics": (
            "Copernicus nodata preserved; missing cells are excluded from measurement calculations."
        ),
        "uncertainty_note": (
            "DEM-derived terrain metrics; source vertical uncertainty and "
            "cross-product terrain bias are not propagated."
        ),
        "output": str(output.relative_to(ROOT)),
        "measurements": measurement_rows,
    }
    output.with_suffix(".tif.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    catalogue = json.loads(
        (ROOT / "data/manifests/candidate-locations.json").read_text(encoding="utf-8")
    )
    targets = [item for item in catalogue["entries"] if item["body"] == "earth"]
    client = Client.open(STAC_URL)
    results = []
    for site in targets:
        try:
            result = ingest(site, catalog=client)
            results.append(
                {
                    "site": site["id"],
                    "coverage": result["valid_pixel_fraction"],
                    "status": "available",
                }
            )
        except (
            Exception
        ) as error:  # report per-location coverage without suppressing the other sites
            results.append(
                {"site": site["id"], "coverage": 0, "status": "unavailable", "reason": str(error)}
            )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
