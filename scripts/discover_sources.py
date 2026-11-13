#!/usr/bin/env python3
"""Discover Earth Sentinel-2 and Mars CTX source observations; download nothing."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EARTH_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
MARS_ODE = "https://oderest.rsl.wustl.edu/live2/"


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TwinWorld-Phase0/0.1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def discover_earth(bbox: list[float], start: str, end: str, limit: int) -> list[dict[str, Any]]:
    result = post_json(
        EARTH_STAC,
        {
            "collections": ["sentinel-2-l2a"],
            "bbox": bbox,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": limit,
            "query": {"eo:cloud_cover": {"lte": 20}},
            "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        },
    )
    candidates = []
    for item in result.get("features", []):
        assets = item.get("assets", {})
        bands = [key for key in ("B02", "B03", "B04") if key in assets]
        candidates.append(
            {
                "body": "earth",
                "provider": "Microsoft Planetary Computer / ESA Copernicus",
                "collection": "sentinel-2-l2a",
                "source_id": item["id"],
                "source_url": (
                    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
                    f"sentinel-2-l2a/items/{urllib.parse.quote(item['id'], safe='')}"
                ),
                "asset_keys_rgb": bands,
                "asset_hrefs_rgb": {key: assets[key].get("href") for key in bands},
                "rendered_preview_href": assets.get("rendered_preview", {}).get("href"),
                "datetime": item.get("properties", {}).get("datetime"),
                "platform": item.get("properties", {}).get("platform"),
                "cloud_cover_percent": item.get("properties", {}).get("eo:cloud_cover"),
                "bbox": item.get("bbox"),
                "geometry": item.get("geometry"),
                "crs": item.get("properties", {}).get("proj:code")
                or item.get("properties", {}).get("proj:epsg"),
                "native_gsd_m": 10,
                "selection_note": "AOI/time/cloud filter; landform label remains unreviewed",
            }
        )
    return candidates


def discover_mars(bbox: list[float], limit: int) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    params = urllib.parse.urlencode(
        {
            "query": "product",
            "target": "mars",
            "ihid": "MRO",
            "iid": "CTX",
            "pt": "EDR",
            "results": "cm",
            "loc": "b",
            "westernlon": west,
            "easternlon": east,
            "minlat": south,
            "maxlat": north,
            "start": 1,
            "limit": limit,
        }
    )
    request = urllib.request.Request(
        f"{MARS_ODE}?{params}", headers={"User-Agent": "TwinWorld-Phase0/0.1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        root = ET.fromstring(response.read())
    if root.findtext("Status") != "Success":
        raise RuntimeError(
            f"Mars ODE search failed: {root.findtext('Status')} {root.findtext('Error')}"
        )
    candidates = []
    for product in root.findall(".//Product"):
        product_id = product.findtext("Product_id") or product.findtext("ProductId")
        if not product_id:
            product_url = product.findtext("ProductURL") or ""
            product_id = urllib.parse.parse_qs(urllib.parse.urlparse(product_url).query).get(
                "product_id", [None]
            )[0]
        if not product_id:
            continue
        map_scale = product.findtext("Map_scale")
        candidates.append(
            {
                "body": "mars",
                "provider": "NASA PDS Geosciences Node Mars ODE / MRO CTX",
                "source_id": product_id,
                "source_url": product.findtext("ProductURL"),
                "label_url": product.findtext("LabelURL"),
                "datetime": product.findtext("Observation_time"),
                "center_latitude": product.findtext("Center_latitude"),
                "center_longitude": product.findtext("Center_longitude"),
                "native_gsd_m": None,
                "ode_map_scale_m_per_px": float(map_scale) if map_scale else None,
                "bbox": {
                    "west": product.findtext("Westernmost_longitude"),
                    "south": product.findtext("Minimum_latitude"),
                    "east": product.findtext("Easternmost_longitude"),
                    "north": product.findtext("Maximum_latitude"),
                },
                "comment": product.findtext("Comment"),
                "selection_note": "ODE footprint/time query; landform label remains unreviewed",
            }
        )
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/manifests/candidate-sources.json"))
    parser.add_argument("--earth-bbox", nargs=4, type=float, default=[14, -25, 16, -23])
    parser.add_argument("--mars-bbox", nargs=4, type=float, default=[65, 7, 70, 10])
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    candidates = discover_earth(args.earth_bbox, args.start, args.end, args.limit)
    candidates += discover_mars(args.mars_bbox, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run = {
        "discovered_at": datetime.now(UTC).isoformat(),
        "earth_bbox_wgs84": args.earth_bbox,
        "mars_bbox_east_lon_lat": args.mars_bbox,
        "earth_date_range": [args.start, args.end],
        "limit_per_source": args.limit,
        "downloaded": False,
        "candidates": candidates,
    }
    args.out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(candidates)} source candidates to {args.out}")
    earth_count = sum(x["body"] == "earth" for x in candidates)
    mars_count = sum(x["body"] == "mars" for x in candidates)
    print(f"Earth: {earth_count}; Mars: {mars_count}")


if __name__ == "__main__":
    main()
