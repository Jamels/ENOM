"""Fetch the Copernicus GLO-30 COG window intersecting a pilot Earth observation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from twinworld.records import read_jsonl
from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "cop-dem-glo-30"
MARS_RADIUS_M = 3_396_000.0
DEFAULT_TARGET_PIXEL_M = 2 * 3.141592653589793 * MARS_RADIUS_M / (128 * 360)
DEFAULT_CONTEXT_SIZE_M = 22 * DEFAULT_TARGET_PIXEL_M


def ingest(
    observation_id: str,
    output: Path,
    *,
    context_size_m: float = DEFAULT_CONTEXT_SIZE_M,
    target_pixel_m: float = DEFAULT_TARGET_PIXEL_M,
) -> dict[str, object]:
    """Fetch a bounded Copernicus DEM window and write its measurements and provenance."""
    manifest = read_jsonl(ROOT / "data/manifests/pilot-100.jsonl")
    record = next((item for item in manifest if item.image_id == observation_id), None)
    if record is None or record.body != "earth":
        raise ValueError("observation_id must identify an Earth observation in pilot-100")
    if context_size_m <= 0 or target_pixel_m <= 0:
        raise ValueError("context size and target pixel spacing must be positive")
    half_width = half_height = context_size_m / 2
    # Use the patch's documented projected CRS to make the retrieval window metric.
    with rasterio.open(ROOT / record.path) as source:
        if source.crs is None or not source.crs.is_projected:
            raise ValueError("Earth patch needs a projected source CRS")
        center_x, center_y = source.transform * (source.width / 2, source.height / 2)
        target_crs = source.crs
    bounds = transform_bounds(
        target_crs,
        "EPSG:4326",
        center_x - half_width,
        center_y - half_height,
        center_x + half_width,
        center_y + half_height,
        densify_pts=21,
    )
    catalog = Client.open(STAC_URL)
    matches = list(catalog.search(collections=[COLLECTION], bbox=list(bounds), limit=20).items())
    if not matches:
        raise RuntimeError("Copernicus DEM catalogue returned no item for the observation")
    item = min(matches, key=lambda candidate: candidate.id)
    signed_item = pc.sign(item)
    asset = signed_item.assets["data"].href
    width = max(3, round(context_size_m / target_pixel_m))
    height = width
    pixel_x = context_size_m / width
    pixel_y = context_size_m / height
    output.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(
        center_x - context_size_m / 2,
        center_y + context_size_m / 2,
        pixel_x,
        pixel_y,
    )
    with rasterio.open(asset) as source:
        with WarpedVRT(
            source, crs=target_crs, transform=transform, width=width, height=height
        ) as vrt:
            profile = vrt.profile.copy()
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.update(driver="GTiff", compress="deflate", tiled=False)
            with rasterio.open(output, "w", **profile) as destination:
                destination.write(vrt.read())
                destination.update_tags(
                    source_product_id=item.id,
                    source_collection=COLLECTION,
                    source_provider="Copernicus / Microsoft Planetary Computer",
                    source_catalog_url=f"{STAC_URL}/collections/{COLLECTION}/items/{item.id}",
                    license=str(item.properties.get("license", "see source product licence")),
                    source_resolution="approximately 30 m",
                    source_crs=str(source.crs),
                )
    metadata = {
        "observation_id": observation_id,
        "dataset_id": "cop-dem-glo-30",
        "provider": "Copernicus / Microsoft Planetary Computer",
        "source_product_id": item.id,
        "source_catalog_url": f"{STAC_URL}/collections/{COLLECTION}/items/{item.id}",
        "source_asset": "data",
        "source_resolution_m": 30,
        "output_pixel_size_m": [pixel_x, pixel_y],
        "context_size_m": context_size_m,
        "source_crs": "EPSG:4326",
        "processing_crs": str(target_crs),
        "processing_method": (
            "STAC bbox intersection; COG warped to a metric grid over the "
            "context window, sampled at the corresponding MOLA posting"
        ),
        "missing_data_semantics": (
            "Raster nodata preserved; no-data pixels excluded from feature calculations"
        ),
        "licence": str(
            item.properties.get("license", "Copernicus DEM licence; see linked product metadata")
        ),
        "output": str(output.relative_to(ROOT)),
    }
    metadata["measurements"] = [
        item.model_dump(mode="json")
        for item in terrain_features(
            output,
            observation_id=observation_id,
            provider="Copernicus / Microsoft Planetary Computer",
            product_id=item.id,
            source_url=f"{STAC_URL}/collections/{COLLECTION}/items/{item.id}",
        )
    ]
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", default="earth-namib-barchan-01")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/terrain/cop-dem-glo-30-namib-01.tif"
    )
    parser.add_argument("--context-size-m", type=float, default=DEFAULT_CONTEXT_SIZE_M)
    parser.add_argument("--target-pixel-m", type=float, default=DEFAULT_TARGET_PIXEL_M)
    args = parser.parse_args()
    print(
        json.dumps(
            ingest(
                args.observation,
                args.output,
                context_size_m=args.context_size_m,
                target_pixel_m=args.target_pixel_m,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
