"""Offline scientific context index and footprint lookup.

The builder reads local terrain products; the reader only uses SQLite. Geographic
bounds are conservative shortcuts: containment is checked in each raster CRS.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform

DATASETS = {
    "cop-dem-glo-30": "earth",
    "cop-dem-glo-90": "earth",
    "nasadem-hgt": "earth",
    "mola-meg128": "mars",
    "lro-lola-gdr-ldem-64": "moon",
    "lro-lola-gdr-polar-ldem-120m": "moon",
}
SCHEMA = """
CREATE TABLE release(id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
  builder_sha256 TEXT NOT NULL);
CREATE TABLE contexts(id INTEGER PRIMARY KEY, observation_id TEXT NOT NULL, body TEXT NOT NULL,
  crs TEXT NOT NULL, geographic_crs TEXT NOT NULL, affine TEXT NOT NULL,
  width INTEGER NOT NULL, height INTEGER NOT NULL, metadata TEXT NOT NULL);
CREATE TABLE places(id TEXT PRIMARY KEY, body TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE context_places(context_id INTEGER PRIMARY KEY REFERENCES contexts(id),
  place_id TEXT NOT NULL REFERENCES places(id));
CREATE TABLE context_quality(context_id INTEGER PRIMARY KEY REFERENCES contexts(id),
  valid_cell_fraction REAL, retained_cell_fraction REAL, native_direct_fraction REAL,
  missing_data_semantics TEXT, uncertainty_note TEXT);
CREATE TABLE measurements(context_id INTEGER NOT NULL REFERENCES contexts(id),
  ordinal INTEGER NOT NULL, name TEXT NOT NULL, value REAL, units TEXT NOT NULL,
  availability TEXT NOT NULL, spatial_scale_m REAL, payload TEXT NOT NULL,
  PRIMARY KEY(context_id, ordinal));
CREATE TABLE source_products(context_id INTEGER NOT NULL REFERENCES contexts(id),
  role TEXT NOT NULL, product_id TEXT NOT NULL, source_url TEXT,
  PRIMARY KEY(context_id, role));
CREATE TABLE bounds(id INTEGER PRIMARY KEY, context_id INTEGER NOT NULL REFERENCES contexts(id));
CREATE VIRTUAL TABLE bounds_index USING rtree(id, min_lon, max_lon, min_lat, max_lat);
"""

LAND_COVER_GROUPS = {
    "bare_sparse",
    "forest",
    "cropland",
    "built_up",
    "snow_ice",
    "water",
    "grass_shrub_wetland",
}


def _validated_land_cover(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Return a trustworthy WorldCover summary, or None for unusable metadata."""
    cover = metadata.get("land_cover")
    if not isinstance(cover, dict):
        return None
    status = cover.get("status")
    if status == "unavailable":
        return cover
    if status not in {"available", "partial"}:
        return None
    dataset_id = cover.get("dataset_id")
    if dataset_id != "esa-worldcover-2021-v200":
        return None
    valid_fraction = cover.get("valid_fraction")
    sample_count = cover.get("sample_count")
    groups = cover.get("group_fractions")
    if (
        isinstance(valid_fraction, bool)
        or not isinstance(valid_fraction, (int, float))
        or not math.isfinite(valid_fraction)
        or not 0 < valid_fraction <= 1
        or isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count <= 0
        or sample_count > 102 * 102
        or not isinstance(groups, dict)
        or set(groups) != LAND_COVER_GROUPS
    ):
        return None
    if not math.isclose(valid_fraction, sample_count / (102 * 102), rel_tol=0, abs_tol=1e-9):
        return None
    values = list(groups.values())
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
        for value in values
    ):
        return None
    if not math.isclose(sum(values), 1.0, rel_tol=0, abs_tol=1e-6):
        return None
    if (status == "available") != math.isclose(valid_fraction, 1.0, rel_tol=0, abs_tol=1e-9):
        return None
    if not isinstance(cover.get("source_tile"), str) or not cover["source_tile"]:
        return None
    return cover


