import pytest

from twinworld.api import (
    SearchRequest,
    catalogue,
    comparison,
    dataset_coverage,
    planets,
    region,
    search,
)


def test_real_pilot_is_searchable_and_missing_data_is_explicit():
    query = region("mars-dune-barchan_crescent_dune-0067+071")
    payload = search(SearchRequest(observation_id=query["id"], profile="aeolian", limit=3))
    assert len(payload.results) == 3
    assert all(result.location["body"] == "earth" for result in payload.results)
    assert all(
        any(evidence.category == "terrain" for evidence in result.evidence)
        for result in payload.results
    )
    assert any("provisional" in item.lower() for item in payload.limitations)


def test_copernicus_coverage_matches_ingested_region():
    coverage = dataset_coverage("cop-dem-glo-30")
    assert coverage["coverage_count"] == 10
    selected_region = region("earth_namib_barchan-01")
    assert "terrain_dem" in selected_region["available_evidence"]
    assert len(selected_region["measurements"]) == 6


def test_candidate_catalogue_and_lunar_coverage_are_separate_from_image_index():
    entries = catalogue()["entries"]
    assert len(entries) >= 12
    assert any(item["body"] == "moon" for item in entries)
    lunar = dataset_coverage("lro-lola-gdr-ldem-64")
    assert lunar["status"] == "available"
    assert lunar["coverage_count"] == 1
    bodies = {item["id"]: item for item in planets()}
    assert bodies["moon"]["available"] is False


def test_mars_api_longitude_is_normalized_to_east_positive_range():
    payload = region("mars-dune-barchan_crescent_dune-0067+071")
    assert 0 <= payload["longitude_east_deg"] < 360


def test_terrain_and_combined_modes_return_inspectable_scores_and_rank_changes():
    query_id = "mars-dune-barchan_crescent_dune-0067+071"
    terrain = search(SearchRequest(observation_id=query_id, method="terrain", limit=5))
    combined = search(SearchRequest(observation_id=query_id, method="combined", limit=5))
    assert terrain.method == "terrain"
    assert terrain.terrain_eligible_candidates > 0
    assert all(result.terrain_similarity is not None for result in terrain.results)
    assert combined.method == "combined"
    assert all(result.combined_score is not None for result in combined.results)
    assert all(result.visual_rank is not None for result in combined.results)


def test_low_coverage_query_cannot_affect_combined_ranking():
    payload = search(
        SearchRequest(
            observation_id="mars-dune-barchan_crescent_dune-1284-163",
            method="combined",
            limit=5,
        )
    )
    assert payload.query_terrain_quality["eligible"] is False
    assert payload.results
    assert all(result.terrain_similarity is None for result in payload.results)
    assert all(result.ranking_evidence == ["visual_embedding"] for result in payload.results)


def test_cross_planet_comparison_reports_scale_matched_terrain_delta():
    result = comparison("mars-dune-barchan_crescent_dune-0067+071", "earth_namib_barchan-01")
    assert result["terrain_measurement_differences"][0]["name"] == "elevation_range"
    delta = result["terrain_measurement_differences"][0]
    assert delta["query_scale_m"] == delta["candidate_scale_m"]
    assert delta["difference_candidate_minus_query"] == pytest.approx(10.6527, abs=0.01)
    assert "additional terrain variables at matching scales" in result["data_gaps"]
