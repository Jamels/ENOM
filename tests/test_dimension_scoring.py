import math

import pytest

from twinworld.analogue import DIMENSIONS, validate_dimension_weights
from twinworld.dimension_scoring import compare_dimensions
from twinworld.scorecards import VARIABLES


def _weights(**overrides: float) -> dict[str, float]:
    result = {dimension_id: 0.0 for dimension_id in DIMENSIONS}
    result.update(overrides)
    return result


def _dimension_rows(offset: float = 0.0) -> list[dict[str, object]]:
    measurements = [
        {
            "name": name,
            "value": float(index) + offset,
            "units": spec["units"],
            "availability": "available",
            "spatial_scale_m": 1000.0,
            "source_url": "https://example.test/source",
            "observation_id": f"observation-{index}",
        }
        for index, (name, spec) in enumerate(VARIABLES.items(), start=1)
    ]
    return [
        {
            "id": dimension_id,
            "label": spec["label"],
            "status": "available" if dimension_id == "terrain" else "not_observed",
            "observation_ids": ["target-observation"],
            "sources": [{"source_url": "https://example.test/source"}],
            "scoring_measurements": measurements if dimension_id == "terrain" else [],
        }
        for dimension_id, spec in DIMENSIONS.items()
    ]


def test_all_dimensions_are_explicit_and_preserve_evidence_and_provenance():
    result = compare_dimensions(_dimension_rows(), _dimension_rows(2.0), _weights(terrain=1.0))
    assert len(result["dimension_scores"]) == 8
    assert [row["id"] for row in result["dimension_scores"]] == list(DIMENSIONS)
    terrain = result["dimension_scores"][1]
    assert terrain["observation_ids"] == ["target-observation"]
    assert terrain["sources"][0]["source_url"] == "https://example.test/source"
    assert terrain["score"] == pytest.approx(
        sum(math.exp(-2 / spec["tolerance"]) for spec in VARIABLES.values()) / len(VARIABLES)
    )
    assert terrain["scored"] is True
    assert all(isinstance(row["score"], float) and 0 <= row["score"] <= 1 for row in result["dimension_scores"])
    assert result["missing_evidence_dimensions"] == []
    assert result["evidence_class"] == "prototype_observed_subset"
    assert sum(row["normalized_contribution"] for row in result["dimension_scores"]) == pytest.approx(result["score"])


def test_shared_terrain_operations_budget_does_not_amplify_terrain_evidence():
    target = _dimension_rows()
    candidate = _dimension_rows(4.0)
    terrain_only = compare_dimensions(target, candidate, _weights(terrain=1.0))
    both = compare_dimensions(
        target,
        candidate,
        _weights(terrain=1.0, mission_operations=1.0),
    )
    assert sum(
        row["effective_weight"] for row in terrain_only["dimension_scores"]
    ) == pytest.approx(1.0)
    assert sum(row["effective_weight"] for row in both["dimension_scores"]) == pytest.approx(1.0)
    assert both["dimension_scores"][1]["effective_weight"] == pytest.approx(0.5)
    assert both["dimension_scores"][-1]["effective_weight"] == pytest.approx(0.5)
    assert "share" in both["dimension_scores"][-1]["score_note"]


def test_terrain_completeness_tracks_requested_measurement_weights():
    from twinworld.scorecards import compare_candidate

    target = _dimension_rows()
    reference = target[1]["scoring_measurements"]
    earth = [reference[0]]
    weights = {name: 0.05 for name in VARIABLES}
    weights["elevation_range"] = 0.8
    comparison = compare_candidate(reference, earth, weights)
    result = compare_dimensions(target, target, _weights(terrain=1.0), comparison)
    assert comparison["data_completeness"] == pytest.approx(0.2)
    assert result["evidence_coverage"] == pytest.approx(0.8)


def test_operations_only_weight_scores_four_supported_proxy_variables():
    result = compare_dimensions(
        _dimension_rows(), _dimension_rows(3.0), _weights(mission_operations=2.0)
    )
    operations = result["dimension_scores"][-1]
    assert operations["score"] is not None
    assert operations["effective_weight"] == pytest.approx(2.0)
    assert {row["name"] for row in operations["comparison_variables"]} == {
        "mean_slope",
        "slope_p90",
        "median_local_relief_3x3",
        "median_roughness_3x3",
    }
    assert result["score"] == pytest.approx(operations["score"])


def test_incompatible_or_missing_terrain_measurements_do_not_become_zero():
    target = _dimension_rows()
    candidate = _dimension_rows()
    target_terrain = target[1]
    candidate_terrain = candidate[1]
    target_terrain["scoring_measurements"] = [
        dict(row, units="km") for row in target_terrain["scoring_measurements"]
    ]
    candidate_terrain["scoring_measurements"] = []
    result = compare_dimensions(target, candidate, _weights(terrain=1.0))
    terrain = result["dimension_scores"][1]
    assert terrain["score"] == 0.5
    assert terrain["score_origin"] == "simulated"
    assert terrain["effective_weight"] == 1.0
    assert terrain["scored"] is True
    assert result["score"] == 0.5
    assert result["evidence_coverage"] == 0.0


