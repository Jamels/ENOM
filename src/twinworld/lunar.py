"""Lunar coordinate conventions and LOLA ingestion contracts.

This module describes and validates source geometry; it does not fetch or
reprocess LOLA rasters. LOLA's south-polar products use product-specific
MOON_ME / ephemeris frames, so callers must preserve the delivered CRS rather
than relabeling a raster as this generic spherical CRS.
"""

from __future__ import annotations

from dataclasses import dataclass

from rasterio.crs import CRS

MOON_REFERENCE_RADIUS_M = 1_737_400.0
LOLA_GDR_URL = "https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/Lunar%20Reconnaissance%20Orbiter%20%28LRO%29/LOLA/GDR/Intro.htm"
LOLA_GDR_COUNTS_URL = "https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/Lunar%20Reconnaissance%20Orbiter%20%28LRO%29/LOLA/GDR/GDRDEC.htm"


@dataclass(frozen=True, slots=True)
class LolaProduct:
    dataset_id: str
    product_type: str
    value_units: str
    availability_semantics: str
    source_url: str


LOLA_PRODUCTS = (
    LolaProduct(
        "lola-gdr-dem",
        "GDRDEM",
        "m",
        "elevation samples; inspect PDS labels for scale/offset and fill values",
        LOLA_GDR_URL,
    ),
    LolaProduct(
        "lola-gdr-counts",
        "GDRDEC",
        "returns/pixel",
        "count cells distinguish sampled support from interpolated DEM values",
        LOLA_GDR_COUNTS_URL,
    ),
)


def normalize_east_longitude(longitude_deg: float) -> float:
    """Normalize east-positive longitude into [0, 360), including wraparound."""
    if not -360.0 <= longitude_deg <= 720.0:
        raise ValueError("longitude is outside the supported normalization range")
    normalized = longitude_deg % 360.0
    return 0.0 if normalized == 360.0 else normalized


def validate_lunar_latitude(latitude_deg: float) -> None:
    """Reject latitude outside the Moon's planetocentric coordinate domain."""
    if not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("lunar latitude must be within [-90, 90] degrees")


def polar_stereographic_crs(hemisphere: str, *, radius_m: float = MOON_REFERENCE_RADIUS_M) -> CRS:
    """Return a spherical lunar polar stereographic CRS in metres.

    This is useful for locally generated rasters and coordinate calculations.
    It must not replace the native CRS of LOLA GDR or PGDA products, whose
    orientation/reference frame is defined by their product labels.
    """
    if hemisphere not in {"north", "south"}:
        raise ValueError("hemisphere must be 'north' or 'south'")
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    latitude = 90 if hemisphere == "north" else -90
    return CRS.from_proj4(
        f"+proj=stere +lat_0={latitude} +lon_0=0 +k=1 +R={radius_m:g} +units=m +no_defs"
    )
