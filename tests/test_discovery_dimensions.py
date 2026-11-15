from pathlib import Path

import pytest

from twinworld.analogue import DIMENSIONS
from twinworld.discovery import _land_cover_status, _summarize_near_equivalents, rank
from twinworld.feature_index import build_index
from twinworld.scorecards import MISSION_PRESETS

ROOT = Path(__file__).resolve().parents[1]


def test_near_equivalent_id_list_is_bounded_without_losing_count():
    candidates = [{"context": {"observation_id": f"earth-{i}"}} for i in range(101)]
    summary = _summarize_near_equivalents(candidates)
    assert summary["near_equivalent_count"] == 101
    assert len(summary["near_equivalent_context_ids"]) == 100
    assert summary["near_equivalent_ids_truncated"] is True
    assert _summarize_near_equivalents(candidates[:100])["near_equivalent_ids_truncated"] is False


def test_independent_evidence_is_prioritized_and_zero_weights_do_not_contribute(tmp_path):
    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    weights = dict.fromkeys(DIMENSIONS, 0.0)
    weights["terrain"] = 1.0
    weights["geology_materials"] = 1.0
    result = rank(
        index,
        release,
        "moon_candidate_moon_mare_tranquillitatis_pit",
        MISSION_PRESETS["landing"]["weights"],
        dimension_weights=weights,
        result_limit=10,
    )
    assert result["results"][0]["context"]["place_id"] == "earth-mojave-lava-tube"
    assert result["results"][0]["independent_evidence_group_count"] == 2
    weights["geology_materials"] = 0.0
    terrain_only = rank(
        index,
        release,
        "moon_candidate_moon_mare_tranquillitatis_pit",
        MISSION_PRESETS["landing"]["weights"],
        dimension_weights=weights,
        result_limit=10,
    )
    assert all(row["independent_evidence_group_count"] == 1 for row in terrain_only["results"])


def test_ranking_returns_eight_explicit_dimension_rows_and_missing_ids(tmp_path):
    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    dimension_weights = {key: 1.0 for key in DIMENSIONS}

    result = rank(
        index,
        release,
        "lola_polar_moon_shackleton_rim",
        MISSION_PRESETS["landing"]["weights"],
        dimension_weights=dimension_weights,
    )

    assert result["dimension_weights"] == dimension_weights
    assert len(result["results"][0]["dimension_scores"]) == 8
    assert {row["dimension_id"] for row in result["results"][0]["dimension_scores"]} == set(
        DIMENSIONS
    )
    assert set(result["results"][0]["missing_dimensions"]) <= set(DIMENSIONS)
    assert result["results"][0]["dimension_scores"]


def test_land_cover_minimum_and_maximum_bounds_are_inclusive_and_diagnosed():
    row = {
        "land_cover": {
            "status": "available",
            "valid_fraction": 1.0,
            "group_fractions": {"bare_sparse": 0.25, "forest": 0.75},
        }
    }
    assert _land_cover_status(row, {"bare_sparse": 0.25}, {"forest": 0.75}) == "pass"
    assert _land_cover_status(row, {"bare_sparse": 0.26}, {}) == "unsuitable"
    assert _land_cover_status(row, {}, {"forest": 0.74}) == "unsuitable"
    assert _land_cover_status({}, {"bare_sparse": 0.1}, {}) == "missing"


def test_contradictory_land_cover_bounds_are_rejected_before_index_access(tmp_path):
    with pytest.raises(ValueError, match="minimum exceeds maximum"):
        rank(
            tmp_path / "missing.sqlite",
            "release",
            "target",
            MISSION_PRESETS["landing"]["weights"],
            land_cover_min_fractions={"forest": 0.8},
            land_cover_max_fractions={"forest": 0.2},
        )


def test_context_detail_retains_measurements_omitted_from_ranking_summary(tmp_path, monkeypatch):
    from twinworld import api

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    monkeypatch.setattr(api, "DISCOVERY_INDEX", index)
    ranking = rank(
        index,
        release,
        "lola_polar_moon_shackleton_rim",
        MISSION_PRESETS["landing"]["weights"],
        result_limit=1,
    )
    summary = ranking["results"][0]["context"]
    assert "measurements" not in summary
    detail = api.discovery_context_detail(summary["observation_id"])
    assert detail["index_id"] == release
    assert detail["context"]["measurements"]
    assert detail["dimensions"]["terrain"]["sources"]


def test_ten_result_moon_response_is_bounded_with_all_dimension_weights(tmp_path):
    from fastapi.testclient import TestClient

    from twinworld import api

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    previous = api.DISCOVERY_INDEX
    api.DISCOVERY_INDEX = index
    try:
        response = TestClient(api.app).post(
            "/api/discovery/rank",
            json={
                "index_id": release,
                "context_id": "lola_polar_moon_shackleton_rim",
                "weights": MISSION_PRESETS["landing"]["weights"],
                "dimension_weights": dict.fromkeys(DIMENSIONS, 1.0),
                "result_limit": 10,
            },
        )
    finally:
        api.DISCOVERY_INDEX = previous
    assert response.status_code == 200
    assert len(response.json()["results"]) == 10
    assert len(response.content) < 250 * 1024
    assert all(len(row["dimension_scores"]) == 8 for row in response.json()["results"])
    dimensions = {row["id"]: row for row in response.json()["results"][0]["dimension_scores"]}
    assert dimensions["terrain"]["comparison_variables"]
    assert dimensions["mission_operations"]["comparison_variables"] == []
    assert dimensions["mission_operations"]["shared_comparison_variables"]


def test_dimension_weights_require_all_eight_stable_ids(tmp_path):
    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    with pytest.raises(ValueError, match="all eight dimensions"):
        rank(
            index,
            release,
            "lola_polar_moon_shackleton_rim",
            MISSION_PRESETS["landing"]["weights"],
            dimension_weights={"terrain": 1.0},
        )
