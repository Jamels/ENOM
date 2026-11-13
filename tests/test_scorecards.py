import math

import pytest
from fastapi.testclient import TestClient

from twinworld import api as api_module
from twinworld.api import app
from twinworld.scorecards import compare_candidate, mission_suitability, validate_weights


def measurement(name, value, scale=926.1153343394911, units="degree"):
    return {"name": name, "value": value, "units": units, "spatial_scale_m": scale}


def test_weights_reject_negative_nonfinite_unknown_and_zero_sum():
    for weights in (
        {"mean_slope": -0.1},
        {"mean_slope": math.inf},
        {"unregistered": 1.0},
        {"mean_slope": 0.0, "slope_p90": 0.0},
    ):
        with pytest.raises(ValueError):
            validate_weights(weights)


def test_missing_and_scale_mismatched_features_are_not_scored_or_called_dissimilar():
    result = compare_candidate(
        [measurement("mean_slope", 5.0)],
        [measurement("mean_slope", 5.0, scale=1200)],
        {"mean_slope": 1.0, "slope_p90": 1.0},
    )
    assert result["similarity_score"] is None
    assert result["data_completeness"] == 0
    assert all(item["score"] is None for item in result["variables"])


def test_score_is_bounded_and_missing_data_weights_renormalize():
    same = compare_candidate(
        [measurement("mean_slope", 4.0), measurement("slope_p90", 10.0)],
        [measurement("mean_slope", 4.0)],
        {"mean_slope": 0.4, "slope_p90": 0.6},
    )
    assert same["similarity_score"] == pytest.approx(1.0)
    assert same["data_completeness"] == 0.5
    one_tolerance = compare_candidate(
        [measurement("mean_slope", 0.0)],
        [measurement("mean_slope", 5.0)],
        {"mean_slope": 1.0},
    )
    assert one_tolerance["similarity_score"] == pytest.approx(math.exp(-1))


def test_mission_screening_has_explicit_inclusive_boundaries_and_missing_state():
    passed = mission_suitability(
        [
            measurement("slope_p90", 10.0),
            measurement("median_local_relief_3x3", 60.0, 1389.17, "m"),
        ],
        "landing",
    )
    assert passed["status"] == "provisional_pass"
    assert mission_suitability([], "landing")["status"] == "insufficient_data"
    failed = mission_suitability(
        [
            measurement("slope_p90", 10.01),
            measurement("median_local_relief_3x3", 60.0, 1389.17, "m"),
        ],
        "landing",
    )
    assert failed["status"] == "provisional_concern"
    assert "not validated" in passed["qualification"]


def test_real_lola_scorecard_api_has_ranked_earth_candidates_and_provenance(monkeypatch):
    def no_visual_index():
        raise AssertionError("scientific scorecards must not require DINOv2 assets")

    monkeypatch.setattr(api_module, "_load", no_visual_index)
    client = TestClient(app)
    sites = client.get("/api/scorecards/sites")
    assert sites.status_code == 200
    assert sites.json()["sites"][0]["source_product_id"] == "LDEM_64"
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "moon_mare_tranquillitatis_01",
            "mission_objective": "landing",
            "weights": {
                "mean_slope": 0.35,
                "slope_p90": 0.3,
                "median_local_relief_3x3": 0.2,
                "median_roughness_3x3": 0.15,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["site"]["source"]["product_id"] == "LDEM_64"
    assert payload["candidate_coverage"]["indexed_earth_dem_contexts"] >= 1
    assert payload["candidates"][0]["similarity_score"] is not None
    assert payload["candidates"][0]["source"]["product_id"].startswith("Copernicus_DSM")
    assert payload["candidates"][0]["variables"]


def test_scorecard_api_rejects_zero_weights_and_unknown_site():
    client = TestClient(app)
    invalid = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "moon_mare_tranquillitatis_01",
            "mission_objective": "landing",
            "weights": {"mean_slope": 0.0},
        },
    )
    assert invalid.status_code == 422
    missing = client.post(
        "/api/scorecards/rank",
        json={"site_id": "unknown", "mission_objective": "landing", "weights": {"mean_slope": 1}},
    )
    assert missing.status_code == 404
