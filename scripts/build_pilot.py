#!/usr/bin/env python3
"""Discover and build the deterministic 100-patch Earth–Mars pilot.

The discovery plan stores stable item identifiers, never expiring signed URLs.
Raster assets are read as Cloud Optimized GeoTIFF windows and generated chips
are written atomically so the command can resume after interruption.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import planetary_computer
import rasterio
import shapefile  # type: ignore[import-untyped]
from pystac_client import Client
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import transform
from rasterio.windows import from_bounds

from twinworld.annotations import merge_review_row
from twinworld.geospatial import mars_projection_longitude, mars_surface_distance_m, shape_contains
from twinworld.patching import extract_metric_patch
from twinworld.records import PatchRecord, read_jsonl, write_jsonl
from twinworld.spatial import ensure_no_overlaps

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/pilot-sites.json"
PLAN_PATH = ROOT / "data/manifests/pilot-plan.json"
MANIFEST_PATH = ROOT / "data/manifests/pilot-100.jsonl"
ANNOTATION_PATH = ROOT / "data/annotations/pilot-100.csv"
PATCH_DIR = ROOT / "data/patches/pilot-100"
MARS_COLLECTION = "mro_ctx_controlled_usgs_dtms"
MARS_STAC = "https://stac.astrogeology.usgs.gov/api"
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
MARS_GEOGRAPHIC_CRS = CRS.from_wkt(
    'GEOGCS["GCS_Mars_2000_Sphere",DATUM["D_Mars_2000_Sphere",'
    'SPHEROID["Mars_2000_Sphere_IAU_IAG",3396190.0,0.0]],'
    'PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]]'
)
LABELS = (
    "barchan_crescent_dune",
    "linear_dune",
    "other_dune",
    "rocky_ridge_layered",
    "other_non_dune",
)
EARTH_OFFSETS_M = ((-6000, -4000), (0, -4000), (6000, -4000), (-3000, 4000), (3000, 4000))


def projected_center(
    longitude: float, latitude: float, destination_crs: CRS, body: str
) -> tuple[float, float]:
    source_crs = CRS.from_epsg(4326) if body == "earth" else MARS_GEOGRAPHIC_CRS
    source_longitude = longitude if body == "earth" else mars_projection_longitude(longitude)
    xs, ys = transform(source_crs, destination_crs, [source_longitude], [latitude])
    return float(xs[0]), float(ys[0])


def geographic_center(x: float, y: float, source_crs: CRS, body: str) -> tuple[float, float]:
    destination_crs = CRS.from_epsg(4326) if body == "earth" else MARS_GEOGRAPHIC_CRS
    longitudes, latitudes = transform(source_crs, destination_crs, [x], [y])
    longitude = float(longitudes[0])
    if body == "mars":
        longitude %= 360.0
    return longitude, float(latitudes[0])


def ensure_mgd3(config: dict[str, Any]) -> Path:
    root = ROOT / "data/raw/mars/mgd3"
    archive = root / "Shapefiles.zip"
    shape_path = root / "shapefiles/Shapefiles/Geocentric/Dune_Field.shp"
    if shape_path.is_file():
        return shape_path
    root.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(".zip.part")
    start = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(
        config["mars_dune_database"]["source_url"],
        headers={"Range": f"bytes={start}-"} if start else {},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if start and response.status != 206:
            start = 0
            partial.unlink(missing_ok=True)
        mode = "ab" if start else "wb"
        with partial.open(mode) as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    os.replace(partial, archive)
    extract_root = root / "shapefiles"
    with zipfile.ZipFile(archive) as source:
        source.extractall(extract_root)
    if not shape_path.is_file():
        raise FileNotFoundError(f"MGD3 Dune_Field shapefile missing from {archive}")
    return shape_path


def _bounds_cover(
    dataset: rasterio.DatasetReader,
    center: tuple[float, float],
    offsets_m: Sequence[Sequence[float]],
    extent_m: float,
) -> bool:
    _, units_to_m = dataset.crs.linear_units_factor
    half_size = extent_m / units_to_m / 2
    for dx, dy in offsets_m:
        x, y = center[0] + dx / units_to_m, center[1] + dy / units_to_m
        if not (
            dataset.bounds.left + half_size <= x <= dataset.bounds.right - half_size
            and dataset.bounds.bottom + half_size <= y <= dataset.bounds.top - half_size
        ):
            return False
    return True


def _earth_candidates(
    catalog: Any, site: dict[str, Any], config: dict[str, Any]
) -> tuple[Any, str, tuple[float, float], float]:
    longitude, latitude = float(site["longitude"]), float(site["latitude"])
    start, end = config["earth_date_range"]
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=[longitude - 0.15, latitude - 0.15, longitude + 0.15, latitude + 0.15],
        datetime=f"{start}T00:00:00Z/{end}T23:59:59Z",
        query={"eo:cloud_cover": {"lte": config["earth_cloud_cover_max"]}},
        max_items=100,
    )
    items = list(search.items())
    items.sort(
        key=lambda item: (
            float(item.properties.get("eo:cloud_cover", 100)),
            -(item.datetime.timestamp() if item.datetime else 0),
            item.id,
        )
    )
    for item in items:
        if "visual" not in item.assets:
            continue
        signed = planetary_computer.sign(item)
        href = signed.assets["visual"].href
        try:
            with rasterio.open(href) as dataset:
                if dataset.count < 3 or dataset.crs is None:
                    continue
                center = projected_center(longitude, latitude, dataset.crs, "earth")
                if _bounds_cover(dataset, center, EARTH_OFFSETS_M, config["target_extent_m"]):
                    return item, href, center, float(max(dataset.res))
        except rasterio.errors.RasterioError:
            continue
    raise RuntimeError(f"no cloud-filtered Sentinel-2 RGB item covers site {site['site_id']}")


def _mars_item(
    catalog: Any,
    longitude: float,
    latitude: float,
    offsets_m: list[list[float]],
    extent_m: float,
    *,
    hinted_item_id: str | None = None,
) -> tuple[Any, str, str, tuple[float, float], float]:
    collection = catalog.get_collection(MARS_COLLECTION)
    items: list[Any] = []
    if hinted_item_id:
        item = collection.get_item(hinted_item_id)
        if item is not None:
            items.append(item)
    query_longitude = longitude % 360.0
    search = catalog.search(
        collections=[MARS_COLLECTION],
        bbox=[
            query_longitude - 0.15,
            latitude - 0.15,
            query_longitude + 0.15,
            latitude + 0.15,
        ],
        max_items=50,
    )
    existing = {item.id for item in items}
    items.extend(item for item in search.items() if item.id not in existing)
    signed_longitude = mars_projection_longitude(longitude)
    for item in items:
        for asset_key in ("orthoimage", "image"):
            asset = item.assets.get(asset_key)
            if asset is None:
                continue
            href = asset.href
            try:
                with rasterio.open(href) as dataset:
                    if dataset.crs is None or dataset.count < 1:
                        continue
                    center = projected_center(signed_longitude, latitude, dataset.crs, "mars")
                    if _bounds_cover(dataset, center, offsets_m, extent_m):
                        return item, asset_key, href, center, float(max(dataset.res))
            except rasterio.errors.RasterioError:
                continue
    raise RuntimeError(f"no map-projected CTX orthoimage covers {longitude:.5f},{latitude:.5f}")


def _candidate_distance(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    longitude, latitude = float(candidate["longitude"]), float(candidate["latitude"])
    return min(
        mars_surface_distance_m(
            longitude,
            latitude,
            float(row["longitude"]),
            float(row["latitude"]),
        )
        for row in selected
    )


def _dune_positions(
    shape_geometry: shapefile.Shape,
    longitude: float,
    latitude: float,
    source_center: tuple[float, float],
    source_crs: CRS,
    source_bounds: rasterio.coords.BoundingBox,
    extent_m: float,
    count: int,
) -> list[list[float]]:
    offsets = [(0.0, 0.0)]
    for radius in (2500.0, 5000.0, 7500.0, 10000.0):
        for dx, dy in (
            (-radius, 0),
            (radius, 0),
            (0, -radius),
            (0, radius),
            (-radius, -radius),
            (-radius, radius),
            (radius, -radius),
            (radius, radius),
        ):
            offsets.append((dx, dy))
    _, units_to_m = source_crs.linear_units_factor
    half = extent_m / units_to_m / 2
    chosen: list[list[float]] = []
    chosen_centers: list[tuple[float, float]] = []
    for dx_m, dy_m in offsets:
        x = source_center[0] + dx_m / units_to_m
        y = source_center[1] + dy_m / units_to_m
        if not (
            source_bounds.left + half <= x <= source_bounds.right - half
            and source_bounds.bottom + half <= y <= source_bounds.top - half
        ):
            continue
        samples_inside = 0
        sample_count = 0
        for sy in (-750, 0, 750):
            for sx in (-750, 0, 750):
                lon, lat = geographic_center(
                    x + sx / units_to_m, y + sy / units_to_m, source_crs, "mars"
                )
                samples_inside += int(shape_contains(shape_geometry, lon, lat))
                sample_count += 1
        if samples_inside / sample_count < 0.55:
            continue
        if any(
            abs(x - old_x) < extent_m / units_to_m and abs(y - old_y) < extent_m / units_to_m
            for old_x, old_y in chosen_centers
        ):
            continue
        chosen.append([dx_m, dy_m])
        chosen_centers.append((x, y))
        if len(chosen) == count:
            return chosen
    return chosen


def _earth_plan_rows(
    catalog: Any, sites: list[dict[str, Any]], config: dict[str, Any], extent_m: float
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Turn configured Earth targets into source-backed patch proposals."""
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for site in sites:
        try:
            item, _href, center, gsd = _earth_candidates(catalog, site, config)
            crs: str
            with rasterio.open(planetary_computer.sign(item).assets["visual"].href) as dataset:
                crs = dataset.crs.to_string()
            canonical_url = (
                f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
                f"sentinel-2-l2a/items/{item.id}"
            )
            for index, (dx, dy) in enumerate(EARTH_OFFSETS_M, start=1):
                x, y = center[0] + dx, center[1] + dy
                longitude, latitude = geographic_center(x, y, CRS.from_user_input(crs), "earth")
                rows.append(
                    {
                        "image_id": f"{site['site_id']}-{index:02d}",
                        "body": "earth",
                        "site_id": site["site_id"],
                        "site_name": site["name"],
                        "proposed_label": site["proposed_label"],
                        "proposal_basis": site["basis"],
                        "longitude": longitude,
                        "latitude": latitude,
                        "center_x": x,
                        "center_y": y,
                        "source_id": item.id,
                        "source_url": canonical_url,
                        "provider": "ESA Sentinel-2 L2A via Microsoft Planetary Computer",
                        "asset_key": "visual",
                        "acquired_at": item.datetime.isoformat() if item.datetime else None,
                        "native_gsd_m": gsd,
                        "crs": crs,
                        "extent_m": extent_m,
                        "processing": {
                            "asset": "Sentinel-2 visual RGB COG",
                            "eo_cloud_cover": str(item.properties.get("eo:cloud_cover", "")),
                            "platform": str(item.properties.get("platform", "")),
                            "site_name": site["name"],
                            "proposal_basis": site["basis"],
                        },
                    }
                )
        except Exception as exc:
            rejected.append({"site_id": str(site["site_id"]), "reason": str(exc)})
    return rows, rejected


