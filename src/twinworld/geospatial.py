"""Small coordinate helpers shared by the pilot and validation tests."""

from __future__ import annotations

import shapefile  # type: ignore[import-untyped]


def mars_projection_longitude(longitude: float) -> float:
    """Convert east longitude to the signed longitude used by STAC rasters."""
    normalized = longitude % 360.0
    return normalized - 360.0 if normalized > 180.0 else normalized


def _ring_contains(ring: list[tuple[float, float]], x: float, y: float) -> bool:
    """Apply the ray-crossing point-in-ring test to one polygon ring."""
    inside = False
    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def shape_contains(geometry: shapefile.Shape, longitude: float, latitude: float) -> bool:
    """Test a Mars coordinate against MGD3 polygons in signed or east-positive form."""
    if geometry.bbox[0] < 0.0 and geometry.bbox[2] <= 180.0:
        longitude = mars_projection_longitude(longitude)
    else:
        longitude %= 360.0
    if not (
        geometry.bbox[0] <= longitude <= geometry.bbox[2]
        and geometry.bbox[1] <= latitude <= geometry.bbox[3]
    ):
        return False
    starts = list(geometry.parts) + [len(geometry.points)]
    contains = False
    for start, end in zip(starts[:-1], starts[1:], strict=True):
        if _ring_contains(geometry.points[start:end], longitude, latitude):
            contains = not contains
    return contains
