"""Small coordinate helpers shared by the pilot and validation tests."""

from __future__ import annotations

import math

import shapefile  # type: ignore[import-untyped]

# JPL planetary parameters list the Mars mean radius as 3,396.19 km.
# https://ssd.jpl.nasa.gov/planets/phys_par.html
MARS_MEAN_RADIUS_M = 3_396_190.0


def mars_surface_distance_m(
    longitude_a_deg: float,
    latitude_a_deg: float,
    longitude_b_deg: float,
    latitude_b_deg: float,
) -> float:
    """Return Mars great-circle distance in metres for east-positive lon/lat points.

    Uses the haversine central angle, ``2 asin(sqrt(h))``, with
    ``h = sin²(Δlat/2) + cos(lat_a) cos(lat_b) sin²(Δlon/2)`` and the IAU mean
    Mars radius. This spherical approximation is for geographic spacing, not
    precise geodetic surveying.
    """
    coordinates = (longitude_a_deg, latitude_a_deg, longitude_b_deg, latitude_b_deg)
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Mars coordinates must be finite")
    if not -90 <= latitude_a_deg <= 90 or not -90 <= latitude_b_deg <= 90:
        raise ValueError("Mars latitude must be between -90 and 90 degrees")

    lon_a, lat_a, lon_b, lat_b = map(
        math.radians, (longitude_a_deg, latitude_a_deg, longitude_b_deg, latitude_b_deg)
    )
    delta_lon = (lon_b - lon_a + math.pi) % (2 * math.pi) - math.pi
    delta_lat = lat_b - lat_a
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(
        delta_lon / 2
    ) ** 2
    central_angle = 2 * math.asin(math.sqrt(min(1.0, haversine)))
    return MARS_MEAN_RADIUS_M * central_angle


def mars_projection_longitude(longitude: float) -> float:
    """Convert east longitude to the signed longitude used by STAC rasters."""
    normalized = longitude % 360.0
    return normalized - 360.0 if normalized > 180.0 else normalized


def ring_contains(ring: list[tuple[float, float]], x: float, y: float) -> bool:
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
        if ring_contains(geometry.points[start:end], longitude, latitude):
            contains = not contains
    return contains
