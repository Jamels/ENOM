import pytest

from twinworld.spatial import ensure_no_overlaps, overlap_pairs


def _patch(image_id: str, x: float) -> dict[str, object]:
    return {
        "image_id": image_id,
        "body": "earth",
        "crs": "EPSG:32633",
        "center_x": x,
        "center_y": 1_000_000.0,
        "longitude": 15.0,
        "latitude": 0.0,
        "extent_m": 2_000.0,
    }


def test_overlap_detector_rejects_intersecting_ground_footprints():
    rows = [_patch("a", 500_000), _patch("b", 501_500)]
    assert overlap_pairs(rows) == [("a", "b")]
    with pytest.raises(ValueError, match="overlapping patch pairs"):
        ensure_no_overlaps(rows)


def test_overlap_detector_allows_touching_nonoverlapping_footprints():
    assert overlap_pairs([_patch("a", 500_000), _patch("b", 502_000)]) == []