def _surface_distance_m(lon1: float, lat1: float, lon2: float, lat2: float, radius: float) -> float:
    """Spherical great-circle distance; adequate for regional prototype screening."""
    a, b = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _geographic_crs(body: str, crs: CRS) -> CRS:
    if body == "earth":
        return CRS.from_epsg(4326)
    # The geographic CRS must share the raster's actual spheroid, including
    # the product's spherical radius. Preserve its native WKT alongside it.
    radius = 1737400 if body == "moon" else 3396000
    return CRS.from_proj4(f"+proj=longlat +R={radius} +no_defs")


def build_index(root: Path, output: Path) -> dict[str, Any]:
    """Build an index from existing sidecars and local rasters, offline."""
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    sidecars = list((root / "data/terrain").glob("*.tif.json"))
    nasadem_dir = root / "artifacts/discovery/nasadem"
    manifest_path = nasadem_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != 1 or not isinstance(manifest.get("contexts"), list):
            raise ValueError("unsupported NASADEM context manifest")
        for name in manifest["contexts"]:
            if (
                not isinstance(name, str)
                or not name.startswith("nasadem_")
                or not name.replace("_", "").isalnum()
            ):
                raise ValueError("invalid NASADEM context ID in manifest")
            sidecar = nasadem_dir / f"{name}.tif.json"
            if not sidecar.is_file():
                raise ValueError(f"NASADEM manifest references missing context {name}")
            sidecars.append(sidecar)
    copernicus_dir = root / "artifacts/discovery/copernicus"
    copernicus_manifest = copernicus_dir / "manifest.json"
    if copernicus_manifest.is_file():
        manifest = json.loads(copernicus_manifest.read_text(encoding="utf-8"))
        if manifest.get("version") != 1 or not isinstance(manifest.get("contexts"), list):
            raise ValueError("unsupported Copernicus context manifest")
        for name in manifest["contexts"]:
            prefix = "candidate_earth_expanded_"
            if (
                not isinstance(name, str)
                or not name.startswith(prefix)
                or not name.replace("_", "").isalnum()
            ):
                raise ValueError("invalid Copernicus context ID in manifest")
            sidecar = (
                copernicus_dir
                / f"cop-dem-candidate-{name.removeprefix('candidate_earth_')}.tif.json"
            )
            if not sidecar.is_file():
                raise ValueError(f"Copernicus manifest references missing context {name}")
            sidecars.append(sidecar)
    global_earth_dir = root / "artifacts/discovery/earth-glo90"
    global_earth_manifest = global_earth_dir / "manifest.json"
    if global_earth_manifest.is_file():
        manifest = json.loads(global_earth_manifest.read_text(encoding="utf-8"))
        if manifest.get("version") != 1 or not isinstance(manifest.get("contexts"), list):
            raise ValueError("unsupported global Earth context manifest")
        for name in manifest["contexts"]:
            if (
                not isinstance(name, str)
                or not name.startswith("copdem_glo90_")
                or not name.replace("_", "").isalnum()
            ):
                raise ValueError("invalid global Earth context ID in manifest")
            sidecar = global_earth_dir / f"{name}.tif.json"
            if not sidecar.is_file():
                raise ValueError(f"global Earth manifest references missing context {name}")
            sidecars.append(sidecar)
    for path in sorted(sidecars):
        metadata = json.loads(path.read_text())
        body = DATASETS.get(metadata.get("dataset_id"))
        if not body:
            continue
        # Land-cover metadata is a separately sourced categorical observation.
        # A malformed summary must never become a usable class filter merely
        # because the elevation raster itself is valid.
        if metadata.get("dataset_id") == "cop-dem-glo-90":
            cover = _validated_land_cover(metadata)
            if cover is None:
                metadata["land_cover"] = {
                    "status": "unavailable",
                    "dataset_id": "esa-worldcover-2021-v200",
                    "unavailable_reason": "missing or invalid WorldCover sidecar summary",
                }
        raster = metadata.get("output") or metadata.get("terrain_raster")
        if not raster or not (root / raster).is_file():
            skipped.append(str(path.relative_to(root)))
            continue
        count_path = metadata.get("count_raster")
        count_datasets = {"mola-meg128", "lro-lola-gdr-polar-ldem-120m"}
        if metadata.get("dataset_id") in count_datasets:
            if not count_path or not (root / count_path).is_file():
                skipped.append(str(path.relative_to(root)) + ": missing count raster")
                continue
            with rasterio.open(root / count_path) as counts:
                count_grid = counts.read(1, masked=True).filled(0)
                count_observed = count_grid > 0
                support = float(np.count_nonzero(count_observed) / count_observed.size)
                count_width, count_height = counts.width, counts.height
                count_crs, count_transform = counts.crs, counts.transform
            expected_key = (
                "observed_cell_fraction"
                if metadata["dataset_id"] == "mola-meg128"
                else "native_count_crop_fraction"
            )
            expected = metadata.get(expected_key)
            if not isinstance(expected, (int, float)) or not math.isclose(
                support, expected, rel_tol=0, abs_tol=1e-9
            ):
                skipped.append(str(path.relative_to(root)) + ": count support mismatch")
                continue
            if metadata["dataset_id"] == "mola-meg128":
                with rasterio.open(root / raster) as elevation:
                    elevation_grid = elevation.read(1, masked=True)
                    elevation_values = np.asarray(elevation_grid.data, dtype=np.float64)
                    elevation_valid = ~np.ma.getmaskarray(elevation_grid) & np.isfinite(
                        elevation_values
                    )
                    aligned = (
                        elevation.width == count_width
                        and elevation.height == count_height
                        and elevation.crs == count_crs
                        and np.allclose(
                            tuple(elevation.transform), tuple(count_transform), rtol=0, atol=1e-9
                        )
                    )
                if not aligned or not np.array_equal(elevation_valid, count_observed):
                    skipped.append(str(path.relative_to(root)) + ": elevation/count grid mismatch")
                    continue
            metadata["index_count_raster_sha256"] = hashlib.sha256(
                (root / count_path).read_bytes()
            ).hexdigest()
        with rasterio.open(root / raster) as src:
            if src.crs is None or src.crs.is_geographic:
                skipped.append(str(path.relative_to(root)))
                continue
            geographic = _geographic_crs(body, src.crs)
            # Sample edges for conservative geographic envelopes. Polar
            # footprints use a full-longitude envelope to avoid seam misses.
            pts = []
            for i in range(33):
                t = i / 32
                pts.extend(
                    [
                        (src.width * t, 0),
                        (src.width * t, src.height),
                        (0, src.height * t),
                        (src.width, src.height * t),
                    ]
                )
            xy = [src.transform @ p for p in pts]
            lon, lat = transform(src.crs, geographic, [p[0] for p in xy], [p[1] for p in xy])
            lon = [(x + 180) % 360 - 180 for x in lon]
            center = src.transform @ (src.width / 2, src.height / 2)
            center_lon, center_lat = transform(src.crs, geographic, [center[0]], [center[1]])
            metadata = dict(metadata)
            metadata["index_raster_sha256"] = hashlib.sha256(
                (root / raster).read_bytes()
            ).hexdigest()
            edge_pixels = [(src.width * i / 16, 0) for i in range(17)]
            edge_pixels += [(src.width, src.height * i / 16) for i in range(1, 17)]
            edge_pixels += [(src.width * (1 - i / 16), src.height) for i in range(1, 17)]
            edge_pixels += [(0, src.height * (1 - i / 16)) for i in range(1, 17)]
            edge_xy = [src.transform @ point for point in edge_pixels]
            edge_lon, edge_lat = transform(
                src.crs, geographic, [p[0] for p in edge_xy], [p[1] for p in edge_xy]
            )
            metadata["index_footprint"] = [
                [longitude % 360, latitude]
                for longitude, latitude in zip(edge_lon, edge_lat, strict=True)
            ]
            metadata["index_center"] = {
                "latitude_deg": center_lat[0],
                "longitude_east_deg": center_lon[0] % 360,
            }
            midpoints = [
                src.transform @ point
                for point in (
                    (0, src.height / 2),
                    (src.width, src.height / 2),
                    (src.width / 2, 0),
                    (src.width / 2, src.height),
                )
            ]
            midpoint_lon, midpoint_lat = transform(
                src.crs, geographic, [p[0] for p in midpoints], [p[1] for p in midpoints]
            )
            radius = {"earth": 6371008.8, "mars": 3396000.0, "moon": 1737400.0}[body]
            metadata["index_ground_width_m"] = _surface_distance_m(
                midpoint_lon[0], midpoint_lat[0], midpoint_lon[1], midpoint_lat[1], radius
            )
            metadata["index_ground_height_m"] = _surface_distance_m(
                midpoint_lon[2], midpoint_lat[2], midpoint_lon[3], midpoint_lat[3], radius
            )
            metadata["index_ground_geometry_method"] = (
                "Spherical great-circle distances between inverse-projected edge midpoints"
            )
            polar = "polar" in str(metadata.get("dataset_id"))
            if polar:
                # A projected rectangle may enclose the pole even though no
                # sampled boundary point reaches it.
                pole_col, pole_row = ~src.transform @ (0, 0)
                if 0 <= pole_col <= src.width and 0 <= pole_row <= src.height:
                    lat.append(-90.0 if sum(lat) < 0 else 90.0)
            # For polar windows use a whole-body envelope: a sampled boundary
            # can miss a latitude extremum. Exact projected containment below
            # still rejects clicks outside the raster.
            if polar:
                bounds = [-180, 180, -90, 90]
            elif max(lon) - min(lon) > 180:
                bounds = [-180, 180, min(lat), max(lat)]
            else:
                bounds = [min(lon), max(lon), min(lat), max(lat)]
            rows.append(
                dict(
                    observation_id=str(metadata["observation_id"]),
                    body=body,
                    crs=src.crs.to_wkt(),
                    geographic_crs=geographic.to_wkt(),
                    affine=list(src.transform)[:6],
                    width=src.width,
                    height=src.height,
                    metadata=metadata,
                    bounds=bounds,
                )
            )
    builder_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    canonical = json.dumps(
        {"builder_sha256": builder_sha256, "contexts": rows},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    identity = hashlib.sha256(canonical.encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(temporary) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(SCHEMA)
            db.execute("INSERT INTO release VALUES (?, 4, ?)", (identity, builder_sha256))
            for i, row in enumerate(rows, 1):
                db.execute(
                    "INSERT INTO contexts VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        i,
                        row["observation_id"],
                        row["body"],
                        row["crs"],
                        row["geographic_crs"],
                        json.dumps(row["affine"]),
                        row["width"],
                        row["height"],
                        json.dumps(
                            {k: v for k, v in row["metadata"].items() if k != "measurements"}
                        ),
                    ),
                )
                metadata = row["metadata"]
                # Use explicit catalogue linkage only; observations without one
                # remain distinct rather than being merged by geographic proximity.
                place_id = f"{row['body']}:{metadata.get('place_id') or row['observation_id']}"
                place_name = str(metadata.get("name") or row["observation_id"])
                db.execute(
                    "INSERT OR IGNORE INTO places VALUES (?, ?, ?)",
                    (place_id, row["body"], place_name),
                )
                db.execute("INSERT INTO context_places VALUES (?, ?)", (i, place_id))
                db.execute(
                    "INSERT INTO context_quality VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        i,
                        metadata.get("valid_pixel_fraction"),
                        metadata.get("observed_cell_fraction"),
                        metadata.get("native_count_crop_fraction"),
                        metadata.get("missing_data_semantics"),
                        metadata.get("uncertainty_note"),
                    ),
                )
                for ordinal, measurement in enumerate(metadata.get("measurements", [])):
                    db.execute(
                        "INSERT INTO measurements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            i,
                            ordinal,
                            measurement["name"],
                            measurement.get("value"),
                            measurement["units"],
                            measurement["availability"],
                            measurement.get("spatial_scale_m"),
                            json.dumps(measurement),
                        ),
                    )
                for role, id_key, url_key in (
                    ("elevation", "source_product_id", "source_url"),
                    ("counts", "counts_product_id", "counts_source_url"),
                    ("counts", "count_product_id", "counts_source_url"),
                ):
                    if metadata.get(id_key):
                        db.execute(
                            "INSERT OR IGNORE INTO source_products VALUES (?, ?, ?, ?)",
                            (i, role, str(metadata[id_key]), metadata.get(url_key)),
                        )
                db.execute("INSERT INTO bounds VALUES (?,?)", (i, i))
                db.execute("INSERT INTO bounds_index VALUES (?,?,?,?,?)", (i, *row["bounds"]))
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("index integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("index foreign-key check failed")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"id": identity, "contexts": len(rows), "skipped": skipped}


def resolve(index: Path, body: str, latitude: float, longitude: float) -> list[dict[str, Any]]:
    """Return contexts whose projected raster rectangle contains the click."""
    if (
        body not in {"moon", "mars"}
        or not all(math.isfinite(v) for v in (latitude, longitude))
        or not -90 <= latitude <= 90
    ):
        raise ValueError("invalid body or coordinate")
    longitude = (longitude + 180) % 360 - 180
    with sqlite3.connect(f"file:{index.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        candidates = db.execute(
            """SELECT c.* FROM bounds_index r JOIN bounds b ON b.id=r.id
          JOIN contexts c ON c.id=b.context_id WHERE c.body=? AND r.min_lon<=? AND r.max_lon>=?
          AND r.min_lat<=? AND r.max_lat>=?""",
            (body, longitude, longitude, latitude, latitude),
        ).fetchall()
        observations = {
            row["id"]: [
                json.loads(item[0])
                for item in db.execute(
                    "SELECT payload FROM measurements WHERE context_id=? ORDER BY ordinal",
                    (row["id"],),
                )
            ]
            for row in candidates
        }
    matches = []
    for row in candidates:
        xs, ys = transform(
            CRS.from_wkt(row["geographic_crs"]), CRS.from_wkt(row["crs"]), [longitude], [latitude]
        )
        col, line = ~Affine(*json.loads(row["affine"])) @ (xs[0], ys[0])
        if -1e-8 <= col <= row["width"] + 1e-8 and -1e-8 <= line <= row["height"] + 1e-8:
            metadata = json.loads(row["metadata"])
            metadata["measurements"] = observations[row["id"]]
            matches.append(metadata)
    # Rank eligible contexts first, but never select a context outside its
    # footprint. The source ordering and distance only break containment ties.
    from twinworld.discovery import _support_ok
    from twinworld.scorecards import measurements_by_name

    source_order = {
        "lro-lola-gdr-polar-ldem-120m": 0,
        "lro-lola-gdr-ldem-64": 1,
        "mola-meg128": 2,
    }
    radius = 3396000.0 if body == "mars" else 1737400.0

    def precedence(m: dict[str, Any]) -> tuple[bool, int, float, str]:
        center = m["index_center"]
        eligible = _support_ok(m) and bool(measurements_by_name(m.get("measurements", [])))
        distance = _surface_distance_m(
            longitude, latitude, center["longitude_east_deg"], center["latitude_deg"], radius
        )
        return (
            not eligible,
            source_order.get(str(m.get("dataset_id")), 99),
            distance,
            str(m["observation_id"]),
        )

    return sorted(matches, key=precedence)
