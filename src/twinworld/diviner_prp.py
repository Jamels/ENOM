"""Bounded sampler for Diviner's south-polar Polar Resource Product (PRP)."""

from __future__ import annotations

import math
from typing import Any

from twinworld.pds import read_byte_range as _read_pds_byte_range

DATASET_ID = "lro-diviner-prp-south-polar"
PRODUCT_ID = "DLRE_PRP_SOUTH.TAB"
TABLE_URL = (
    "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-"
    "lro_diviner_derived1/data_derived_prp/dlre_prp_south.tab"
)
LABEL_URL = TABLE_URL.removesuffix(".tab") + ".lbl"
ROW_BYTES = 210
HEADER_ROWS = 1
GRID_SIDE = 1200
TRIANGLES_PER_CELL = 2
POLAR_RADIUS_KM = 1737.4
MESH_ORIGIN_KM = 299.75
MESH_STEP_KM = 0.5
SEARCH_CELLS = 2
MAX_SAMPLE_DISTANCE_KM = 5.0


def _candidate_grid(latitude_deg: float, longitude_east_deg: float) -> tuple[int, int]:
    if not math.isfinite(latitude_deg) or not math.isfinite(longitude_east_deg):
        raise ValueError("Diviner PRP coordinates must be finite")
    if not (-90.0 <= latitude_deg <= -80.0):
        raise ValueError("Diviner south-polar PRP covers latitudes -90 to -80 degrees")
    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_east_deg % 360.0)
    x = POLAR_RADIUS_KM * math.cos(latitude) * math.cos(longitude)
    y = POLAR_RADIUS_KM * math.cos(latitude) * math.sin(longitude)
    row = round((MESH_ORIGIN_KM - x) / MESH_STEP_KM)
    column = round((y + MESH_ORIGIN_KM) / MESH_STEP_KM)
    if not (0 <= row < GRID_SIDE and 0 <= column < GRID_SIDE):
        raise ValueError("Coordinate falls outside Diviner south-polar mesh")
    return row, column


def _parse_record(raw: bytes, record_index: int, candidate_lat: float, candidate_lon: float) -> dict[str, Any]:
    if len(raw) != ROW_BYTES:
        raise IOError("Diviner PRP record did not match its 210-byte PDS row")
    fields = raw.decode("ascii").strip().split(",")
    if len(fields) != 15:
        raise ValueError("Diviner PRP row did not contain the 15 PDS fields")
    values = [float(field.strip()) for field in fields]
    longitude, latitude = values[9], values[10]
    distance = _distance_km(candidate_lat, candidate_lon, latitude, longitude)
    ice_depth = None if values[14] == -999.0 else values[14]
    return {
        "record_index": record_index,
        "latitude_deg": latitude,
        "longitude_east_deg": longitude % 360.0,
        "distance_from_candidate_km": distance,
        "measurements": {
            "annual_average_surface_temperature_2cm": values[12],
            "annual_maximum_surface_temperature": values[13],
            "modeled_ice_stability_depth": ice_depth,
        },
    }


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * POLAR_RADIUS_KM * math.asin(math.sqrt(a))


def read_nearest_triangle(latitude_deg: float, longitude_east_deg: float) -> dict[str, Any]:
    """Read nearby mesh rows and return the closest triangle centroid.

    The 1200×1200 regular cell layout and row ordering were checked against
    the product's triangle vertex coordinates. Only five short row ranges are
    requested; the 604 MB global table is never downloaded.
    """
    row, column = _candidate_grid(latitude_deg, longitude_east_deg)
    candidates: list[dict[str, Any]] = []
    for mesh_row in range(max(0, row - SEARCH_CELLS), min(GRID_SIDE, row + SEARCH_CELLS + 1)):
        first_column = max(0, column - SEARCH_CELLS)
        last_column = min(GRID_SIDE - 1, column + SEARCH_CELLS)
        first_triangle = (mesh_row * GRID_SIDE + first_column) * TRIANGLES_PER_CELL
        last_triangle = (mesh_row * GRID_SIDE + last_column + 1) * TRIANGLES_PER_CELL - 1
        first_record = HEADER_ROWS + first_triangle
        last_record = HEADER_ROWS + last_triangle
        start = first_record * ROW_BYTES
        end = (last_record + 1) * ROW_BYTES - 1
        raw = _read_pds_byte_range(
            TABLE_URL,
            start,
            end,
            timeout=30,
            product_name=f"{PRODUCT_ID} local south-polar rows",
        )
        expected = (last_record - first_record + 1) * ROW_BYTES
        if len(raw) != expected:
            raise IOError("Diviner PRP byte range did not match the requested local rows")
        for offset in range(0, len(raw), ROW_BYTES):
            record_index = first_triangle + offset // ROW_BYTES
            candidates.append(_parse_record(
                raw[offset : offset + ROW_BYTES], record_index, latitude_deg, longitude_east_deg
            ))
    nearest = min(candidates, key=lambda item: item["distance_from_candidate_km"])
    if nearest["distance_from_candidate_km"] > MAX_SAMPLE_DISTANCE_KM:
        raise ValueError("Nearest Diviner PRP triangle is too far from the candidate place")
    return {
        **nearest,
        "candidate_grid_cell": {"row": row, "column": column},
        "search_triangle_count": len(candidates),
        "mesh_resolution_note": "about 0.5 km triangle spacing; sample is the nearest triangle centroid, not a place-wide average",
    }
