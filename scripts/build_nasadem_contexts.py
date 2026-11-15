"""Derive reproducible Earth contexts from locally available NASADEM ZIP tiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform

from scripts.ingest_nasadem_scorecard import _read_members
from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
PIXEL = 463.05766716974557
DOI = "https://doi.org/10.5067/MEASURES/NASADEM/NASADEM_HGT.001"


def build(archives: Path, destination: Path) -> dict[str, object]:
    destination.mkdir(parents=True, exist_ok=True)
    completed = []
    failures = []
    for archive in sorted(archives.glob("NASADEM_HGT_*.zip")):
        tile = archive.stem.removeprefix("NASADEM_HGT_").lower()
        try:
            south = int(tile[1:3]) * (-1 if tile[0] == "s" else 1)
            west = int(tile[4:7]) * (-1 if tile[3] == "w" else 1)
            heights, num, water = _read_members(archive, tile)
            heights[(heights <= -32768) | (water == 255) | (num == 0)] = np.nan
            source_transform = Affine(
                1 / 3600, 0, west - 0.5 / 3600, 0, -1 / 3600, south + 1 + 0.5 / 3600
            )
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            # Remain well inside each tile to avoid source-edge artifacts.
            for lat_step in range(9):
                for lon_step in range(9):
                    lat_fraction = 0.1 + lat_step * 0.1
                    lon_fraction = 0.1 + lon_step * 0.1
                    latitude, longitude = south + lat_fraction, west + lon_fraction
                    zone = int((longitude + 180) // 6) + 1
                    crs = CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)
                    xs, ys = transform("EPSG:4326", crs, [longitude], [latitude])
                    grid = from_origin(xs[0] - 11 * PIXEL, ys[0] + 11 * PIXEL, PIXEL, PIXEL)
                    output = np.full((22, 22), np.nan, dtype="float32")
                    reproject(
                        heights,
                        output,
                        src_transform=source_transform,
                        src_crs="EPSG:4326",
                        src_nodata=np.nan,
                        dst_transform=grid,
                        dst_crs=crs,
                        dst_nodata=np.nan,
                        resampling=Resampling.bilinear,
                    )
                    fraction = float(np.isfinite(output).mean())
                    if fraction < 0.9:
                        continue
                    name = f"nasadem_{tile}_{lat_step:02d}_{lon_step:02d}"
                    raster = destination / f"{name}.tif"
                    with rasterio.open(
                        raster,
                        "w",
                        driver="GTiff",
                        width=22,
                        height=22,
                        count=1,
                        dtype="float32",
                        crs=crs,
                        transform=grid,
                        nodata=np.nan,
                        compress="deflate",
                    ) as dst:
                        dst.write(output, 1)
                    measurements = [
                        m.model_dump(mode="json")
                        for m in terrain_features(
                            raster,
                            observation_id=name,
                            provider="NASA LP DAAC / NASADEM HGT",
                            product_id=f"NASADEM_HGT_{tile}",
                            source_url=DOI,
                            processing_method=(
                                "NASADEM HGT with water and zero-source masks, "
                                "bilinear reprojection to metric grid"
                            ),
                        )
                    ]
                    metadata = {
                        "observation_id": name,
                        "body": "earth",
                        "name": f"NASADEM {tile} · {latitude:.2f}, {longitude:.2f}",
                        "dataset_id": "nasadem-hgt",
                        "provider": "NASA LP DAAC / NASADEM HGT",
                        "source_product_id": f"NASADEM_HGT_{tile}",
                        "dataset_version": "001",
                        "source_url": DOI,
                        "source_sha256": checksum,
                        "latitude_deg": latitude,
                        "longitude_east_deg": longitude % 360,
                        "valid_pixel_fraction": fraction,
                        "context_size_m": 22 * PIXEL,
                        "processing_method": (
                            "Local NASADEM HGT, zero-source and water cells masked; "
                            "bilinear resampling to metric 22×22 grid"
                        ),
                        "missing_data_semantics": (
                            "Void, water and zero source-count cells excluded"
                        ),
                        "uncertainty_note": (
                            "Source vertical error and interpolation effects not propagated"
                        ),
                        "output": str(raster.relative_to(ROOT)),
                        "measurements": measurements,
                    }
                    raster.with_suffix(".tif.json").write_text(
                        json.dumps(metadata, indent=2) + "\n"
                    )
                    completed.append(name)
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append({"archive": archive.name, "error": str(exc)})
    manifest = {
        "version": 1,
        "sampling": "9x9 per source tile; centres 0.10 to 0.90 degrees from tile edges",
        "contexts": completed,
        "failures": failures,
    }
    temporary = destination / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination / "manifest.json")
    return {
        "contexts": len(completed),
        "tiles": len(list(archives.glob("NASADEM_HGT_*.zip"))),
        "failures": failures,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", type=Path, default=ROOT / "data/earthdata-scraper/nasadem")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/discovery/nasadem")
    args = parser.parse_args()
    print(json.dumps(build(args.archives, args.output), indent=2))
