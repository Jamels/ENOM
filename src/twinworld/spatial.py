"""Spatial independence checks for physical-area image patches."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from rasterio.crs import CRS


def _surface_distance_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Approximate short surface distance using a local equirectangular metric."""
    radius = 6_371_000 if a["body"] == "earth" else 3_396_190
    lon_a, lat_a = math.radians(float(a["longitude"])), math.radians(float(a["latitude"]))
    lon_b, lat_b = math.radians(float(b["longitude"])), math.radians(float(b["latitude"]))
    delta_lon = (lon_b - lon_a + math.pi) % (2 * math.pi) - math.pi
    x = delta_lon * math.cos((lat_a + lat_b) / 2)
    y = lat_b - lat_a
    return radius * math.hypot(x, y)


def overlap_pairs(rows: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return pairs whose ground footprints overlap or may overlap.

    Equal projected CRSs permit an exact axis-aligned square check. For unlike
    CRSs, a circumscribed-circle check is conservative so uncertain cases fail
    closed rather than leaking spatially adjacent chips into different groups.
    """
    overlapping: list[tuple[str, str]] = []
    for index, first in enumerate(rows):
        for second in rows[index + 1 :]:
            if first["body"] != second["body"]:
                continue
            half_first = float(first["extent_m"]) / 2
            half_second = float(second["extent_m"]) / 2
            if first["crs"] == second["crs"]:
                crs = CRS.from_user_input(first["crs"])
                _, units_to_m = crs.linear_units_factor
                half_first /= units_to_m
                half_second /= units_to_m
                overlaps = (
                    abs(float(first["center_x"]) - float(second["center_x"]))
                    < half_first + half_second
                    and abs(float(first["center_y"]) - float(second["center_y"]))
                    < half_first + half_second
                )
            else:
                # Without a shared map plane, reject possible overlap conservatively.
                conservative_radius = math.hypot(half_first + half_second, half_first + half_second)
                overlaps = _surface_distance_m(first, second) < conservative_radius
            if overlaps:
                overlapping.append((str(first["image_id"]), str(second["image_id"])))
    return overlapping


def ensure_no_overlaps(rows: Sequence[dict[str, Any]]) -> None:
    """Raise when any pair of records may share ground footprint area."""
    pairs = overlap_pairs(rows)
    if pairs:
        sample = ", ".join(f"{first} / {second}" for first, second in pairs[:8])
        raise ValueError(f"detected {len(pairs)} overlapping patch pairs: {sample}")
