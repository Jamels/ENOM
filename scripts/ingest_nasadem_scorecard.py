"""Ingest one NASADEM HGT tile into a bounded Earth terrain scorecard context.

The selected 1-degree granule is downloaded once and cached. NASA Earthdata Login
is required; provide a short-lived Personal Access Token in EARTHDATA_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import zipfile
from collections import Counter
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

from twinworld.records import read_jsonl
from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/pilot-100.jsonl"
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
NASADEM_DOI = "https://doi.org/10.5067/MEASURES/NASADEM/NASADEM_HGT.001"
NASADEM_GUIDE = "https://lpdaac.usgs.gov/documents/2237/NASADEM_User_Guide_V13.pdf"
PIXELS_PER_DEGREE = 3600
TILE_SAMPLES = PIXELS_PER_DEGREE + 1
EARTH_GRID_M = 463.05766716974557
DEFAULT_CONTEXT_SIZE_M = 22 * EARTH_GRID_M
MAX_TILE_BYTES = 64 * 1024 * 1024
PROVIDER = "NASA LP DAAC / NASADEM HGT"


def tile_name(longitude_deg: float, latitude_deg: float) -> str:
    """Return the NASADEM HGT southwest-corner tile ID for an Earth point."""
    if not -56 <= latitude_deg < 60:
        raise ValueError("NASADEM HGT coverage is limited to 56S–60N")
    if not -180 <= longitude_deg < 180:
        raise ValueError("Earth longitude must be in [-180, 180)")
    south, west = math.floor(latitude_deg), math.floor(longitude_deg)
    return f"{'n' if south >= 0 else 's'}{abs(south):02d}{'e' if west >= 0 else 'w'}{abs(west):03d}"


def _granule(tile: str) -> dict[str, str]:
    south = int(tile[1:3]) * (1 if tile[0] == "n" else -1)
    west = int(tile[4:7]) * (1 if tile[3] == "e" else -1)
    response = requests.get(
        CMR_URL,
        params={
            "short_name": "NASADEM_HGT",
            "version": "001",
            "page_size": 10,
            "bounding_box": f"{west},{south},{west + 1},{south + 1}",
        },
        timeout=30,
    )
    response.raise_for_status()
    entries = response.json().get("feed", {}).get("entry", [])
    title = f"NASADEM_HGT_{tile}"
    entry = next((item for item in entries if item.get("producer_granule_id") == title), None)
    if entry is None:
        raise RuntimeError(f"NASA CMR has no NASADEM_HGT granule for {tile}")
    data_link = next(
        (
            link["href"]
            for link in entry.get("links", [])
            if link.get("title", "").startswith("Download NASADEM_HGT_")
            and link["href"].endswith(".zip")
        ),
        None,
    )
    if data_link is None:
        raise RuntimeError(f"NASA CMR granule {title} has no HGT download link")
    return {"granule_id": title, "granule_url": data_link, "granule_updated_at": entry["updated"]}


def _download_tile(url: str, cache_path: Path, token: str) -> bool:
    """Download and validate a bounded ZIP atomically; return whether it was fetched."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.is_file():
        return False
    with requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=(20, 180),
    ) as response:
        if response.status_code == 401:
            raise PermissionError("NASA Earthdata rejected EARTHDATA_TOKEN; check its validity")
        response.raise_for_status()
        length = int(response.headers.get("Content-Length", "0"))
        if length > MAX_TILE_BYTES:
            raise RuntimeError(f"NASADEM granule exceeds the {MAX_TILE_BYTES}-byte tile limit")
        temporary = cache_path.with_suffix(".part")
        total = 0
        try:
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_TILE_BYTES:
                        raise RuntimeError(
                            f"NASADEM granule exceeds the {MAX_TILE_BYTES}-byte tile limit"
                        )
                    output.write(chunk)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError("Downloaded NASADEM ZIP failed its CRC check")
            temporary.replace(cache_path)
            return True
        finally:
            temporary.unlink(missing_ok=True)


