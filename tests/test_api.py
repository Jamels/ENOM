import math

import pytest
import yaml
from fastapi import HTTPException

from twinworld import api as api_module
from twinworld.api import (
    SearchRequest,
    AnalogueDiscoveryRequest,
    analogue_profiles,
    analogue_sources,
    catalogue,
    comparison,
    dataset_coverage,
    datasets,
    planets,
    region,
    search,
    discover_analogues,
    places,
)
from twinworld.retrieval import search as visual_search
from twinworld.science import Availability, PhysicalMeasurement


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


def test_visual_api_order_matches_shared_retrieval():
    query_id = "mars-dune-barchan_crescent_dune-0067+071"
    records, indexes, vectors = api_module._load()
    expected = visual_search(vectors, records, indexes[query_id], top_k=50)
    actual = search(
        SearchRequest(observation_id=query_id, method="visual", limit=50)
    )

    assert [item.observation_id for item in actual.results] == [
        records[index].image_id for index, _ in expected
    ]
    assert [item.cosine_similarity for item in actual.results] == pytest.approx(
        [score for _, score in expected]
    )


def test_embedding_metadata_must_match_a_configured_model_and_preprocessing():
    config = yaml.safe_load(api_module.MODEL_CONFIG.read_text(encoding="utf-8"))
    preprocessing_id = config["preprocessing"]["id"]
    for profile in config["models"].values():
        metadata = {
            "model_id": profile["model_id"],
            "revision": profile["revision"],
            "embedding_dimension": profile["embedding_dimension"],
            "preprocessing_id": preprocessing_id,
        }
        api_module._validate_embedding_identity(metadata)

        metadata["revision"] = "stale-revision"
        with pytest.raises(RuntimeError, match="model identity"):
            api_module._validate_embedding_identity(metadata)

        metadata["revision"] = profile["revision"]
        metadata["preprocessing_id"] = "stale-preprocessing"
        with pytest.raises(RuntimeError, match="preprocessing"):
            api_module._validate_embedding_identity(metadata)


def test_copernicus_coverage_matches_ingested_region():
    coverage = dataset_coverage("cop-dem-glo-30")
    assert coverage["coverage_count"] == 18
    selected_region = region("earth_namib_barchan-01")
    assert "terrain_dem" in selected_region["available_evidence"]
    assert len(selected_region["measurements"]) == 6


def test_candidate_catalogue_and_lunar_coverage_are_separate_from_image_index():
    entries = catalogue()["entries"]
    assert len(entries) >= 12
    assert any(item["body"] == "moon" for item in entries)
    lunar = dataset_coverage("lro-lola-gdr-ldem-64")
    assert lunar["status"] == "available"
    assert lunar["coverage_count"] == 4
    assert "moon_mare_tranquillitatis_diviner_01" in lunar["observation_ids"]
    bodies = {item["id"]: item for item in planets()}
    assert bodies["moon"]["available"] is False
    assert dataset_coverage("lro-diviner-gdr-level3-st-clc")["coverage_count"] == 2
    assert dataset_coverage("mgs-tes-derived-thermal-inertia")["coverage_count"] == 4
    earth_geology = dataset_coverage("usgs-earth-sgmc")
    assert earth_geology["coverage_count"] == 3
    assert earth_geology["candidate_site_query_count"] == 8
    assert any(row["id"] == "usgs-earth-sgmc" for row in datasets())


def test_mars_api_longitude_is_normalized_to_east_positive_range():
    payload = region("mars-dune-barchan_crescent_dune-0067+071")
    assert 0 <= payload["longitude_east_deg"] < 360