def test_mapping_input_retains_linked_evidence_rows_verbatim():
    target_row = {"observation_id": "moon-dem", "units": "m", "value": 10}
    candidate_row = {"observation_id": "earth-dem", "units": "m", "value": 12}
    result = compare_dimensions(
        {"terrain": [target_row]},
        {"terrain": [candidate_row]},
        _weights(terrain=1.0),
    )
    terrain = result["dimension_scores"][1]
    assert terrain["evidence_items"] == [candidate_row]
    assert all(row["score"] is None for row in terrain["comparison_variables"])
    assert terrain["score"] == 0.5
    assert terrain["score_origin"] == "simulated"
    assert result["evidence_coverage"] == 0.0


@pytest.mark.parametrize("weight", [True, "1", float("nan"), float("inf"), -1.0])
def test_dimension_weights_reject_bool_nonnumeric_and_invalid_values(weight):
    weights = _weights(terrain=1.0)
    weights["terrain"] = weight
    with pytest.raises(ValueError):
        validate_dimension_weights(weights)


def test_dimension_weights_reject_finite_values_whose_total_overflows():
    with pytest.raises(ValueError, match="total dimension weight"):
        validate_dimension_weights(_weights(**{"terrain": 1.0e308, "mission_operations": 1.0e308}))


def test_scorer_requires_all_eight_finite_weights():
    with pytest.raises(ValueError, match="all eight"):
        compare_dimensions(_dimension_rows(), _dimension_rows(), {"terrain": 1.0})
    with pytest.raises(ValueError, match="finite"):
        compare_dimensions(_dimension_rows(), _dimension_rows(), _weights(terrain=float("nan")))


@pytest.mark.parametrize(
    "dimension_id,name,units,a,b,expected",
    [
        ("thermal_illumination", "surface_temperature", "K", 200.0, 250.0, 0.8),
        ("water_resources", "water_ice_mass_fraction", "kg/kg", 0.2, 0.4, 0.8),
        ("dust_processes", "surface_migration_rate", "m/year", 2.0, 4.0, 0.5),
        ("biology_habitability", "water_activity", "1", 0.8, 0.9, 0.9),
        ("subsurface", "observed_cavity_span", "m", 20.0, 40.0, 0.5),
    ],
)
def test_experimental_physical_protocols_require_real_comparability_metadata(
    dimension_id,
    name,
    units,
    a,
    b,
    expected,
):
    # Synthetic contract fixtures test algorithms; these are not observations
    # or demonstrations that real reference pairs have these measurements.
    def measure(value):
        return {
            "name": name,
            "value": value,
            "units": units,
            "availability": "available",
            "spatial_scale_m": 100,
            "support_fraction": 1.0,
            "comparison_basis": "fixture:identical-quantity-depth-time-statistic",
            "source_url": "https://example.test/observation",
            "product_id": "fixture",
            "feature_status": "observed_cavity",
        }

    weights = _weights(**{dimension_id: 1.0})
    reference = {dimension_id: [measure(a)]}
    candidate = {dimension_id: [measure(b)]}
    comparison = compare_dimensions(reference, candidate, weights)
    assert comparison["score"] == pytest.approx(expected)
    row = next(row for row in comparison["dimension_scores"] if row["id"] == dimension_id)
    assert row["methodology_kind"] == "measured"
    assert row["evidence_status"] == "matched_measurement"
    assert row["observed_score"] == pytest.approx(expected)
    for bad in (
        {"comparison_basis": "different-depth-or-time"},
        {"spatial_scale_m": 200},
        {"support_fraction": True},
        {"support_fraction": 0.5},
        {"value": None},
        {"value": True},
        {"value": float("nan")},
        {"units": "wrong"},
        {"source_url": None},
    ):
        result = compare_dimensions(reference, {dimension_id: [measure(b) | bad]}, weights)
        assert result["score"] == 0.5
        assert result["evidence_coverage"] == 0
        invalid = next(row for row in result["dimension_scores"] if row["id"] == dimension_id)
        assert invalid["observed_score"] is None
        assert invalid["score_origin"] == "simulated"


def test_real_mapped_materials_support_experimental_geology_without_code_matching():
    from pathlib import Path

    from twinworld.scientific_observations import dimension_inputs

    root = Path(__file__).resolve().parents[1]
    moon = dimension_inputs(root, "moon-mare-tranquillitatis-pit")
    mojave = dimension_inputs(root, "earth-mojave-lava-tube")
    carbonate = dimension_inputs(root, "earth-carlsbad-caverns")
    weights = _weights(geology_materials=1.0)
    assert compare_dimensions(moon, mojave, weights)["score"] == 1.0
    assert compare_dimensions(moon, carbonate, weights)["score"] == 0.0
    missing = compare_dimensions({}, mojave, weights)
    assert missing["score"] == 0.5
    assert missing["dimension_scores"][0]["score_origin"] == "simulated"


def test_zero_weight_geology_does_not_change_independent_evidence_class():
    from pathlib import Path

    from twinworld.scientific_observations import dimension_inputs

    root = Path(__file__).resolve().parents[1]
    result = compare_dimensions(
        dimension_inputs(root, "moon-mare-tranquillitatis-pit"),
        dimension_inputs(root, "earth-mojave-lava-tube"),
        _weights(terrain=1.0),
    )
    assert "geology_materials" not in result["independent_evidence_groups"]
