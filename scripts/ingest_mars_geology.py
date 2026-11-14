"""Look up mapped geologic unit codes for indexed Mars sites in USGS SIM 1083.

This vector map is coarse regional context, not a measurement of soil,
mineralogy, or engineering properties. It is kept outside terrain scoring.
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import requests
import shapefile

from twinworld.geospatial import mars_projection_longitude
from twinworld.records import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/pilot-100.jsonl"
MOLA_SIDECARS = ROOT / "data/terrain"
OUTPUT_DIR = ROOT / "data/geology"
DATASET_ID = "usgs-sim-1083-mars-global-geology"
PRODUCT_ID = "USGS SIM 1083 / I1083_Mariner9_25M_Mars2000"
DOI_URL = "https://doi.org/10.5066/P9UGAC18"
RECORD_URL = "https://www.usgs.gov/data/geologic-map-mars"
ARCHIVE_URL = (
    "https://www.sciencebase.gov/catalog/file/get/65678461d34e17319ded0ac1"
    "?f=__disk__ff%2Fdc%2Fa6%2Fffdca6605404f9a397ba005fd8d20632b6b7445e"
)
ARCHIVE_CACHE = ROOT / "data/raw/mars_geology/usgs-sim1083-gis.zip"
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
SHAPEFILE_BASE = "GIS/Shapefiles/I1083_GeoUnits"
BOUNDARY_EPSILON_DEG = 1e-9


def normalize_east_longitude(longitude_deg: float) -> float:
    """Normalize east-positive longitudes into the shapefile's [-180, 180) domain."""
    if not -360.0 <= longitude_deg <= 360.0:
        raise ValueError("Mars longitude must be in [-360, 360]")
    return mars_projection_longitude(longitude_deg)


