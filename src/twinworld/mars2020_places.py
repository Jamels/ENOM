"""Reader for Perseverance's PDS PLACES best-tactical localization table."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

MARS_RADIUS_KM = 3396.19
DATASET_ID = "mars2020-rover-places-best-tactical"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * MARS_RADIUS_KM * math.asin(math.sqrt(a))


def parse_best_tactical_csv(
    text: str,
    center_latitude_deg: float,
    center_longitude_east_deg: float,
    radius_km: float = 20.0,
) -> list[dict[str, Any]]:
    """Keep localized ROVER drive rows inside a candidate region.

    SITE rows and invalid sol/drive values are excluded. Rows remain isolated
    position fixes; this function does not interpolate or invent wheel tracks.
    """
    if not math.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("Candidate radius must be a positive finite distance")
    reader = csv.DictReader(io.StringIO(text))
    required = {
        "frame", "site", "drive", "pose", "planetocentric_latitude",
        "longitude", "elevation", "sol",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("PLACES best-tactical table is missing required columns")
    result = []
    for row in reader:
        if row["frame"] != "ROVER":
            continue
        sol, drive = int(row["sol"]), int(row["drive"])
        if sol < 0 or drive <= 0:
            continue
        latitude = float(row["planetocentric_latitude"])
        longitude = float(row["longitude"]) % 360.0
        distance = distance_km(
            center_latitude_deg, center_longitude_east_deg, latitude, longitude
        )
        if distance > radius_km:
            continue
        result.append({
            "site": int(row["site"]),
            "drive": drive,
            "pose": int(row["pose"]),
            "sol": sol,
            "latitude_deg": latitude,
            "longitude_east_deg": longitude,
            "elevation_m": float(row["elevation"]),
            "distance_from_candidate_km": distance,
        })
    result.sort(key=lambda item: (item["sol"], item["site"], item["drive"], item["pose"]))
    return result