def test_place_and_analogue_api_exposes_profiles_evidence_and_source_status():
    profile_rows = analogue_profiles()
    assert {row["id"] for row in profile_rows} == {
        "dunes", "polar_resources", "geology_materials", "subsurface_targets", "mission_operations"
    }
    result = discover_analogues(AnalogueDiscoveryRequest(
        target_site_id="moon_mare_tranquillitatis_01", profile_id="mission_operations", limit=10
    ))
    assert result["unique_place_count"] == len({row["place"]["id"] for row in result["results"]})
    assert len(result["target_evidence"]) == 8
    assert result["target"]["id"] == "observed-moon_mare_tranquillitatis_01"
    assert any(item["id"] == "cop-dem-glo-30" and item["coverage_count"] == 18 for item in analogue_sources())
    assert dataset_coverage("nasa-power-climatology")["coverage_count"] == 8
    assert any(item["id"] == "nasa-power-humidity" and item["coverage_count"] == 8 for item in analogue_sources())
    cave_context = dataset_coverage("candidate-subsurface-context")
    assert cave_context["status"] == "context_only"
    assert cave_context["coverage_count"] == 5
    assert cave_context["body_counts"] == {"earth": 3, "moon": 2}
    assert all(row["measurement_status"] == "no_measurement" for row in cave_context["observations"])
    mission_context = dataset_coverage("candidate-mission-site-context")
    assert mission_context["coverage_count"] == 3
    assert mission_context["body_counts"] == {"mars": 3}
    meda = dataset_coverage("mars2020-meda")
    assert meda["coverage_count"] == 3
    assert meda["unique_place_count"] == 1
    assert meda["scope"] == "Selected Mars sol 100 only; not a Mars climate normal or full rover traverse archive."
    assert any(item["id"] == "mars2020-meda" for item in datasets())
    assert any(
        item["id"] == "observed-moon_mare_tranquillitatis_01"
        for item in places()["places"]
    )


def test_analogue_api_rejects_partial_dimension_weight_sets():
    request = AnalogueDiscoveryRequest(
        target_site_id="moon-mare-tranquillitatis_01", profile_id="dunes", weights={"terrain": 1.0}
    )
    with pytest.raises(HTTPException) as error:
        discover_analogues(request)
    assert error.value.status_code == 422
    with pytest.raises(ValueError, match="must be a number"):
        AnalogueDiscoveryRequest(target_site_id="mars-jezero", profile_id="dunes", weights={"terrain": True})


def test_candidate_geology_and_elevation_layers_are_available_when_rasters_exist():
    result = discover_analogues(AnalogueDiscoveryRequest(
        target_site_id="mars-jezero", profile_id="mission_operations", limit=10
    ))
    geology = next(item for item in result["target_evidence"] if item["id"] == "geology_materials")
    assert geology["status"] == "available"
    assert geology["interpretations"][0]["map_unit_code"] == "Nhc"
    assert any(layer["id"] == "geology_context" and layer["status"] == "point_context" for layer in result["target_layers"])
    assert result["target_layers"]
    if next(item for item in result["target_layers"] if item["id"] == "terrain_dem")["status"] == "available":
        preview = api_module.place_elevation_preview("mars-jezero")
        assert preview.media_type == "image/png"
        assert preview.body.startswith(b"\x89PNG\r\n\x1a\n")
        slope = api_module.place_slope_preview("mars-jezero")
        assert slope.media_type == "image/png"
        assert slope.body.startswith(b"\x89PNG\r\n\x1a\n")
        coverage = api_module.place_coverage_preview("mars-jezero")
        assert coverage.media_type == "image/png"
        assert coverage.body.startswith(b"\x89PNG\r\n\x1a\n")
        coverage_layer = next(item for item in result["target_layers"] if item["id"] == "terrain_coverage")
        assert coverage_layer["observations"][0]["coverage_fraction"] == pytest.approx(0.4772727273)
        thermal = next(item for item in result["target_evidence"] if item["id"] == "thermal_illumination")
        assert thermal["measurements"][0]["units"] == "J/(m^2*K*sqrt(s))"
        thermal_layer = next(item for item in result["target_layers"] if item["id"] == "thermal_context")
        assert thermal_layer["status"] == "available"
        thermal_preview = api_module.place_thermal_preview("mars-jezero")
        assert thermal_preview.media_type == "image/png"
        assert thermal_preview.body.startswith(b"\x89PNG\r\n\x1a\n")
        roughness = api_module.place_roughness_preview("earth-namib")
        assert roughness.media_type == "image/png"
        assert roughness.body.startswith(b"\x89PNG\r\n\x1a\n")
        namib = next(row for row in result["results"] if row["place"]["id"] == "earth-namib")
        roughness_layer = next(item for item in namib["layers"] if item["id"] == "terrain_roughness")
        assert roughness_layer["status"] == "available"