def _download_archive(cache_path: Path = ARCHIVE_CACHE) -> None:
    if cache_path.is_file():
        if cache_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Cached USGS geology archive exceeds the configured size limit")
        with zipfile.ZipFile(cache_path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Cached USGS geology ZIP failed its CRC check")
        return

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".part")
    total = 0
    try:
        with requests.get(ARCHIVE_URL, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            length = int(response.headers.get("Content-Length", "0"))
            if length > MAX_ARCHIVE_BYTES:
                raise RuntimeError("USGS geology archive exceeds the configured size limit")
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise RuntimeError("USGS geology archive exceeds the configured size limit")
                    output.write(chunk)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Downloaded USGS geology ZIP failed its CRC check")
            required = {
                f"{SHAPEFILE_BASE}.shp",
                f"{SHAPEFILE_BASE}.shx",
                f"{SHAPEFILE_BASE}.dbf",
                f"{SHAPEFILE_BASE}.prj",
            }
            if not required.issubset(archive.namelist()):
                raise RuntimeError("USGS geology archive is missing required GeoUnits files")
        temporary.replace(cache_path)
    finally:
        temporary.unlink(missing_ok=True)


def load_geounits(cache_path: Path = ARCHIVE_CACHE) -> shapefile.Reader:
    """Open the GeoUnits polygon layer from the cached archive."""
    _download_archive(cache_path)
    with zipfile.ZipFile(cache_path) as archive:
        members = [archive.read(f"{SHAPEFILE_BASE}.{ext}") for ext in ("shp", "shx", "dbf")]
    reader = shapefile.Reader(
        shp=io.BytesIO(members[0]),
        shx=io.BytesIO(members[1]),
        dbf=io.BytesIO(members[2]),
        encoding="utf-8",
    )
    if "Unit" not in [field[0] for field in reader.fields[1:]]:
        raise RuntimeError("USGS GeoUnits layer has no Unit code attribute")
    return reader


def _ring_relation(point: tuple[float, float], ring: list[list[float]]) -> str:
    """Return inside, outside, or boundary for one planar polygon ring."""
    x, y = point
    inside = False
    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        dx, dy = x2 - x1, y2 - y1
        cross = (x - x1) * dy - (y - y1) * dx
        if (
            abs(cross) <= BOUNDARY_EPSILON_DEG * max(1.0, abs(dx) + abs(dy))
            and min(x1, x2) - BOUNDARY_EPSILON_DEG <= x <= max(x1, x2) + BOUNDARY_EPSILON_DEG
            and min(y1, y2) - BOUNDARY_EPSILON_DEG <= y <= max(y1, y2) + BOUNDARY_EPSILON_DEG
        ):
            return "boundary"
        if (y1 > y) != (y2 > y) and x < (dx * (y - y1) / dy + x1):
            inside = not inside
    return "inside" if inside else "outside"


def mapped_unit_at(
    reader: shapefile.Reader, longitude_east_deg: float, latitude_deg: float
) -> tuple[str, str | None]:
    """Return a unique mapped unit code, or an explicit unmapped/boundary state."""
    if not -90 <= latitude_deg <= 90:
        raise ValueError("Mars latitude must be in [-90, 90]")
    point = (normalize_east_longitude(longitude_east_deg), latitude_deg)
    unit_field = [field[0] for field in reader.fields[1:]].index("Unit")
    hits: list[str] = []
    boundary = False
    for shape_record in reader.iterShapeRecords():
        shape = shape_record.shape
        if not (
            shape.bbox[0] - BOUNDARY_EPSILON_DEG <= point[0] <= shape.bbox[2] + BOUNDARY_EPSILON_DEG
            and shape.bbox[1] - BOUNDARY_EPSILON_DEG
            <= point[1]
            <= shape.bbox[3] + BOUNDARY_EPSILON_DEG
        ):
            continue
        starts = list(shape.parts) + [len(shape.points)]
        inside = False
        on_boundary = False
        for start, stop in zip(starts, starts[1:], strict=False):
            relation = _ring_relation(point, shape.points[start:stop])
            if relation == "boundary":
                on_boundary = True
                break
            if relation == "inside":
                inside = not inside
        if on_boundary:
            boundary = True
        elif inside:
            hits.append(str(shape_record.record[unit_field]).strip())
    if boundary or len(hits) > 1:
        return "boundary_ambiguous", None
    if not hits:
        return "unmapped", None
    return "mapped", hits[0]


def _mars_mola_sites() -> list[tuple[str, float, float]]:
    records = {record.image_id: record for record in read_jsonl(MANIFEST) if record.body == "mars"}
    sites = []
    for sidecar in sorted(MOLA_SIDECARS.glob("mola-meg128-*.tif.json")):
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        record = records.get(str(metadata.get("observation_id", "")))
        if record is not None:
            sites.append((record.image_id, record.longitude, record.latitude))
    return sites


def ingest_sites(*, cache_path: Path = ARCHIVE_CACHE) -> list[dict[str, object]]:
    """Write categorical map provenance sidecars for all indexed MOLA sites."""
    reader = load_geounits(cache_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for observation_id, longitude, latitude in _mars_mola_sites():
        status, unit_code = mapped_unit_at(reader, longitude, latitude)
        metadata: dict[str, object] = {
            "observation_id": observation_id,
            "dataset_id": DATASET_ID,
            "provider": "U.S. Geological Survey Astrogeology Science Center",
            "source_product_id": PRODUCT_ID,
            "source_url": ARCHIVE_URL,
            "dataset_reference_url": DOI_URL,
            "record_url": RECORD_URL,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "map_layer": "I1083_GeoUnits",
            "map_unit_code": unit_code,
            "classification_status": status,
            "longitude_east_deg": longitude,
            "longitude_layer_deg": normalize_east_longitude(longitude),
            "latitude_deg": latitude,
            "coordinate_reference_system": "Mars_2000_Sphere geographic; 3,396,190 m radius",
            "nominal_cartographic_scale": (
                "1:25,000,000 from 65°S to 65°N; approximately 1:5,000,000 poleward of 60°"
            ),
            "source_description": (
                "Global polygon unit classification from the Scott and Carr USGS geologic map, "
                "digitized and renovated against a semi-controlled THEMIS daytime IR 100 m/pixel "
                "basemap. Map-unit polygons generalize regional interpretations; this code is "
                "not a measurement of local soil, mineralogy, or engineering properties."
            ),
            "scorecard_role": "geology_context_only; excluded from terrain ranking",
        }
        output = OUTPUT_DIR / f"usgs-sim1083-{observation_id}.json"
        output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        results.append(metadata)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ARCHIVE_CACHE)
    args = parser.parse_args()
    print(json.dumps(ingest_sites(cache_path=args.cache), indent=2))


if __name__ == "__main__":
    main()