def _mars_context_plan_rows(
    catalog: Any, sites: list[dict[str, Any]], extent_m: float
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Turn configured Mars reference sites into CTX patch proposals."""
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    context_allocations = {
        "mars_mawrth_layered": 4,
        "mars_eberswalde_layered": 3,
        "mars_valles_layered": 3,
        "mars_elysium_nondune": 2,
        "mars_hecates_nondune": 2,
        "mars_memnonia_nondune": 2,
        "mars_medusae_nondune": 2,
        "mars_aeolis_nondune": 2,
    }
    for site in sites:
        offsets = site["patch_offsets_m"]
        if len(offsets) != context_allocations[site["site_id"]]:
            rejected.append(
                {
                    "site_id": str(site["site_id"]),
                    "reason": "configured patch offsets do not match requested site allocation",
                }
            )
            continue
        try:
            item, asset_key, _href, center, gsd = _mars_item(
                catalog,
                float(site["longitude"]),
                float(site["latitude"]),
                offsets,
                extent_m,
            )
            crs = str(item.properties.get("proj:wkt2") or item.properties.get("proj:code") or "")
            # Read the raster CRS and source GSD from the actual COG, not catalog summaries.
            asset = item.assets[asset_key]
            with rasterio.open(asset.href) as dataset:
                crs = dataset.crs.to_string()
                for index, (dx, dy) in enumerate(offsets, start=1):
                    x = center[0] + float(dx)
                    y = center[1] + float(dy)
                    longitude, latitude = geographic_center(x, y, dataset.crs, "mars")
                    rows.append(
                        {
                            "image_id": f"{site['site_id']}-{index:02d}",
                            "body": "mars",
                            "site_id": site["site_id"],
                            "site_name": site["name"],
                            "proposed_label": site["proposed_label"],
                            "proposal_basis": site["ambiguity_notes"],
                            "ambiguity_notes": site["ambiguity_notes"],
                            "longitude": longitude,
                            "latitude": latitude,
                            "center_x": x,
                            "center_y": y,
                            "source_id": item.id,
                            "source_url": (
                                f"{MARS_STAC}/collections/{MARS_COLLECTION}/items/{item.id}"
                            ),
                            "provider": "NASA MRO CTX, orthorectified by USGS Astrogeology",
                            "asset_key": asset_key,
                            "acquired_at": None,
                            "native_gsd_m": gsd,
                            "crs": crs,
                            "extent_m": extent_m,
                            "processing": {
                                "asset": "USGS CTX orthorectified COG",
                                "site_name": site["name"],
                                "proposal_basis": site["ambiguity_notes"],
                                "catalog_datetime_not_acquisition": str(
                                    item.properties.get("datetime", "")
                                ),
                            },
                        }
                    )
        except Exception as exc:
            rejected.append({"site_id": str(site["site_id"]), "reason": str(exc)})
    return rows, rejected


def discover_plan(config: dict[str, Any]) -> dict[str, Any]:
    earth_catalog = Client.open(PC_STAC)
    mars_catalog = Client.open(MARS_STAC)
    shape_path = ensure_mgd3(config)
    shape_reader = shapefile.Reader(str(shape_path))
    shape_fields = [field[0] for field in shape_reader.fields[1:]]
    dune_shapes: dict[str, shapefile.Shape] = {}
    for geometry, values in zip(shape_reader.shapes(), shape_reader.records(), strict=True):
        row = dict(zip(shape_fields, values, strict=True))
        dune_shapes[str(row["Dune_ID"])] = geometry

    extent_m = float(config["target_extent_m"])
    earth_rows, rejected = _earth_plan_rows(
        earth_catalog, config["earth_sites"], config, extent_m
    )
    mars_rows, mars_rejected = _mars_context_plan_rows(
        mars_catalog, config["mars_context_sites"], extent_m
    )
    rows = earth_rows + mars_rows
    rejected.extend(mars_rejected)

    # Parse the source manifest as plain dictionaries; its morphology fields are not PatchRecords.
    candidate_dicts = (
        [
            json.loads(line)
            for line in (ROOT / "data/manifests/mars-dune-candidates.jsonl")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        if (ROOT / "data/manifests/mars-dune-candidates.jsonl").is_file()
        else []
    )

    dune_plan: list[dict[str, Any]] = []
    for category in ("barchan_crescent_dune", "linear_dune", "other_dune"):
        candidates = [
            row
            for row in candidate_dicts
            if row["category"] == category
            and float(row["area_km2"]) >= config["mars_dune_database"]["minimum_field_area_km2"]
            and str(row["confidence"]) == "1"
        ]
        target_fields = 10 if category != "linear_dune" else 4
        selected: list[dict[str, Any]] = []
        remaining = list(candidates)
        while remaining and len(selected) < target_fields:
            if selected:
                # Maximize Mars surface separation after seeding with the largest field.
                remaining.sort(
                    key=lambda row: (
                        _candidate_distance(row, selected),
                        float(row["area_km2"]),
                        str(row["dune_id"]),
                    ),
                    reverse=True,
                )
            else:
                remaining.sort(
                    key=lambda row: (float(row["area_km2"]), str(row["dune_id"])),
                    reverse=True,
                )
            candidate = remaining.pop(0)
            if any(row["dune_id"] == candidate["dune_id"] for row in selected):
                continue
            count = 1
            try:
                item, asset_key, href, center, gsd = _mars_item(
                    mars_catalog,
                    float(candidate["longitude"]),
                    float(candidate["latitude"]),
                    [[0, 0]],
                    extent_m,
                    hinted_item_id=str(candidate["ctx_item_id"]),
                )
                with rasterio.open(href) as dataset:
                    candidate_crs = dataset.crs
                    if candidate_crs is None:
                        continue
                    if category == "linear_dune":
                        count = (3, 3, 2, 2)[len(selected)]
                        offsets = _dune_positions(
                            dune_shapes[candidate["dune_id"]],
                            float(candidate["longitude"]),
                            float(candidate["latitude"]),
                            center,
                            candidate_crs,
                            dataset.bounds,
                            extent_m,
                            count,
                        )
                        if len(offsets) != count:
                            continue
                    else:
                        offsets = [[0.0, 0.0]]
                    candidate.update(
                        {
                            "asset_key": asset_key,
                            "source_id": item.id,
                            "source_url": (
                                f"{MARS_STAC}/collections/{MARS_COLLECTION}/items/{item.id}"
                            ),
                            "provider": "NASA MRO CTX, orthorectified by USGS Astrogeology",
                            "offsets_m": offsets,
                            "center_x": center[0],
                            "center_y": center[1],
                            "native_gsd_m": gsd,
                            "crs": candidate_crs.to_string(),
                            "catalog_datetime": str(item.properties.get("datetime", "")),
                        }
                    )
                    selected.append(candidate)
            except Exception as exc:
                rejected.append(
                    {
                        "site_id": f"mars_dune_{candidate['dune_id']}",
                        "reason": str(exc),
                    }
                )
        required_rows = 10
        if len(selected) < target_fields:
            rejected.append(
                {
                    "site_id": f"mars_dune_{category}",
                    "reason": (
                        f"only {len(selected)} of {target_fields} eligible fields "
                        "had usable CTX coverage"
                    ),
                }
            )
        if category == "linear_dune":
            for field in selected:
                for index, (dx, dy) in enumerate(field["offsets_m"], start=1):
                    x = float(field["center_x"]) + float(dx)
                    y = float(field["center_y"]) + float(dy)
                    longitude, latitude = geographic_center(
                        x, y, CRS.from_user_input(field["crs"]), "mars"
                    )
                    dune_plan.append(
                        {
                            "image_id": f"mars-dune-linear-{field['dune_id']}-{index:02d}",
                            "body": "mars",
                            "site_id": f"mars_dune_{field['dune_id']}",
                            "site_name": f"MGD3 dune field {field['dune_id']}",
                            "proposed_label": category,
                            "proposal_basis": (
                                f"MGD3 type {field['morphology_types']}; "
                                f"confidence {field['confidence']}"
                            ),
                            "ambiguity_notes": "MGD3 field type; verify the 2 km crop",
                            "longitude": longitude,
                            "latitude": latitude,
                            "center_x": x,
                            "center_y": y,
                            "source_id": field["source_id"],
                            "source_url": field["source_url"],
                            "provider": field["provider"],
                            "asset_key": field["asset_key"],
                            "acquired_at": None,
                            "native_gsd_m": field["native_gsd_m"],
                            "crs": field["crs"],
                            "extent_m": extent_m,
                            "processing": {
                                "asset": "USGS CTX orthorectified COG",
                                "mgd3_dune_id": field["dune_id"],
                                "mgd3_morphology_types": field["morphology_types"],
                                "mgd3_field_area_km2": str(field["area_km2"]),
                                "mgd3_source": field["morphology_source"],
                                "catalog_datetime_not_acquisition": field["catalog_datetime"],
                            },
                        }
                    )
        else:
            for field in selected:
                lon, lat = float(field["longitude"]), float(field["latitude"])
                x, y = float(field["center_x"]), float(field["center_y"])
                dune_plan.append(
                    {
                        "image_id": f"mars-dune-{category}-{field['dune_id']}",
                        "body": "mars",
                        "site_id": f"mars_dune_{field['dune_id']}",
                        "site_name": f"MGD3 dune field {field['dune_id']}",
                        "proposed_label": category,
                        "proposal_basis": (
                            f"MGD3 type {field['morphology_types']}; "
                            f"confidence {field['confidence']}"
                        ),
                        "ambiguity_notes": "MGD3 field type; verify the 2 km crop",
                        "longitude": lon,
                        "latitude": lat,
                        "center_x": x,
                        "center_y": y,
                        "source_id": field["source_id"],
                        "source_url": field["source_url"],
                        "provider": field["provider"],
                        "asset_key": field["asset_key"],
                        "acquired_at": None,
                        "native_gsd_m": field["native_gsd_m"],
                        "crs": field["crs"],
                        "extent_m": extent_m,
                        "processing": {
                            "asset": "USGS CTX orthorectified COG",
                            "mgd3_dune_id": field["dune_id"],
                            "mgd3_morphology_types": field["morphology_types"],
                            "mgd3_field_area_km2": str(field["area_km2"]),
                            "mgd3_source": field["morphology_source"],
                            "catalog_datetime_not_acquisition": field["catalog_datetime"],
                        },
                    }
                )
        if len([row for row in dune_plan if row["proposed_label"] == category]) < required_rows:
            rejected.append(
                {
                    "site_id": f"mars_dune_{category}",
                    "reason": "candidate plan contains fewer than 10 crops for this category",
                }
            )
    rows.extend(dune_plan)

    plan = {
        "benchmark_id": config["benchmark_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "config_sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        "extent_m": extent_m,
        "rows": sorted(rows, key=lambda row: row["image_id"]),
        "rejected": rejected,
        "source_collection": MARS_COLLECTION,
    }
    ensure_no_overlaps(plan["rows"])
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PLAN_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, PLAN_PATH)
    return plan


def _source_href(row: dict[str, Any], earth_catalog: Any, mars_catalog: Any) -> str:
    if row["body"] == "earth":
        item = earth_catalog.get_collection("sentinel-2-l2a").get_item(row["source_id"])
        if item is None:
            raise RuntimeError(f"Sentinel-2 item not found: {row['source_id']}")
        return planetary_computer.sign(item).assets[row["asset_key"]].href
    item = mars_catalog.get_collection(MARS_COLLECTION).get_item(row["source_id"])
    if item is None:
        raise RuntimeError(f"CTX STAC item not found: {row['source_id']}")
    return item.assets[row["asset_key"]].href


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cached_patch_matches(
    row: dict[str, Any], record: PatchRecord | None, patch_path: Path
) -> bool:
    """Check whether a patch file still represents the planned source and center."""
    return bool(
        record
        and patch_path.is_file()
        and record.source_id == row["source_id"]
        and float(record.processing.get("patch_center_x", "nan")) == float(row["center_x"])
        and float(record.processing.get("patch_center_y", "nan")) == float(row["center_y"])
        and _sha256(patch_path) == record.checksum_sha256
    )


def _mask_coverage(
    dataset: rasterio.DatasetReader,
    center_x: float,
    center_y: float,
    extent_m: float,
    bands: tuple[int, ...],
) -> float:
    """Estimate usable source coverage on the exact output grid."""
    _, units_to_m = dataset.crs.linear_units_factor
    half = extent_m / units_to_m / 2
    window = from_bounds(
        center_x - half,
        center_y - half,
        center_x + half,
        center_y + half,
        transform=dataset.transform,
    )
    masks = dataset.read_masks(
        bands,
        window=window,
        out_shape=(len(bands), 100, 100),
        resampling=Resampling.average,
    )
    return float((masks.min(axis=0) > 0).mean())


def _fallback_centers(
    row: dict[str, Any],
    dataset: rasterio.DatasetReader,
    peers: list[dict[str, Any]],
    bands: tuple[int, ...],
    dune_shapes: dict[str, shapefile.Shape],
) -> tuple[float, float, float] | None:
    """Move a crop to nearby valid source pixels within its proposed site."""
    _, units_to_m = dataset.crs.linear_units_factor
    half = float(row["extent_m"]) / units_to_m / 2
    offsets = [(0.0, 0.0)]
    for radius in (1000, 2000, 3000, 4000, 5000, 7000, 9000, 12000, 15000, 20000):
        offsets.extend(
            (dx * radius, dy * radius)
            for dx, dy in (
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
                (1, 1),
                (1, -1),
                (-1, 1),
                (-1, -1),
            )
        )
    dune_id = row.get("processing", {}).get("mgd3_dune_id")
    for dx_m, dy_m in offsets:
        x = float(row["center_x"]) + dx_m / units_to_m
        y = float(row["center_y"]) + dy_m / units_to_m
        if not (
            dataset.bounds.left + half <= x <= dataset.bounds.right - half
            and dataset.bounds.bottom + half <= y <= dataset.bounds.top - half
        ):
            continue
        if any(
            peer is not row
            and peer["site_id"] == row["site_id"]
            and abs(x - float(peer["center_x"])) < 2 * half
            and abs(y - float(peer["center_y"])) < 2 * half
            for peer in peers
        ):
            continue
        if dune_id:
            longitude, latitude = geographic_center(x, y, dataset.crs, "mars")
            if not shape_contains(dune_shapes[str(dune_id)], longitude, latitude):
                continue
        coverage = _mask_coverage(dataset, x, y, float(row["extent_m"]), bands)
        # Small margin accounts for the bilinear warp's edge pixels.
        if coverage >= 0.98:
            return x, y, coverage
    return None


def _replacement_dune_row(
    failed_row: dict[str, Any],
    category: str,
    candidate_dicts: list[dict[str, Any]],
    selected_ids: set[str],
    mars_catalog: Any,
    dune_shapes: dict[str, shapefile.Shape],
) -> dict[str, Any] | None:
    for candidate in sorted(
        candidate_dicts, key=lambda item: float(item["area_km2"]), reverse=True
    ):
        dune_id = str(candidate["dune_id"])
        if (
            candidate["category"] != category
            or dune_id in selected_ids
            or float(candidate["area_km2"]) < 20
            or str(candidate["confidence"]) != "1"
        ):
            continue
        try:
            item, asset_key, _href, center, gsd = _mars_item(
                mars_catalog,
                float(candidate["longitude"]),
                float(candidate["latitude"]),
                [[0, 0]],
                float(failed_row["extent_m"]),
                hinted_item_id=str(candidate["ctx_item_id"]),
            )
            with rasterio.open(item.assets[asset_key].href) as dataset:
                candidate_row = {
                    **failed_row,
                    "site_id": f"mars_dune_{dune_id}",
                    "center_x": center[0],
                    "center_y": center[1],
                    "processing": {"mgd3_dune_id": dune_id},
                }
                usable_center = _fallback_centers(candidate_row, dataset, [], (1,), dune_shapes)
                if usable_center is None:
                    continue
                center_x, center_y, _coverage = usable_center
                longitude, latitude = geographic_center(center_x, center_y, dataset.crs, "mars")
                return {
                    **failed_row,
                    "image_id": f"mars-dune-{category}-{dune_id}",
                    "site_id": f"mars_dune_{dune_id}",
                    "site_name": f"MGD3 dune field {dune_id}",
                    "proposal_basis": (
                        f"MGD3 type {candidate['morphology_types']}; "
                        f"confidence {candidate['confidence']}"
                    ),
                    "ambiguity_notes": "MGD3 field type; verify the 2 km crop",
                    "longitude": longitude,
                    "latitude": latitude,
                    "center_x": center_x,
                    "center_y": center_y,
                    "source_id": item.id,
                    "source_url": f"{MARS_STAC}/collections/{MARS_COLLECTION}/items/{item.id}",
                    "provider": "NASA MRO CTX, orthorectified by USGS Astrogeology",
                    "asset_key": asset_key,
                    "native_gsd_m": gsd,
                    "crs": dataset.crs.to_string(),
                    "processing": {
                        "asset": "USGS CTX orthorectified COG",
                        "mgd3_dune_id": dune_id,
                        "mgd3_morphology_types": str(candidate["morphology_types"]),
                        "mgd3_field_area_km2": str(candidate["area_km2"]),
                        "mgd3_source": str(candidate["morphology_source"]),
                        "catalog_datetime_not_acquisition": str(
                            item.properties.get("datetime", "")
                        ),
                    },
                }
        except (KeyError, OSError, RuntimeError, rasterio.errors.RasterioError):
            continue
    return None


def repair_plan_coverage(plan: dict[str, Any]) -> dict[str, Any]:
    """Relocate nodata crops and replace unusable MGD3 fields before extraction."""
    earth_catalog = Client.open(PC_STAC)
    mars_catalog = Client.open(MARS_STAC)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    shape_path = ensure_mgd3(config)
    reader = shapefile.Reader(str(shape_path))
    fields = [field[0] for field in reader.fields[1:]]
    dune_shapes = {
        str(dict(zip(fields, values, strict=True))["Dune_ID"]): geometry
        for geometry, values in zip(reader.shapes(), reader.records(), strict=True)
    }
    candidate_dicts = [
        json.loads(line)
        for line in (ROOT / "data/manifests/mars-dune-candidates.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows = list(plan["rows"])
    ensure_no_overlaps(rows)
    existing = (
        {record.image_id: record for record in read_jsonl(MANIFEST_PATH)}
        if MANIFEST_PATH.exists()
        else {}
    )
    used_dunes = {
        str(row.get("processing", {}).get("mgd3_dune_id"))
        for row in rows
        if row.get("processing", {}).get("mgd3_dune_id")
    }
    repair_state = plan.get("coverage_repairs", {})
    changed = int(repair_state.get("relocated_or_replaced", 0))
    replaced = list(repair_state.get("replacements", []))
    for row in list(rows):
        prior = existing.get(str(row["image_id"]))
        destination = PATCH_DIR / f"{row['image_id']}.tif"
        if _cached_patch_matches(row, prior, destination):
            continue
        href = _source_href(row, earth_catalog, mars_catalog)
        bands = (1, 2, 3) if row["body"] == "earth" else (1,)
        with rasterio.open(href) as dataset:
            coverage = _mask_coverage(
                dataset,
                float(row["center_x"]),
                float(row["center_y"]),
                float(row["extent_m"]),
                bands,
            )
            if coverage >= 0.98:
                continue
            new_center = _fallback_centers(row, dataset, rows, bands, dune_shapes)
            if new_center:
                x, y, coverage = new_center
                row["center_x"], row["center_y"] = x, y
                row["longitude"], row["latitude"] = geographic_center(
                    x, y, dataset.crs, str(row["body"])
                )
                row.setdefault("processing", {})["nodata_relocation"] = (
                    f"shifted from planned center by valid-data mask search; "
                    f"estimated source coverage={coverage:.4f}"
                )
                changed += 1
                plan["rows"] = sorted(rows, key=lambda item: item["image_id"])
                ensure_no_overlaps(plan["rows"])
                plan["coverage_repairs"] = {
                    "relocated_or_replaced": changed,
                    "replacements": replaced,
                }
                _save_plan(plan)
                continue
        category = str(row["proposed_label"])
        if row["body"] == "mars" and category in {
            "barchan_crescent_dune",
            "other_dune",
        }:
            replacement = _replacement_dune_row(
                row, category, candidate_dicts, used_dunes, mars_catalog, dune_shapes
            )
            if replacement:
                rows[rows.index(row)] = replacement
                used_dunes.add(str(replacement["processing"]["mgd3_dune_id"]))
                replaced.append({"old": str(row["image_id"]), "new": str(replacement["image_id"])})
                changed += 1
                plan["rows"] = sorted(rows, key=lambda item: item["image_id"])
                ensure_no_overlaps(plan["rows"])
                plan["coverage_repairs"] = {
                    "relocated_or_replaced": changed,
                    "replacements": replaced,
                }
                _save_plan(plan)
                continue
        raise RuntimeError(
            f"no valid, label-preserving coverage replacement for {row['image_id']} "
            f"(estimated coverage {coverage:.3f})"
        )
    if changed:
        plan["rows"] = sorted(rows, key=lambda row: row["image_id"])
        plan["coverage_repairs"] = {"relocated_or_replaced": changed, "replacements": replaced}
        _save_plan(plan)
        print(f"coverage repairs: {changed}; field replacements={len(replaced)}")
    return plan


def _save_manifest(records: list[PatchRecord]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST_PATH.with_suffix(".jsonl.tmp")
    write_jsonl(temporary, sorted(records, key=lambda record: record.image_id))
    os.replace(temporary, MANIFEST_PATH)


def _save_plan(plan: dict[str, Any]) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PLAN_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, PLAN_PATH)


def _write_annotations(records: list[PatchRecord], plan_rows: list[dict[str, Any]]) -> None:
    rows = {row["image_id"]: row for row in plan_rows}
    previous: dict[str, dict[str, str]] = {}
    if ANNOTATION_PATH.is_file():
        with ANNOTATION_PATH.open(encoding="utf-8", newline="") as source:
            previous = {row["image_id"]: row for row in csv.DictReader(source)}
    ANNOTATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = ANNOTATION_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "image_id",
                "proposed_label",
                "reviewed_label",
                "review_status",
                "ambiguity_notes",
                "source_reference",
                "annotator_id",
                "reviewed_at",
                "review_rationale",
            ),
        )
        writer.writeheader()
        for record in sorted(records, key=lambda item: item.image_id):
            planned = rows[record.image_id]
            reviewed = previous.get(record.image_id, {})
            writer.writerow(
                merge_review_row(
                    record.image_id,
                    planned["proposed_label"],
                    planned["source_url"],
                    planned.get("ambiguity_notes", ""),
                    reviewed,
                )
            )
    os.replace(temporary, ANNOTATION_PATH)


def build_patches(plan: dict[str, Any]) -> list[PatchRecord]:
    earth_catalog = Client.open(PC_STAC)
    mars_catalog = Client.open(MARS_STAC)
    existing = (
        {record.image_id: record for record in read_jsonl(MANIFEST_PATH)}
        if MANIFEST_PATH.exists()
        else {}
    )
    records = dict(existing)
    failures: list[dict[str, str]] = []
    for row in plan["rows"]:
        destination = PATCH_DIR / f"{row['image_id']}.tif"
        prior = existing.get(row["image_id"])
        if _cached_patch_matches(row, prior, destination):
            continue
        patch_started = time.perf_counter()
        temp_destination = destination.with_suffix(".part.tif")
        temp_destination.unlink(missing_ok=True)
        try:
            href = _source_href(row, earth_catalog, mars_catalog)
            bands: tuple[int, ...] = (1, 2, 3) if row["body"] == "earth" else (1,)
            geometry = None
            error: Exception | None = None
            for attempt in range(3):
                try:
                    geometry = extract_metric_patch(
                        href,
                        temp_destination,
                        center_x=float(row["center_x"]),
                        center_y=float(row["center_y"]),
                        extent_m=float(row["extent_m"]),
                        native_gsd_m=float(row["native_gsd_m"]),
                        bands=bands,
                        min_valid_fraction=0.95,
                    )
                    break
                except (rasterio.errors.RasterioError, OSError, TimeoutError) as exc:
                    error = exc
                    temp_destination.unlink(missing_ok=True)
                    time.sleep(2**attempt)
            if geometry is None:
                if error:
                    raise error
                raise RuntimeError("patch generation failed without an error")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_destination, destination)
            temp_sidecar = temp_destination.with_suffix(temp_destination.suffix + ".json")
            sidecar = destination.with_suffix(destination.suffix + ".json")
            if temp_sidecar.is_file():
                os.replace(temp_sidecar, sidecar)
            processing = dict(row["processing"])
            processing.update(
                {
                    "source_asset_key": str(row["asset_key"]),
                    "patch_extent_m": str(geometry.width_m),
                    "patch_pixel_size_m": str(geometry.pixel_size_m),
                    "valid_pixel_fraction": str(geometry.valid_pixel_fraction),
                    "patch_center_x": str(row["center_x"]),
                    "patch_center_y": str(row["center_y"]),
                    "patch_processing_seconds": f"{time.perf_counter() - patch_started:.6f}",
                    "processing": "metric square; bilinear resampling to native source sampling",
                }
            )
            record = PatchRecord(
                image_id=row["image_id"],
                body=row["body"],
                path=str(destination.relative_to(ROOT)),
                source_id=row["source_id"],
                provider=row["provider"],
                source_url=row["source_url"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                native_gsd_m=float(row["native_gsd_m"]),
                width_m=geometry.width_m,
                height_m=geometry.height_m,
                acquired_at=row.get("acquired_at"),
                crs=geometry.crs,
                label="unknown",
                label_status="unknown",
                geographic_group=row["site_id"],
                checksum_sha256=_sha256(destination),
                processing=processing,
            )
            records[record.image_id] = record
            _save_manifest(list(records.values()))
            print(
                f"built {record.image_id}: {geometry.width_pixels}px, "
                f"valid={geometry.valid_pixel_fraction:.3f}"
            )
        except Exception as exc:
            temp_destination.unlink(missing_ok=True)
            temp_destination.with_suffix(temp_destination.suffix + ".json").unlink(missing_ok=True)
            failures.append({"image_id": str(row["image_id"]), "reason": str(exc)})
            print(f"failed {row['image_id']}: {exc}")
    result = sorted(records.values(), key=lambda record: record.image_id)
    checksum_groups: dict[str, list[str]] = {}
    for record in result:
        checksum_groups.setdefault(record.checksum_sha256, []).append(record.image_id)
    duplicates = [ids for ids in checksum_groups.values() if len(ids) > 1]
    if duplicates:
        raise RuntimeError(f"duplicate patch file contents detected: {duplicates[:5]}")
    ensure_no_overlaps(plan["rows"])
    _write_annotations(result, plan["rows"])
    if failures:
        failure_path = ROOT / "data/manifests/pilot-failures.json"
        failure_path.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    else:
        (ROOT / "data/manifests/pilot-failures.json").unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-plan", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.refresh_plan or not PLAN_PATH.exists():
        plan = discover_plan(config)
    else:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    planned_counts = Counter((row["body"], row["proposed_label"]) for row in plan["rows"])
    print(f"plan has {len(plan['rows'])} patches; rejected/discovery notes={len(plan['rejected'])}")
    for key, count in sorted(planned_counts.items()):
        print(f"{key[0]} {key[1]}: {count}")
    if args.plan_only:
        return
    plan = repair_plan_coverage(plan)
    records = build_patches(plan)
    print(
        f"manifest records: {len(records)}; manifest={MANIFEST_PATH}; annotations={ANNOTATION_PATH}"
    )


if __name__ == "__main__":
    main()
