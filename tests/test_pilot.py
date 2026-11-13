import shapefile

from twinworld.geospatial import shape_contains


def test_mgd3_polygon_contains_signed_and_0_to_360_mars_longitudes():
    geometry = shapefile.Shape(
        shapeType=shapefile.POLYGON,
        points=[(-51, -10), (-49, -10), (-49, -8), (-51, -8), (-51, -10)],
        parts=[0],
    )

    assert shape_contains(geometry, -50, -9)
    assert shape_contains(geometry, 310, -9)
    assert not shape_contains(geometry, 308, -9)
