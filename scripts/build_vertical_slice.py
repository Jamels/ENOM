#!/usr/bin/env python3
"""Create one traceable Earth–Mars pair from public source products.

Run on n-pc-unix after acquiring/extracting the CTX V01 map-projected tile.
The generated two-image slice validates processing only; it is not a benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
from pathlib import Path

import planetary_computer
import rasterio
import shapefile  # type: ignore[import-untyped]
from pystac_client import Client
from rasterio.crs import CRS
from rasterio.warp import transform

from twinworld.geospatial import ring_contains
from twinworld.patching import extract_metric_patch
from twinworld.records import PatchRecord, write_jsonl

EARTH_ITEM = "S2B_MSIL2A_20241231T084259_R064_T33KWP_20241231T122915"
MARS_MOSAIC = "MurrayLab_GlobalCTXMosaic_V01_E068_N04"
EARTH_LON_LAT = (15.7, -24.0)
MARS_LON_LAT = (68.03595577627597, 6.812141794229826)
MARS_GEOGRAPHIC_CRS = CRS.from_wkt(
    'GEOGCS["GCS_Mars_2000_Sphere",DATUM["D_Mars_2000_Sphere",'
    'SPHEROID["Mars_2000_Sphere_IAU_IAG",3396190.0,0.0]],'
    'PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]]'
)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def projected_center(
    lon: float, lat: float, source_crs: CRS, geographic_crs: CRS
) -> tuple[float, float]:
    x, y = transform(geographic_crs, source_crs, [lon], [lat])
    return x[0], y[0]


def seam_observation_at(path: Path, x: float, y: float) -> dict[str, object]:
    """Resolve the mosaic's seam-map observation at a projected map point."""
    reader = shapefile.Reader(str(path))
    field_names = [field[0] for field in reader.fields[1:]]
    matches: list[dict[str, object]] = []
    for geometry, values in zip(reader.shapes(), reader.records(), strict=True):
        if not (
            geometry.bbox[0] <= x <= geometry.bbox[2] and geometry.bbox[1] <= y <= geometry.bbox[3]
        ):
            continue
        starts = list(geometry.parts) + [len(geometry.points)]
        contains = False
        for start, end in zip(starts[:-1], starts[1:], strict=True):
            if ring_contains(geometry.points[start:end], x, y):
                contains = not contains
        if contains:
            matches.append(dict(zip(field_names, values, strict=True)))
    if not matches:
        raise ValueError("Mars patch center is absent from the CTX mosaic seam map")
    match = next((row for row in matches if row.get("DATA_QUAL") == "OK"), matches[0])
    if match.get("DATA_QUAL") != "OK":
        raise ValueError(f"Mars seam-map source quality is {match.get('DATA_QUAL')!r}")
    return match


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mars-mosaic",
        type=Path,
        default=Path("data/raw/mars/ctx-v01/MurrayLab_CTX_V01_E068_N04_Mosaic.tif"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/patches/vertical-slice"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/manifests/vertical-slice.jsonl")
    )
    parser.add_argument(
        "--mars-seam-map",
        type=Path,
        default=Path("data/raw/mars/ctx-v01/MurrayLab_CTX_V01_E068_N04_SeamMap.shp"),
    )
    args = parser.parse_args()
    if not args.mars_mosaic.is_file():
        parser.error(f"map-projected CTX mosaic TIFF not found: {args.mars_mosaic}")

    catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    collection = catalog.get_collection("sentinel-2-l2a")
    if collection is None:
        raise RuntimeError("Sentinel-2 STAC collection not found")
    item = collection.get_item(EARTH_ITEM)
    if item is None:
        raise RuntimeError(f"Sentinel-2 STAC item not found: {EARTH_ITEM}")
    earth_item = planetary_computer.sign(item)
    earth_asset = earth_item.assets["visual"]
    earth_output = args.output_dir / "earth_namib_2km.tif"
    with rasterio.open(earth_asset.href) as source:
        if source.count != 3 or source.crs is None:
            raise ValueError("expected a three-band georeferenced Sentinel-2 visual asset")
        x, y = projected_center(*EARTH_LON_LAT, source.crs, CRS.from_epsg(4326))
        if not (
            source.bounds.left <= x <= source.bounds.right
            and source.bounds.bottom <= y <= source.bounds.top
        ):
            raise ValueError("selected Earth center is outside the chosen Sentinel-2 tile")
        earth_crs = source.crs.to_string()
    earth_geometry = extract_metric_patch(
        earth_asset.href,
        earth_output,
        center_x=x,
        center_y=y,
        extent_m=2000,
        native_gsd_m=10,
        bands=(1, 2, 3),
    )

    mars_output = args.output_dir / "mars_meroe_2km.tif"
    with rasterio.open(args.mars_mosaic) as source:
        if source.crs is None:
            raise ValueError("CTX V01 mosaic has no map CRS")
        mx, my = projected_center(*MARS_LON_LAT, source.crs, MARS_GEOGRAPHIC_CRS)
        mars_crs = source.crs.to_string()
    mars_source = seam_observation_at(args.mars_seam_map, mx, my)
    mars_geometry = extract_metric_patch(
        args.mars_mosaic,
        mars_output,
        center_x=mx,
        center_y=my,
        extent_m=2000,
        native_gsd_m=5,
    )

    acquired = item.datetime.isoformat() if isinstance(item.datetime, datetime) else None
    earth_record = PatchRecord(
        image_id="earth-namib-s2b-20241231-15.7e-24.0s-2km",
        body="earth",
        path=str(earth_output),
        source_id=EARTH_ITEM,
        provider="ESA Sentinel-2 Level-2A via Microsoft Planetary Computer",
        source_url=(
            "https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
            f"sentinel-2-l2a/items/{EARTH_ITEM}"
        ),
        latitude=EARTH_LON_LAT[1],
        longitude=EARTH_LON_LAT[0],
        native_gsd_m=10,
        width_m=earth_geometry.width_m,
        height_m=earth_geometry.height_m,
        acquired_at=acquired,
        crs=earth_crs,
        label="unknown",
        label_status="unknown",
        geographic_group="namib_sand_sea_15.7E_24.0S",
        checksum_sha256=checksum(earth_output),
        processing={
            "asset": "visual RGB COG",
            "scale": "2 km square; 10 m native pixel spacing",
            "resampling": "bilinear to native 10 m grid",
            "annotation": "unreviewed; confirm dune morphology before labeling",
        },
    )
    mars_record = PatchRecord(
        image_id="mars-meroe-ctx-v01-68.0360e-6.8121n-2km",
        body="mars",
        path=str(mars_output),
        source_id=str(mars_source["PRODUCT_ID"]),
        provider="MRO CTX global V01 mosaic, Murray Lab / Caltech",
        source_url=(f"https://murray-lab.caltech.edu/CTX/V01/tiles/{MARS_MOSAIC}.zip"),
        latitude=MARS_LON_LAT[1],
        longitude=MARS_LON_LAT[0],
        native_gsd_m=5,
        width_m=mars_geometry.width_m,
        height_m=mars_geometry.height_m,
        acquired_at=None,
        crs=mars_crs,
        label="unknown",
        label_status="unknown",
        geographic_group="meroe_patera_west_dune_field",
        checksum_sha256=checksum(mars_output),
        processing={
            "asset": "map-projected blended CTX V01 GeoTIFF mosaic",
            "mosaic_tile": f"{MARS_MOSAIC}_Mosaic.tif",
            "seam_map_source_quality": str(mars_source["DATA_QUAL"]),
            "source_observation_time": str(mars_source["IMAGE_TIME"]),
            "source_observation_file": str(mars_source["PDS_IMG"]),
            "scale": "2 km square; 5 m mosaic pixel spacing",
            "resampling": "bilinear to native 5 m mosaic grid",
            "annotation": "unreviewed; inspect seam map and morphology before labeling",
        },
    )
    write_jsonl(args.manifest, [earth_record, mars_record])
    print(
        f"wrote {args.manifest}; 2 patches "
        f"(Earth {earth_geometry.width_pixels}px, Mars {mars_geometry.width_pixels}px)"
    )
    print(f"Earth SHA-256: {earth_record.checksum_sha256}")
    print(f"Mars SHA-256: {mars_record.checksum_sha256}")


if __name__ == "__main__":
    main()