def test_body_layers_keep_separate_coordinates_and_mark_unavailable_products():
    for site_id, body in (
        ("mars-jezero", "mars"),
        ("moon-mare-tranquillitatis-pit", "moon"),
    ):
        result = discover_analogues(AnalogueDiscoveryRequest(
            target_site_id=site_id, profile_id="mission_operations", limit=10
        ))
        dem = next(layer for layer in result["target_layers"] if layer["id"] == "terrain_dem")
        assert dem["body"] == body
        assert "never overlaid directly" in dem["alignment_note"]
        assert dem["status"] in {"available", "metadata_only"}

    result = discover_analogues(AnalogueDiscoveryRequest(
        target_site_id="moon-mare-tranquillitatis-pit", profile_id="mission_operations", limit=10
    ))
    earth_candidate = next(row for row in result["results"] if row["place"]["id"] == "earth-namib")
    assert all(layer["body"] == "earth" for layer in earth_candidate["layers"] if "body" in layer)


def test_layer_previews_select_rasters_from_the_requested_physical_quantity():
    mars_elevation = api_module.place_elevation_preview("mars-jezero").body
    mars_thermal = api_module.place_thermal_preview("mars-jezero").body
    moon_elevation = api_module.place_elevation_preview("moon-mare-tranquillitatis-pit").body
    moon_thermal = api_module.place_thermal_preview("moon-mare-tranquillitatis-pit").body

    assert mars_elevation != mars_thermal
    assert moon_elevation != moon_thermal

    with pytest.raises(HTTPException) as error:
        api_module.place_thermal_preview("earth-namib")
    assert error.value.status_code == 404


def test_lola_south_polar_products_are_exposed_as_supported_candidate_layers():
    coverage = api_module.dataset_coverage("lro-lola-gdr-polar-ldem-120m")
    assert coverage["coverage_count"] == 3
    assert set(coverage["place_ids"]) == {
        "moon-shackleton-rim", "moon-malapert-massif", "moon-de-gerlache-rim"
    }
    result = api_module.discover_analogues(AnalogueDiscoveryRequest(
        target_site_id="moon-malapert-massif", profile_id="polar_resources", limit=10
    ))
    terrain = next(row for row in result["target_evidence"] if row["id"] == "terrain")
    assert terrain["status"] == "available"
    assert any(row["score"] is not None for row in result["results"])
    dem = next(row for row in result["target_layers"] if row["id"] == "terrain_dem")
    support = next(row for row in result["target_layers"] if row["id"] == "terrain_coverage")
    assert dem["status"] == "available" and dem["body"] == "moon"
    assert dem["crs"] == ["Moon south-polar stereographic (DE421 frame)"]
    assert support["status"] == "available"
    assert support["observations"][0]["coverage_kind"] == "direct_lola_shot_count"
    assert api_module.place_elevation_preview("moon-malapert-massif").body.startswith(b"\x89PNG\r\n\x1a\n")


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


def test_terrain_vector_excludes_measurements_marked_unavailable(monkeypatch):
    unavailable = PhysicalMeasurement(
        name="mean_slope",
        value=0.0,
        units="degree",
        availability=Availability.NOT_OBSERVED,
        spatial_scale_m=926.0,
    )
    monkeypatch.setattr(api_module, "_terrain_quality", lambda _id: {"eligible": True})
    monkeypatch.setattr(api_module, "_terrain_measurements", lambda _id: [unavailable])
    api_module._terrain_vector.cache_clear()
    try:
        assert api_module._terrain_vector("unavailable-fixture") == {}
    finally:
        api_module._terrain_vector.cache_clear()


def test_terrain_similarity_uses_documented_scale_fallback_when_mad_is_zero(monkeypatch):
    values = {"query": 1.0, "candidate": 2.0, "other": 1.0}
    monkeypatch.setattr(
        api_module,
        "_terrain_vector",
        lambda observation_id: {"elevation_range": (values[observation_id], 100.0, "m")},
    )
    assert api_module._terrain_similarity("query", "candidate", list(values)) == pytest.approx(
        math.exp(-1.0)
    )


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