def _read_members(
    cache_path: Path, tile: str, *, samples: int = TILE_SAMPLES
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read elevation, valid-observation count, and water masks from the cached tile."""
    with zipfile.ZipFile(cache_path) as archive:
        members = {Path(name).suffix.lower(): name for name in archive.namelist()}
        arrays = []
        for extension, dtype, expected_bytes in (
            (".hgt", ">i2", 2 * samples**2),
            (".num", "u1", samples**2),
            (".swb", "u1", samples**2),
        ):
            name = members.get(extension)
            if name is None:
                raise RuntimeError(f"NASADEM {tile} ZIP is missing {extension} support data")
            raw = archive.read(name)
            if len(raw) != expected_bytes:
                raise RuntimeError(
                    f"NASADEM {tile} {extension} size {len(raw)} != {expected_bytes} bytes"
                )
            arrays.append(np.frombuffer(raw, dtype=dtype).reshape(samples, samples))
    return arrays[0].astype(np.float32), arrays[1], arrays[2]


def ingest(
    observation_id: str,
    output: Path,
    *,
    token: str | None = None,
    context_size_m: float = DEFAULT_CONTEXT_SIZE_M,
    target_pixel_m: float = EARTH_GRID_M,
) -> dict[str, object]:
    """Build scale-matched NASADEM context and support measurements for one Earth patch."""
    token = token or os.environ.get("EARTHDATA_TOKEN")
    if not token:
        raise ValueError("Set EARTHDATA_TOKEN to a NASA Earthdata Login Personal Access Token")
    if context_size_m <= 0 or target_pixel_m <= 0:
        raise ValueError("context size and target pixel spacing must be positive")
    records = read_jsonl(MANIFEST)
    record = next((item for item in records if item.image_id == observation_id), None)
    if record is None or record.body != "earth":
        raise ValueError("observation_id must identify an Earth observation in pilot-100")
    tile = tile_name(record.longitude, record.latitude)
    granule = _granule(tile)
    cache_path = ROOT / "data/raw/nasadem" / f"{granule['granule_id']}.zip"
    downloaded_now = _download_tile(granule["granule_url"], cache_path, token)
    retrieved_at = datetime.now(UTC).isoformat() if downloaded_now else None
    heights, num, water = _read_members(cache_path, tile)
    heights[(heights < -32767) | (heights > 32767) | (water == 255)] = np.nan

    with rasterio.open(ROOT / record.path) as reference:
        if reference.crs is None or not reference.crs.is_projected:
            raise ValueError("Earth patch needs a projected source CRS")
        center_x, center_y = reference.transform @ (
            reference.width / 2,
            reference.height / 2,
        )
        target_crs = reference.crs
    half = context_size_m / 2
    width = height = max(3, round(context_size_m / target_pixel_m))
    pixel = context_size_m / width
    output_transform = Affine(pixel, 0, center_x - half, 0, -pixel, center_y + half)
    tile_south = math.floor(record.latitude)
    tile_west = math.floor(record.longitude)
    source_transform = Affine(
        1 / PIXELS_PER_DEGREE,
        0,
        tile_west - 0.5 / PIXELS_PER_DEGREE,
        0,
        -1 / PIXELS_PER_DEGREE,
        tile_south + 1 + 0.5 / PIXELS_PER_DEGREE,
    )
    source_crs = CRS.from_epsg(4326)
    dem = np.full((height, width), -32768, dtype=np.float32)
    reproject(
        heights,
        dem,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=output_transform,
        dst_crs=target_crs,
        dst_nodata=-32768,
        resampling=Resampling.bilinear,
    )
    quality_pixel_m = 30.0
    quality_width = ceil(context_size_m / quality_pixel_m)
    quality_pixel_m = context_size_m / quality_width
    quality_transform = Affine(
        quality_pixel_m,
        0,
        center_x - half,
        0,
        -quality_pixel_m,
        center_y + half,
    )
    local_num = np.zeros((quality_width, quality_width), dtype=np.uint8)
    local_water = np.full((quality_width, quality_width), 255, dtype=np.uint8)
    for source, destination in ((num, local_num), (water, local_water)):
        reproject(
            source,
            destination,
            src_transform=source_transform,
            src_crs=source_crs,
            dst_transform=quality_transform,
            dst_crs=target_crs,
            resampling=Resampling.nearest,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="int16",
        crs=target_crs,
        transform=output_transform,
        nodata=-32768,
        compress="deflate",
    ) as destination:
        destination.write(np.rint(dem).astype(np.int16), 1)

    context_land = (local_water != 255) & (local_num != 0)
    quality_histogram = dict(Counter(map(int, local_num[context_land])).most_common())
    direct_classes = sum(value for code, value in quality_histogram.items() if 1 <= code <= 23)
    terrestrial_cells = sum(quality_histogram.values())
    metadata: dict[str, object] = {
        "observation_id": observation_id,
        "dataset_id": "nasadem-hgt",
        "provider": PROVIDER,
        "source_product_id": granule["granule_id"],
        "source_url": granule["granule_url"],
        "dataset_reference_url": NASADEM_DOI,
        "user_guide_url": NASADEM_GUIDE,
        "granule_updated_at": granule["granule_updated_at"],
        "retrieved_at": retrieved_at,
        "acquisition_period": "SRTM mission, 2000-02-11 through 2000-02-21",
        "native_resolution_arcseconds": 1,
        "vertical_datum": "EGM96 geoid",
        "height_units": "m",
        "quality_source": "NASADEM NUM and SWB layers; class histogram over this context",
        "num_class_histogram": quality_histogram,
        "direct_srtm_class_fraction": direct_classes / terrestrial_cells
        if terrestrial_cells
        else None,
        "data_coverage": {
            "status": "partial" if np.any(dem == -32768) else "complete",
            "observed_cell_count": int(np.count_nonzero(dem != -32768)),
            "grid_cell_count": int(dem.size),
            "observed_cell_fraction": float(np.count_nonzero(dem != -32768) / dem.size),
            "direct_srtm_source_fraction": direct_classes / terrestrial_cells
            if terrestrial_cells
            else None,
            "note": (
                "NASADEM is a merged void-filled surface. The NUM source-class histogram is "
                "separate from valid raster coverage and identifies non-SRTM fills."
            ),
        },
        "context_size_m": context_size_m,
        "output_pixel_size_m": pixel,
        "processing_crs": target_crs.to_string(),
        "processing_method": (
            "One CMR-selected 1-degree HGT granule; EGM96 heights warped bilinearly to the "
            "indexed Earth patch CRS and 463 m context grid; water mask applied"
        ),
        "missing_data_semantics": (
            "NASADEM HGT is a void-filled merge. NUM source classes are preserved as a tile "
            "histogram; interpolation or secondary-DEM fills are not presented as direct SRTM."
        ),
        "licence": "U.S. Government work; cite NASADEM DOI",
        "cache_file": str(cache_path.relative_to(ROOT)),
        "cache_reused": not downloaded_now,
        "output": str(output.relative_to(ROOT)),
    }
    features = [
        item.model_dump(mode="json")
        for item in terrain_features(
            output,
            observation_id=observation_id,
            provider=PROVIDER,
            product_id=granule["granule_id"],
            source_url=granule["granule_url"],
            processing_method=str(metadata["processing_method"]),
        )
    ]
    for item in features:
        item["uncertainty"]["description"] = (
            "NASADEM merged HGT terrain metric; source NUM class fractions are recorded "
            "separately and include non-SRTM fills. Vegetation/buildings and resampling can "
            "affect surface heights."
        )
    metadata["measurements"] = features
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", default="earth_namib_barchan-01")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/terrain/nasadem-hgt-earth-namib-01.tif",
    )
    parser.add_argument("--context-size-m", type=float, default=DEFAULT_CONTEXT_SIZE_M)
    args = parser.parse_args()
    result = ingest(args.observation, args.output, context_size_m=args.context_size_m)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
