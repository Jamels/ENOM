import json
from pathlib import Path

import pytest
from rasterio.warp import transform

from twinworld.lunar import (
    LOLA_PRODUCTS,
    normalize_east_longitude,
    polar_stereographic_crs,
    validate_lunar_latitude,
)
from twinworld.records import read_jsonl, validate_records

ROOT = Path(__file__).resolve().parents[1]


def test_lunar_longitude_and_latitude_conventions() -> None:
    assert normalize_east_longitude(360) == 0
    assert normalize_east_longitude(-1) == 359
    with pytest.raises(ValueError):
        normalize_east_longitude(721)
    validate_lunar_latitude(-90)
    with pytest.raises(ValueError):
        validate_lunar_latitude(90.01)


@pytest.mark.parametrize(("hemisphere", "latitude"), [("north", 90), ("south", -90)])
def test_lunar_polar_crs_round_trip(hemisphere: str, latitude: int) -> None:
    crs = polar_stereographic_crs(hemisphere)
    xs, ys = transform(crs.geodetic_crs, crs, [0.0], [float(latitude)])
    assert abs(xs[0]) < 1e-5
    assert abs(ys[0]) < 1e-5
    assert "1737400" in crs.to_proj4()


@pytest.mark.parametrize("radius_m", [float("nan"), float("inf")])
def test_lunar_polar_crs_rejects_non_finite_radius(radius_m: float) -> None:
    with pytest.raises(ValueError, match="radius_m must be finite and positive"):
        polar_stereographic_crs("south", radius_m=radius_m)


def test_candidate_catalogue_has_provenance_and_normalized_coordinates() -> None:
    data = json.loads((ROOT / "data/manifests/candidate-locations.json").read_text())
    entries = data["entries"]
    assert len(entries) >= 12
    assert len({item["id"] for item in entries}) == len(entries)
    for item in entries:
        assert item["source_url"].startswith("https://")
        assert item["dataset_refs"]
        assert 0 <= item["longitude_east_deg"] < 360
        assert -90 <= item["latitude_deg"] <= 90
        assert item["status"] != "validated_analogue"


def test_candidate_review_pairs_are_real_pilot_ids_and_unadjudicated() -> None:
    records = read_jsonl(ROOT / "data/manifests/pilot-100.jsonl")
    ids = {record.image_id for record in records}
    review = json.loads((ROOT / "configs/retrieval-review-set-v1.json").read_text())
    assert review["relevance_labels_are_adjudicated"] is False
    assert {item["relationship_hypothesis"] for item in review["pairs"]} == {
        "positive_candidate",
        "negative_candidate",
    }
    for pair in review["pairs"]:
        assert pair["query_id"] in ids
        assert pair["candidate_id"] in ids
        assert pair["review_status"] == "pending"


def test_pilot_manifest_coordinate_conventions_validate_without_raster_assets() -> None:
    records = read_jsonl(ROOT / "data/manifests/pilot-100.jsonl")
    assert validate_records(records, ROOT, check_file=False) == []
    mars_rows = [record for record in records if record.body == "mars"]
    assert any(record.longitude < 0 for record in mars_rows)


def test_lola_products_distinguish_elevation_from_support_counts() -> None:
    assert {product.product_type for product in LOLA_PRODUCTS} == {"GDRDEM", "GDRDEC"}
    assert all("lola" in product.dataset_id for product in LOLA_PRODUCTS)
