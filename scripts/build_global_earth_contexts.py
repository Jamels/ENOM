"""Build an equal-area, globally distributed Earth terrain sample from public COGs.

Only 22x22 analysis grids and WorldCover class summaries are retained. Source
COGs are read through a byte-counting local proxy that rejects non-range reads.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import random
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import time
from typing import Any
from urllib.parse import unquote

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coordinates

from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/discovery/earth-glo90"
COPDEM_HOST = "copernicus-dem-90m.s3.eu-central-1.amazonaws.com"
WORLDCOVER_HOST = "esa-worldcover.s3.eu-central-1.amazonaws.com"
COPDEM_BASE = f"https://{COPDEM_HOST}"
WORLDCOVER_BASE = f"https://{WORLDCOVER_HOST}"
LAND_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_land.geojson"
)
TILE_LIST_URL = f"{COPDEM_BASE}/tileList.txt"
PIXEL_M = 463.05766716974557
CELLS = 22
CONTEXT_M = PIXEL_M * CELLS
SURFACE_CELLS = 102
WORLD_COVER_YEAR_VERSION = "2021-v200"
WORLD_COVER_CLASSES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_ice",
    80: "water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}
GROUPS = {
    "bare_sparse": {60},
    "forest": {10},
    "cropland": {40},
    "built_up": {50},
    "snow_ice": {70},
    "water": {80},
    "grass_shrub_wetland": {20, 30, 90, 95, 100},
}
SOURCE_PIXEL_LABELS = (
    "WorldCover proportions are estimated by modal class in a 102x102 grid "
    "of approximately 100 m cells over the 10.19 km footprint."
)


class TransferCounter:
    def __init__(
        self,
        initial: dict[str, Any] | None = None,
        progress_path: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        initial = initial or {}
        self.bytes: Counter[str] = Counter(initial.get("bytes_by_source", {}))
        self.ranges: Counter[str] = Counter(initial.get("range_responses_by_source", {}))
        self.progress_path = progress_path

    def add(self, host: str, size: int, ranged: bool) -> None:
        with self._lock:
            self.bytes[host] += size
            self.ranges[host] += int(ranged)
            if self.progress_path is not None:
                temporary = self.progress_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(self._snapshot_unlocked(), sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.progress_path)

    def _snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "bytes_by_source": dict(self.bytes),
            "range_responses_by_source": dict(self.ranges),
            "total_bytes": sum(self.bytes.values()),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()


def _proxy_handler(counter: TransferCounter) -> type[BaseHTTPRequestHandler]:
    upstream_sessions = threading.local()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _serve(self, method: str) -> None:
            route = parse_proxy_path(self.path)
            if route is None:
                self.send_error(404)
                return
            _category, host, suffix = route
            request_headers = {"Accept-Encoding": "identity", "User-Agent": "ENOM-GLO90/1.0"}
            for key in ("Range", "If-Range", "If-None-Match", "If-Modified-Since"):
                if key in self.headers:
                    request_headers[key] = self.headers[key]
            ranged = "Range" in request_headers
            if not is_bounded_source_request(method, request_headers):
                self.send_error(400, "unbounded source reads are disabled")
                return
            session = getattr(upstream_sessions, "session", None)
            if session is None:
                session = requests.Session()
                upstream_sessions.session = session
            try:
                response = session.request(
                    method,
                    f"https://{host}/{suffix}",
                    headers=request_headers,
                    stream=True,
                    timeout=(20, 60),
                )
            except requests.RequestException:
                self.send_error(502, "upstream data source failed")
                return
            if ranged and response.status_code != 206:
                response.close()
                self.send_error(502, "upstream did not honor the byte-range request")
                return
            self.send_response(response.status_code)
            for key in (
                "Content-Length",
                "Content-Range",
                "Content-Type",
                "Accept-Ranges",
                "ETag",
                "Last-Modified",
            ):
                if key in response.headers:
                    self.send_header(key, response.headers[key])
            self.send_header("Connection", "close")
            self.end_headers()
            transferred = 0
            try:
                if method != "HEAD" and response.status_code < 400:
                    transferred = forward_response_body(
                        response.iter_content(256 * 1024), self.wfile.write
                    )
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                response.close()
                counter.add(host, transferred, ranged)
                self.close_connection = True

        def do_GET(self) -> None:
            self._serve("GET")

        def do_HEAD(self) -> None:
            self._serve("HEAD")

    return Handler


def parse_proxy_path(path: str) -> tuple[str, str, str] | None:
    category, separator, suffix = unquote(path).lstrip("/").partition("/")
    if category == "copdem":
        host = COPDEM_HOST
    elif category == "worldcover":
        host = WORLDCOVER_HOST
    else:
        return None
    if not separator or not suffix:
        return None
    return category, host, suffix


def is_bounded_source_request(method: str, headers: dict[str, str]) -> bool:
    return method == "HEAD" or (method == "GET" and "Range" in headers)


def forward_response_body(blocks: Iterator[bytes], write: Any) -> int:
    """Count source bytes before forwarding each block to a local reader."""
    received = 0
    for block in blocks:
        if not block:
            continue
        received += len(block)
        try:
            write(block)
        except (BrokenPipeError, ConnectionResetError):
            break
    return received


@contextmanager
def metered_proxy(counter: TransferCounter) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _proxy_handler(counter))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def download_source(url: str, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded_bytes = 0
    if not destination.is_file():
        response = requests.get(url, headers={"Accept-Encoding": "identity"}, timeout=60)
        response.raise_for_status()
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
        downloaded_bytes = len(response.content)
    return hashlib.sha256(destination.read_bytes()).hexdigest(), downloaded_bytes


def _in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    """Ray-cast a point after unwrapping ring longitudes around the point."""
    inside = False
    previous_lon = ring[-1][0]
    previous_lat = ring[-1][1]
    previous_lon = longitude + ((previous_lon - longitude + 180) % 360) - 180
    for raw_lon, current_lat in ring:
        current_lon = longitude + ((raw_lon - longitude + 180) % 360) - 180
        crosses = (current_lat > latitude) != (previous_lat > latitude)
        if crosses:
            intersection = (previous_lon - current_lon) * (latitude - current_lat) / (
                previous_lat - current_lat
            ) + current_lon
            if longitude < intersection:
                inside = not inside
        previous_lon, previous_lat = current_lon, current_lat
    return inside


def point_is_land(longitude: float, latitude: float, features: list[dict[str, Any]]) -> bool:
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind, coordinates = geometry.get("type"), geometry.get("coordinates")
        polygons: Any
        if kind == "Polygon":
            polygons = [coordinates]
        elif kind == "MultiPolygon":
            polygons = coordinates
        else:
            polygons = []
        for polygon in polygons:
            if not polygon or not _in_ring(longitude, latitude, polygon[0]):
                continue
            if not any(_in_ring(longitude, latitude, hole) for hole in polygon[1:]):
                return True
    return False


def fibonacci_land_points(
    features: list[dict[str, Any]], *, candidates: int, seed: int
) -> list[tuple[float, float, int]]:
    """Uniform-area Fibonacci sphere points filtered by a coarse land mask."""
    golden_angle = math.pi * (3 - math.sqrt(5))
    points: list[tuple[float, float, int]] = []
    for index in range(candidates):
        z = 1 - 2 * (index + 0.5) / candidates
        latitude = math.degrees(math.asin(z))
        longitude = (math.degrees(index * golden_angle) + 180) % 360 - 180
        if point_is_land(longitude, latitude, features):
            points.append((longitude, latitude, index))
    random.Random(seed).shuffle(points)
    return points


def earth_crs(longitude: float, latitude: float) -> CRS:
    if latitude >= 84:
        return CRS.from_epsg(3413)
    if latitude <= -80:
        return CRS.from_epsg(3031)
    signed = (longitude + 180) % 360 - 180
    zone = min(60, max(1, int((signed + 180) // 6) + 1))
    return CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)


def metric_grid(longitude: float, latitude: float, cells: int = CELLS) -> tuple[CRS, Affine]:
    crs = earth_crs(longitude, latitude)
    signed = (longitude + 180) % 360 - 180
    xs, ys = transform_coordinates("EPSG:4326", crs, [signed], [latitude])
    posting = CONTEXT_M / cells
    return crs, from_origin(xs[0] - CONTEXT_M / 2, ys[0] + CONTEXT_M / 2, posting, posting)


def surface_grid(transform: Affine) -> Affine:
    """Return a 102×102 grid aligned to the full terrain footprint."""
    posting = CONTEXT_M / SURFACE_CELLS
    return from_origin(transform.c, transform.f, posting, posting)


def copdem_tile_name(longitude: float, latitude: float) -> str:
    signed = (longitude + 180) % 360 - 180
    south, west = math.floor(latitude), math.floor(signed)
    ns = f"N{south:02d}" if south >= 0 else f"S{abs(south):02d}"
    ew = f"E{west:03d}" if west >= 0 else f"W{abs(west):03d}"
    return f"Copernicus_DSM_COG_30_{ns}_00_{ew}_00_DEM"


def worldcover_tile_name(longitude: float, latitude: float) -> str:
    signed = (longitude + 180) % 360 - 180
    south = math.floor(latitude / 3) * 3
    west = math.floor(signed / 3) * 3
    ns = f"N{south:02d}" if south >= 0 else f"S{abs(south):02d}"
    ew = f"E{west:03d}" if west >= 0 else f"W{abs(west):03d}"
    return f"{ns}{ew}"


def worldcover_fractions(values: np.ndarray) -> dict[str, Any]:
    valid = values[(values != 0) & np.isin(values, list(WORLD_COVER_CLASSES))]
    if not valid.size:
        return {"valid_fraction": 0.0, "class_fractions": {}, "group_fractions": {}}
    classes = Counter(int(value) for value in valid)
    class_fractions = {
        WORLD_COVER_CLASSES[code]: count / valid.size for code, count in sorted(classes.items())
    }
    groups = {
        name: sum(classes.get(code, 0) for code in codes) / valid.size
        for name, codes in GROUPS.items()
    }
    return {
        "valid_fraction": float(valid.size / values.size),
        "sample_count": int(valid.size),
        "class_fractions": class_fractions,
        "group_fractions": groups,
        "sample_method": SOURCE_PIXEL_LABELS,
    }


def public_asset_url(url: str, category: str) -> str:
    host = COPDEM_HOST if category == "copdem" else WORLDCOVER_HOST
    suffix = unquote(url.split(f"/{category}/", 1)[1])
    return f"https://{host}/{suffix}"


def _disk_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _great_circle_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    delta_lon, delta_lat = lon2 - lon1, lat2 - lat1
    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, h)))


class SphericalSpacingIndex:
    """Near-constant-time minimum-spacing checks using 3D spherical buckets."""

    radius_km = 6371.0088

    def __init__(self, minimum_spacing_km: float) -> None:
        if (
            not math.isfinite(minimum_spacing_km)
            or minimum_spacing_km < 0
            or minimum_spacing_km > math.pi * self.radius_km
        ):
            raise ValueError(
                "minimum spacing must be finite and no greater than half a circumference"
            )
        self.minimum_spacing_km = minimum_spacing_km
        self.minimum_chord_km = (
            2 * self.radius_km * math.sin(minimum_spacing_km / (2 * self.radius_km))
        )
        self.cell_size = self.minimum_chord_km or 1.0
        self.buckets: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}

    def _coordinates(self, longitude: float, latitude: float) -> tuple[float, float, float]:
        lon, lat = math.radians(longitude), math.radians(latitude)
        radius = self.radius_km
        return (
            radius * math.cos(lat) * math.cos(lon),
            radius * math.cos(lat) * math.sin(lon),
            radius * math.sin(lat),
        )

    def _bucket(self, point: tuple[float, float, float]) -> tuple[int, int, int]:
        return (
            math.floor(point[0] / self.cell_size),
            math.floor(point[1] / self.cell_size),
            math.floor(point[2] / self.cell_size),
        )

    def add(self, longitude: float, latitude: float) -> None:
        point = self._coordinates(longitude, latitude)
        self.buckets.setdefault(self._bucket(point), []).append(point)

    def is_too_close(self, longitude: float, latitude: float) -> bool:
        if self.minimum_spacing_km <= 0:
            return False
        point = self._coordinates(longitude, latitude)
        bucket = self._bucket(point)
        threshold_squared = self.minimum_chord_km**2
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbors = self.buckets.get(
                        (bucket[0] + dx, bucket[1] + dy, bucket[2] + dz), ()
                    )
                    for other in neighbors:
                        if sum((point[i] - other[i]) ** 2 for i in range(3)) < threshold_squared:
                            return True
        return False


def geographic_band(longitude: float, latitude: float) -> str:
    lat_band = int(math.floor((latitude + 90) / 10) * 10 - 90)
    lon_band = int(math.floor((longitude % 360) / 30) * 30)
    return f"{lat_band:+03d}_to_{lat_band + 10:+03d}|{lon_band:03d}_to_{lon_band + 30:03d}"


def context_footprint_area_km2(raster_path: Path) -> float:
    """Estimate ground area from geodesic distances between projected edge midpoints."""
    with rasterio.open(raster_path) as source:
        transform = source.transform
        center_x = transform.c + source.width * transform.a / 2
        center_y = transform.f + source.height * transform.e / 2
        edge_points = [
            (transform.c, center_y),
            (transform.c + source.width * transform.a, center_y),
            (center_x, transform.f),
            (center_x, transform.f + source.height * transform.e),
        ]
        longitude, latitude = transform_coordinates(
            source.crs,
            "EPSG:4326",
            [point[0] for point in edge_points],
            [point[1] for point in edge_points],
        )
    width_km = _great_circle_km((longitude[0], latitude[0]), (longitude[1], latitude[1]))
    height_km = _great_circle_km((longitude[2], latitude[2]), (longitude[3], latitude[3]))
    return width_km * height_km


def land_context(
    longitude: float,
    latitude: float,
    observation_id: str,
    copdem_url: str,
    worldcover_url: str,
    output_dir: Path,
) -> tuple[dict[str, Any], float, str | None, int]:
    crs, transform = metric_grid(longitude, latitude)
    signed = (longitude + 180) % 360 - 180
    raster_path = output_dir / f"{observation_id}.tif"
    sidecar_path = raster_path.with_suffix(".tif.json")
    temporary_raster = raster_path.with_suffix(".tif.part")
    peak_storage_bytes = _disk_bytes(output_dir)
    try:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_MAX_RETRY="4",
            GDAL_HTTP_RETRY_DELAY="2",
            VSI_CACHE="FALSE",
            GDAL_CACHEMAX=64,
            CPL_TMPDIR=str(output_dir / "tmp"),
        ):
            with rasterio.open(copdem_url) as source:
                with WarpedVRT(
                    source,
                    crs=crs,
                    transform=transform,
                    width=CELLS,
                    height=CELLS,
                    resampling=Resampling.bilinear,
                ) as vrt:
                    dem = vrt.read(1, masked=True).astype(np.float32)
                    values = dem.filled(np.nan)
                    valid = ~np.ma.getmaskarray(dem) & np.isfinite(values)
            valid_fraction = float(valid.mean())
            if valid_fraction < 0.9:
                raise ValueError(f"insufficient valid DEM support ({valid_fraction:.1%})")
            profile = {
                "driver": "GTiff",
                "width": CELLS,
                "height": CELLS,
                "count": 1,
                "dtype": "float32",
                "crs": crs,
                "transform": transform,
                "nodata": np.nan,
                "compress": "deflate",
                "predictor": 3,
            }
            with rasterio.open(temporary_raster, "w", **profile) as destination:
                destination.write(values, 1)
            peak_storage_bytes = max(peak_storage_bytes, _disk_bytes(output_dir))
            measurements = [
                item.model_dump(mode="json")
                for item in terrain_features(
                    temporary_raster,
                    observation_id=observation_id,
                    provider="Copernicus DEM GLO-90 / AWS Open Data",
                    product_id=copdem_tile_name(longitude, latitude),
                    source_url=public_asset_url(copdem_url, "copdem"),
                    processing_method=(
                        "Public GLO-90 COG byte-range read; bilinear warp to a local metric "
                        "22x22 grid at 463.0577 m posting for cross-body exploratory comparison."
                    ),
                )
            ]
            temporary_raster.replace(raster_path)

            cover: dict[str, Any] = {
                "status": "unavailable",
                "dataset_id": f"esa-worldcover-{WORLD_COVER_YEAR_VERSION}",
            }
            try:
                with rasterio.open(worldcover_url) as source:
                    with WarpedVRT(
                        source,
                        crs=crs,
                        transform=surface_grid(transform),
                        width=SURFACE_CELLS,
                        height=SURFACE_CELLS,
                        resampling=Resampling.mode,
                        src_nodata=0,
                        nodata=0,
                    ) as vrt:
                        classified = vrt.read(1)
                cover_summary = worldcover_fractions(classified)
                cover = cover_summary | {
                    "status": "available" if cover_summary["valid_fraction"] == 1.0 else "partial",
                    "dataset_id": f"esa-worldcover-{WORLD_COVER_YEAR_VERSION}",
                    "source_tile": worldcover_tile_name(longitude, latitude),
                    "source_url": public_asset_url(worldcover_url, "worldcover"),
                }
            except (rasterio.errors.RasterioError, OSError, requests.RequestException):
                cover = cover | {"status": "unavailable"}
    finally:
        temporary_raster.unlink(missing_ok=True)

    sidecar: dict[str, Any] = {
        "observation_id": observation_id,
        "place_id": observation_id,
        "body": "earth",
        "name": f"Copernicus GLO-90 · {latitude:.3f}, {signed:.3f}",
        "longitude_east_deg": longitude % 360,
        "latitude_deg": latitude,
        "dataset_id": "cop-dem-glo-90",
        "provider": "Copernicus DEM / AWS Open Data Registry",
        "source_product_id": copdem_tile_name(longitude, latitude),
        "source_url": public_asset_url(copdem_url, "copdem"),
        "source_resolution_m": 90,
        "source_vertical_reference": "EGM2008 orthometric height",
        "processing_crs": crs.to_string(),
        "output_pixel_size_m": [PIXEL_M, PIXEL_M],
        "context_size_m": CONTEXT_M,
        "valid_pixel_fraction": valid_fraction,
        "observed_cell_fraction": valid_fraction,
        "land_cover": cover,
        "uncertainty_note": (
            "Copernicus GLO-90 is a digital surface model; vegetation, structures, "
            "source mosaicking and source vertical error are not corrected."
        ),
        "missing_data_semantics": "Source nodata remains masked; no-data is not treated as zero.",
        "processing_method": (
            "A local 22x22 metric window was read from a remotely hosted GLO-90 COG; "
            "source tiles are not saved. The output is the reproducible analysis raster."
        ),
        "sampling_method": (
            "Fibonacci sphere equal-area candidates filtered by Natural Earth 1:110m land polygons"
        ),
        "measurements": measurements,
        "output": str(raster_path.relative_to(ROOT)),
    }
    sidecar_tmp = sidecar_path.with_suffix(".json.part")
    try:
        sidecar_tmp.write_text(
            json.dumps(sidecar, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        peak_storage_bytes = max(peak_storage_bytes, _disk_bytes(output_dir))
        sidecar_tmp.replace(sidecar_path)
    finally:
        sidecar_tmp.unlink(missing_ok=True)
    return (
        sidecar,
        raster_path.stat().st_size + sidecar_path.stat().st_size,
        cover["status"],
        peak_storage_bytes,
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--candidate-count", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=6112026)
    parser.add_argument("--min-spacing-km", type=float, default=100.0)
    parser.add_argument("--max-storage-bytes", type=int, default=5_000_000_000)
    parser.add_argument("--max-source-bytes", type=int, default=4_000_000_000)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if (
        args.target_count < 1
        or args.candidate_count < args.target_count
        or not math.isfinite(args.min_spacing_km)
        or args.min_spacing_km < 0
        or args.min_spacing_km > math.pi * 6371.0088
        or args.max_storage_bytes < 1
        or args.max_source_bytes < 1
    ):
        parser.error("target/candidate counts and minimum spacing are invalid")

    output_dir = args.output_dir.resolve()
    try:
        output_dir.relative_to(ROOT)
    except ValueError:
        parser.error("--output-dir must be within the ENOM checkout")
    output_dir.mkdir(parents=True, exist_ok=True)
    build_lock = (output_dir / ".build.lock").open("a+")
    try:
        fcntl.flock(build_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        build_lock.close()
        parser.error(f"a global Earth context build is already active in {output_dir}")
    (output_dir / "tmp").mkdir(exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    source_dir = output_dir / "source-metadata"
    land_path = source_dir / "natural-earth-ne_110m_land.geojson"
    tile_list_path = source_dir / "copernicus-dem-glo-90-tileList.txt"
    land_hash, land_download_bytes = download_source(LAND_URL, land_path)
    tile_list_hash, tile_list_download_bytes = download_source(TILE_LIST_URL, tile_list_path)
    land_geojson = json.loads(land_path.read_text(encoding="utf-8"))
    features = land_geojson["features"]
    tile_names = set(tile_list_path.read_text(encoding="utf-8").split())
    inputs = {
        "sampler": "fibonacci-sphere-land-v1",
        "land_mask_url": LAND_URL,
        "land_mask_sha256": land_hash,
        "copdem_tile_list_url": TILE_LIST_URL,
        "copdem_tile_list_sha256": tile_list_hash,
        "worldcover_dataset": "ESA WorldCover 2021 v200",
        "worldcover_dataset_url": "https://doi.org/10.5281/zenodo.7254221",
        "target_grid_cells": CELLS,
        "target_posting_m": PIXEL_M,
        "target_context_m": CONTEXT_M,
        "surface_sample_cells": SURFACE_CELLS,
        "seed": args.seed,
        "minimum_spacing_km": args.min_spacing_km,
        "candidate_count": args.candidate_count,
    }
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("inputs") != inputs:
            raise ValueError(
                "existing global Earth manifest has incompatible source or sampler identity"
            )
    else:
        manifest = {
            "version": 1,
            "inputs": inputs,
            "target_count": args.target_count,
            "started_at_unix": time(),
            "contexts": [],
            "candidate_indices": [],
            "processed_candidates": 0,
            "failures": {},
            "land_cover_status_counts": {},
            "source_transfer": {
                "bytes_by_source": {},
                "range_responses_by_source": {},
                "total_bytes": 0,
            },
        }
        _atomic_json(manifest_path, manifest)

    existing = manifest["contexts"]
    candidate_indices = set(manifest["candidate_indices"])
    spacing_index = SphericalSpacingIndex(args.min_spacing_km)
    for name in existing:
        sidecar_path = output_dir / f"{name}.tif.json"
        if not sidecar_path.is_file() or not (output_dir / f"{name}.tif").is_file():
            raise ValueError(f"manifest references incomplete context {name}")
        item = json.loads(sidecar_path.read_text(encoding="utf-8"))
        longitude = float(item["longitude_east_deg"])
        latitude = float(item["latitude_deg"])
        spacing_index.add(longitude, latitude)
    points = fibonacci_land_points(features, candidates=args.candidate_count, seed=args.seed)
    progress_path = output_dir / ".transfer-progress.json"
    transfer_state = manifest.get("source_transfer")
    if progress_path.is_file():
        progress_state = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress_state.get("total_bytes", 0) > (transfer_state or {}).get("total_bytes", 0):
            transfer_state = progress_state
    transfer = TransferCounter(transfer_state, progress_path)
    failures: Counter[str] = Counter(manifest.get("failures", {}))
    cover_status: Counter[str] = Counter(manifest.get("land_cover_status_counts", {}))
    processed = int(manifest.get("processed_candidates", 0))
    source_metadata_bytes = int(
        manifest.get(
            "source_metadata_bytes",
            land_download_bytes + tile_list_download_bytes or _disk_bytes(source_dir),
        )
    )
    manifest.setdefault("started_at_unix", time())
    manifest["target_count"] = args.target_count
    peak_storage = max(
        int(manifest.get("peak_additional_storage_bytes", 0)),
        _disk_bytes(output_dir),
    )
    with metered_proxy(transfer) as proxy:
        for longitude, latitude, candidate_index in points:
            if len(existing) >= args.target_count:
                break
            if source_metadata_bytes + transfer.snapshot()["total_bytes"] >= args.max_source_bytes:
                break
            if candidate_index in candidate_indices:
                continue
            processed += 1
            tile = copdem_tile_name(longitude, latitude)
            if tile not in tile_names:
                failures["no_copdem_tile"] += 1
                candidate_indices.add(candidate_index)
                if processed % 25 == 0:
                    manifest.update(
                        processed_candidates=processed,
                        candidate_indices=sorted(candidate_indices),
                        failures=dict(failures),
                    )
                    _atomic_json(manifest_path, manifest)
                continue
            if spacing_index.is_too_close(longitude, latitude):
                failures["minimum_spacing"] += 1
                candidate_indices.add(candidate_index)
                if processed % 25 == 0:
                    manifest.update(
                        processed_candidates=processed,
                        candidate_indices=sorted(candidate_indices),
                        failures=dict(failures),
                    )
                    _atomic_json(manifest_path, manifest)
                continue
            context_id = f"copdem_glo90_{len(existing) + 1:06d}"
            copdem_name = tile
            copdem_url = f"{proxy}/copdem/{copdem_name}/{copdem_name}.tif"
            cover_name = worldcover_tile_name(longitude, latitude)
            cover_asset = f"ESA_WorldCover_10m_2021_v200_{cover_name}_Map.tif"
            cover_url = f"{proxy}/worldcover/v200/2021/map/{cover_asset}"
            try:
                item, item_bytes, cover_quality, item_peak_storage = land_context(
                    longitude,
                    latitude,
                    context_id,
                    copdem_url,
                    cover_url,
                    output_dir,
                )
            except (
                OSError,
                ValueError,
                rasterio.errors.RasterioError,
                requests.RequestException,
            ) as error:
                failures[type(error).__name__ + ":" + str(error)[:100]] += 1
                candidate_indices.add(candidate_index)
                if (processed % 25) == 0:
                    manifest.update(
                        processed_candidates=processed,
                        candidate_indices=sorted(candidate_indices),
                        failures=dict(failures),
                        source_transfer=transfer.snapshot(),
                        source_metadata_bytes=source_metadata_bytes,
                    )
                    _atomic_json(manifest_path, manifest)
                if (
                    source_metadata_bytes + transfer.snapshot()["total_bytes"]
                    >= args.max_source_bytes
                ):
                    manifest.update(
                        processed_candidates=processed,
                        candidate_indices=sorted(candidate_indices),
                        failures=dict(failures),
                        source_transfer=transfer.snapshot(),
                        source_metadata_bytes=source_metadata_bytes,
                    )
                    _atomic_json(manifest_path, manifest)
                    raise RuntimeError(
                        "source byte budget reached; resumable manifest saved"
                    ) from error
                continue
            storage = _disk_bytes(output_dir)
            peak_storage = max(peak_storage, storage, item_peak_storage)
            if storage > args.max_storage_bytes:
                (output_dir / f"{context_id}.tif").unlink(missing_ok=True)
                (output_dir / f"{context_id}.tif.json").unlink(missing_ok=True)
                manifest.update(
                    candidate_indices=sorted(candidate_indices),
                    failures=dict(failures),
                    source_transfer=transfer.snapshot(),
                    source_metadata_bytes=source_metadata_bytes,
                    additional_storage_bytes=_disk_bytes(output_dir),
                    peak_additional_storage_bytes=peak_storage,
                )
                _atomic_json(manifest_path, manifest)
                raise RuntimeError("global Earth output exceeded the configured storage budget")
            existing.append(context_id)
            candidate_indices.add(candidate_index)
            spacing_index.add(longitude, latitude)
            cover_status[str(cover_quality)] += 1
            manifest.update(
                contexts=existing,
                candidate_indices=sorted(candidate_indices),
                processed_candidates=processed,
                failures=dict(failures),
                land_cover_status_counts=dict(cover_status),
                source_transfer=transfer.snapshot(),
                source_metadata_bytes=source_metadata_bytes,
                additional_storage_bytes=storage,
                peak_additional_storage_bytes=peak_storage,
            )
            _atomic_json(manifest_path, manifest)
            if len(existing) % 25 == 0:
                print(
                    json.dumps(
                        {
                            "contexts": len(existing),
                            "target": args.target_count,
                            "processed_candidates": processed,
                            "source_bytes": source_metadata_bytes
                            + transfer.snapshot()["total_bytes"],
                            "additional_storage_bytes": storage,
                            "land_cover_status": cover_quality,
                        }
                    ),
                    flush=True,
                )

    by_latitude_band: Counter[str] = Counter()
    by_longitude_band: Counter[str] = Counter()
    land_candidate_bins = Counter(
        geographic_band(longitude, latitude) for longitude, latitude, _ in points
    )
    context_bins: set[str] = set()
    context_bin_counts: Counter[str] = Counter()
    summed_context_footprint_area_km2 = 0.0
    classified_footprint_area_km2 = 0.0
    mapped_nonwater_area_km2 = 0.0
    worldcover_contexts_with_classification = 0
    for name in existing:
        item = json.loads((output_dir / f"{name}.tif.json").read_text(encoding="utf-8"))
        latitude, longitude = float(item["latitude_deg"]), float(item["longitude_east_deg"])
        lat_band = int(math.floor((latitude + 90) / 10) * 10 - 90)
        lon_band = int(math.floor(longitude / 30) * 30)
        by_latitude_band[f"{lat_band:+03d}_to_{lat_band + 10:+03d}"] += 1
        by_longitude_band[f"{lon_band:03d}_to_{lon_band + 30:03d}"] += 1
        band = geographic_band(longitude, latitude)
        context_bins.add(band)
        context_bin_counts[band] += 1
        area = context_footprint_area_km2(output_dir / f"{name}.tif")
        summed_context_footprint_area_km2 += area
        land_cover = item.get("land_cover", {})
        if land_cover.get("status") == "available":
            groups = land_cover.get("group_fractions", {})
            water_fraction = groups.get("water")
            valid_fraction = land_cover.get("valid_fraction")
            if (
                isinstance(water_fraction, (int, float))
                and isinstance(valid_fraction, (int, float))
                and 0 <= valid_fraction <= 1
            ):
                worldcover_contexts_with_classification += 1
                mapped_area = area * float(valid_fraction)
                classified_footprint_area_km2 += mapped_area
                mapped_nonwater_area_km2 += mapped_area * (1 - float(water_fraction))
    elapsed = time() - float(manifest["started_at_unix"])
    complete = len(existing) >= args.target_count
    if complete:
        progress_path.unlink(missing_ok=True)
    manifest.update(
        contexts=existing,
        candidate_indices=sorted(candidate_indices),
        processed_candidates=processed,
        failures=dict(failures),
        land_cover_status_counts=dict(cover_status),
        source_transfer=transfer.snapshot(),
        source_metadata_bytes=source_metadata_bytes,
        source_byte_budget_overshoot_bytes=max(
            0,
            source_metadata_bytes + transfer.snapshot()["total_bytes"] - args.max_source_bytes,
        ),
        additional_storage_bytes=_disk_bytes(output_dir),
        peak_additional_storage_bytes=max(peak_storage, _disk_bytes(output_dir)),
        latitude_band_counts=dict(by_latitude_band),
        longitude_band_counts=dict(by_longitude_band),
        land_candidate_count=len(points),
        land_candidate_bin_counts=dict(land_candidate_bins),
        context_bin_counts=dict(context_bin_counts),
        coverage_gap_bins=sorted(set(land_candidate_bins) - context_bins),
        summed_context_footprint_area_km2=summed_context_footprint_area_km2,
        worldcover_classified_footprint_area_km2=classified_footprint_area_km2,
        worldcover_mapped_nonwater_area_km2=mapped_nonwater_area_km2,
        worldcover_contexts_with_classification=worldcover_contexts_with_classification,
        elapsed_seconds=elapsed,
        complete=complete,
    )
    _atomic_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "complete": manifest["complete"],
                "contexts": len(existing),
                "target_count": args.target_count,
                "processed_candidates": processed,
                "failures": dict(failures),
                "land_cover_status_counts": dict(cover_status),
                "source_metadata_bytes": source_metadata_bytes,
                "source_byte_budget_overshoot_bytes": manifest[
                    "source_byte_budget_overshoot_bytes"
                ],
                "source_transfer": transfer.snapshot(),
                "summed_context_footprint_area_km2": manifest["summed_context_footprint_area_km2"],
                "worldcover_classified_footprint_area_km2": manifest[
                    "worldcover_classified_footprint_area_km2"
                ],
                "worldcover_mapped_nonwater_area_km2": manifest[
                    "worldcover_mapped_nonwater_area_km2"
                ],
                "coverage_gap_bins": manifest["coverage_gap_bins"],
                "additional_storage_bytes": manifest["additional_storage_bytes"],
                "peak_additional_storage_bytes": manifest["peak_additional_storage_bytes"],
                "elapsed_seconds": manifest["elapsed_seconds"],
                "latitude_band_counts": dict(by_latitude_band),
                "longitude_band_counts": dict(by_longitude_band),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
