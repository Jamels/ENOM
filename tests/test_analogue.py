from pathlib import Path

import pytest

from twinworld.analogue import (
    DIMENSIONS,
    PROFILES,
    _distance_km,
    build_places,
    candidate_context_records,
    discover,
    source_inventory,
    validate_dimension_weights,
)

ROOT = Path(__file__).resolve().parents[1]


def test_places_keep_separate_mare_contexts_distinct_and_group_nearby_products():
    places = build_places(ROOT)
    contexts = [
        place
        for place in places
        if place["body"] == "moon"
        and place["status"] == "observed_context"
        and "tranquillitatis" in place["id"]
    ]
    assert len(contexts) == 2
    assert len({round(place["longitude_east_deg"], 2) for place in contexts}) == 2
    datasets_by_context = [
        {item.get("dataset_id") for item in place["observations"]} for place in contexts
    ]
    assert all("lro-lola-gdr-ldem-64" in datasets for datasets in datasets_by_context)
    assert any("lro-diviner-gdr-level3-st-clc" in datasets for datasets in datasets_by_context)


def test_unreviewed_pilot_groups_are_not_default_places_but_candidate_places_remain():
    places = build_places(ROOT)
    ids = {place["id"] for place in places}
    assert "earth-pilot-badain_otherdune" not in ids
    assert "earth-namib" in ids
    assert all(
        observation.get("label_status") == "verified"
        for place in places
        for observation in place["observations"]
        if observation.get("kind") == "imagery" and observation.get("label_status")
    )
    restored = build_places(ROOT, include_unreviewed=True)
    assert "earth-pilot-badain_otherdune" in {place["id"] for place in restored}


def test_archived_catalogue_places_are_hidden_by_default_and_can_be_restored(tmp_path):
    manifest = tmp_path / "data/manifests/candidate-locations.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"entries":[{"id":"earth-current","name":"Current","body":"earth",'
        '"latitude_deg":0,"longitude_east_deg":0,"status":"candidate"},'
        '{"id":"earth-archived","name":"Archived","body":"earth",'
        '"latitude_deg":1,"longitude_east_deg":1,"status":"archived"}]}',
        encoding="utf-8",
    )
    assert {place["id"] for place in build_places(tmp_path)} == {"earth-current"}
    assert {place["id"] for place in build_places(tmp_path, include_archived=True)} == {
        "earth-current",
        "earth-archived",
    }


def test_dimension_weights_require_all_dimensions_and_reject_invalid_values():
    weights = dict(PROFILES["dunes"]["weights"])
    assert set(validate_dimension_weights(weights)) == set(DIMENSIONS)
    with pytest.raises(ValueError, match="all eight dimensions"):
        validate_dimension_weights({"terrain": 1.0})
    with pytest.raises(ValueError, match="all eight dimensions"):
        validate_dimension_weights({})
    weights["terrain"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        validate_dimension_weights(weights)


def test_discovery_returns_unique_places_and_missing_evidence_is_not_zero_score():
    result = discover(ROOT, "moon_mare_tranquillitatis_01", "mission_operations", limit=10)
    place_ids = [item["place"]["id"] for item in result["results"]]
    assert len(place_ids) == len(set(place_ids))
    assert len(place_ids) <= 10
    assert result["search_scope"].startswith("ENOM's current")
    assert all(len(item["dimension_scores"]) == 8 for item in result["results"])
    assert all(item["score"] is None or 0 < item["score"] <= 1 for item in result["results"])
    assert all(
        item["mission_suitability"]["status"] == "not_assessed" for item in result["results"]
    )


def test_polar_candidate_target_receives_scores_only_after_directly_supported_dem_is_linked():
    result = discover(ROOT, "moon-shackleton-rim", "subsurface_targets")
    assert result["results"]
    terrain = next(row for row in result["target_evidence"] if row["id"] == "terrain")
    assert terrain["status"] == "available"
    assert any(item["score"] is not None for item in result["results"])
    assert all(
        dimension["score"] is None
        for result_item in result["results"]
        for dimension in result_item["dimension_scores"]
        if dimension["id"] not in {"terrain", "mission_operations"}
    )


def test_terrain_operations_proxy_scores_hazards_without_claiming_mission_suitability():
    result = discover(ROOT, "moon-shackleton-rim", "mission_operations")
    for item in result["results"]:
        operations = next(
            row for row in item["dimension_scores"] if row["id"] == "mission_operations"
        )
        assert operations["score"] is not None
        assert operations["scored"] is True
        assert {
            row["name"]
            for row in operations["comparison_variables"]
            if row["availability"] == "available"
        } >= {"mean_slope", "median_roughness_3x3"}
        assert item["mission_suitability"]["status"] == "not_assessed"
    target_operations = next(
        row for row in result["target_evidence"] if row["id"] == "mission_operations"
    )
    assert "does not test a specific vehicle" in target_operations["summary"]

    terrain_weights = {name: 0.0 for name in DIMENSIONS}
    terrain_weights["terrain"] = 1.0
    operations_weights = {name: 0.0 for name in DIMENSIONS}
    operations_weights["mission_operations"] = 1.0
    terrain_only = discover(ROOT, "moon-shackleton-rim", "mission_operations", terrain_weights)
    operations_only = discover(
        ROOT, "moon-shackleton-rim", "mission_operations", operations_weights
    )
    assert terrain_only["results"][0]["place"]["id"] == operations_only["results"][0]["place"]["id"]
    assert terrain_only["results"][0]["score"] != operations_only["results"][0]["score"]


def test_source_inventory_separates_connected_and_planned_sources():
    inventory = {item["id"]: item for item in source_inventory(ROOT)}
    assert inventory["cop-dem-glo-30"]["status"] == "operational"
    assert inventory["cop-dem-glo-30"]["coverage_count"] == 18
    assert inventory["crism"]["status"] == "not_connected"
    assert inventory["usgs-spectral-library"]["status"] == "reference_only"
    assert inventory["nasa-power-thermal"]["coverage_count"] == 8
    assert inventory["nasa-power-wind"]["status"] == "operational"
    assert inventory["nasa-power-humidity"]["coverage_count"] == 8
    assert inventory["era5-wind"]["status"] == "operational"
    assert inventory["era5-wind"]["coverage_count"] == 8
    assert inventory["era5-precipitation"]["coverage_count"] == 8
    assert "not a dust event" in inventory["era5-wind"]["role"]
    assert inventory["candidate-subsurface-context"]["status"] == "context_only"
    assert inventory["candidate-subsurface-context"]["coverage_count"] == 5
    assert inventory["cave-records"]["status"] == "not_connected"
    assert inventory["candidate-mission-site-context"]["coverage_count"] == 3
    assert inventory["mission-operations"]["status"] == "not_connected"
    assert inventory["mars2020-meda-temperature"]["coverage_count"] == 1
    assert inventory["mars2020-meda-wind"]["coverage_count"] == 1
    assert inventory["mars2020-meda-humidity"]["coverage_count"] == 1
    assert inventory["mola-meg128"]["coverage_count"] == 13
    assert inventory["lola-ldem64"]["coverage_count"] == 4
    assert inventory["lola-polar-dem"]["status"] == "operational"
    assert inventory["lola-polar-dem"]["coverage_count"] == 3


def test_meda_sol_observations_are_linked_as_context_not_cross_body_scores():
    result = discover(ROOT, "mars-jezero", "polar_resources")
    dimensions = {row["id"]: row for row in result["target_evidence"]}
    temperature = next(
        row
        for row in dimensions["thermal_illumination"]["measurements"]
        if row["name"].startswith("MEDA ATS")
    )
    wind = next(
        row
        for row in dimensions["dust_processes"]["measurements"]
        if row["name"] == "MEDA horizontal wind speed"
    )
    humidity = next(
        row
        for row in dimensions["water_resources"]["measurements"]
        if row["name"].startswith("MEDA near-surface")
    )
    assert temperature["units"] == "K" and temperature["sample_count"] > 1000
    assert wind["units"] == "m/s" and wind["sample_count"] > 0
    assert humidity["units"] == "%RH" and humidity["sample_count"] > 0
    for candidate in result["results"]:
        scored = {row["id"]: row for row in candidate["dimension_scores"]}
        assert all(
            scored[key]["score"] is None
            for key in ("thermal_illumination", "dust_processes", "water_resources")
        )
    humidity_evidence = next(
        row
        for row in dimensions["water_resources"]["evidence_items"]
        if row["dataset_id"] == "mars2020-meda"
    )
    assert humidity_evidence["kind"] == "derived"
    assert (
        humidity_evidence["spatial_coverage"]["location_precision"]
        == "rover_track_in_mission_region"
    )
    assert "not soil water" in humidity_evidence["use_limit"]
    assert "sol median" in humidity_evidence["use_limit"]


def test_nasa_power_climatology_is_linked_to_earth_places_and_remains_context_only():
    namib = next(place for place in build_places(ROOT) if place["id"] == "earth-namib")
    thermal = next(
        item
        for item in discover(ROOT, "moon_mare_tranquillitatis_01", "dunes")["results"]
        if item["place"]["id"] == "earth-namib"
    )
    assert any(
        observation.get("dataset_id") == "nasa-power-climatology"
        for observation in namib["observations"]
    )
    climate_dimension = next(
        item for item in thermal["dimension_scores"] if item["id"] == "thermal_illumination"
    )
    wind_dimension = next(
        item for item in thermal["dimension_scores"] if item["id"] == "dust_processes"
    )
    moisture_dimension = next(
        item for item in thermal["dimension_scores"] if item["id"] == "water_resources"
    )
    assert climate_dimension["status"] == "available"
    assert wind_dimension["status"] == "available"
    assert climate_dimension["score"] is None
    assert wind_dimension["score"] is None
    assert moisture_dimension["status"] == "context_only"
    assert {measurement["name"] for measurement in moisture_dimension["measurements"]} == {
        "RH2M",
        "ERA5 average monthly precipitation total",
    }
    assert moisture_dimension["score"] is None
    assert "not a surface-water or ground-ice measurement" in moisture_dimension["summary"]


def test_candidate_diviner_and_tes_observations_are_place_linked_but_not_miscompared():
    jezero = next(place for place in build_places(ROOT) if place["id"] == "mars-jezero")
    mare_pit = next(
        place for place in build_places(ROOT) if place["id"] == "moon-mare-tranquillitatis-pit"
    )
    assert any(
        row.get("dataset_id") == "mgs-tes-derived-thermal-inertia" for row in jezero["observations"]
    )
    assert any(
        row.get("dataset_id") == "lro-diviner-gdr-level3-st-clc" for row in mare_pit["observations"]
    )

    mars_result = discover(ROOT, "mars-jezero", "polar_resources")
    thermal = next(
        row for row in mars_result["target_evidence"] if row["id"] == "thermal_illumination"
    )
    assert thermal["measurements"][0]["units"] == "J/(m^2*K*sqrt(s))"
    assert all(
        next(dim for dim in row["dimension_scores"] if dim["id"] == "thermal_illumination")["score"]
        is None
        for row in mars_result["results"]
    )


def test_power_measurements_stay_in_their_scientific_dimensions():
    result = discover(ROOT, "mars-jezero", "dunes")
    namib = next(row for row in result["results"] if row["place"]["id"] == "earth-namib")
    dimensions = {row["id"]: row for row in namib["dimension_scores"]}
    assert {row["name"] for row in dimensions["thermal_illumination"]["measurements"]} == {
        "T2M",
        "ALLSKY_SFC_SW_DWN",
        "ERA5 monthly mean 2 m air temperature",
    }
    assert {row["name"] for row in dimensions["dust_processes"]["measurements"]} == {
        "WS10M",
        "ERA5 monthly mean 10 m wind speed",
    }
    assert {row["name"] for row in dimensions["water_resources"]["measurements"]} == {
        "RH2M",
        "ERA5 average monthly precipitation total",
    }
    wind_evidence = dimensions["dust_processes"]["evidence_items"][0]
    assert wind_evidence["kind"] == "derived"
    assert wind_evidence["location"]["body"] == "earth"
    assert wind_evidence["temporal_coverage"]
    assert wind_evidence["uncertainty"]
    assert wind_evidence["source_url"].startswith("https://power.larc.nasa.gov/")


def test_cave_and_mission_catalogue_context_is_not_treated_as_measurement_or_score():
    cave = discover(ROOT, "mars-jezero", "subsurface_targets")
    lava_beds = next(row for row in cave["results"] if row["place"]["id"] == "earth-lava-beds")
    subsurface = next(row for row in lava_beds["dimension_scores"] if row["id"] == "subsurface")
    assert subsurface["status"] == "not_observed"
    assert subsurface["score"] is None
    assert subsurface["context_evidence"][0]["kind"] == "interpreted"
    assert "no surveyed subsurface geometry" in subsurface["context_evidence"][0]["uncertainty"]

    operations = discover(ROOT, "mars-jezero", "mission_operations")
    mission = next(
        row for row in operations["target_evidence"] if row["id"] == "mission_operations"
    )
    assert mission["status"] == "available"
    assert mission["context_evidence"][0]["kind"] == "interpreted"
    assert any(
        item["dataset_id"] == "mars2020-rover-places-best-tactical"
        for item in mission["evidence_items"]
    )
    assert all(
        row["mission_suitability"]["status"] == "not_assessed" for row in operations["results"]
    )

    earth_record = next(
        row for row in candidate_context_records(ROOT) if row["place_id"] == "earth-lava-beds"
    )
    lunar_record = next(
        row
        for row in candidate_context_records(ROOT)
        if row["place_id"] == "moon-marius-hills-hole"
    )
    assert earth_record["measurement_status"] == "no_measurement"
    assert lunar_record["measurement_status"] == "no_measurement"
    assert "possible lava-tube skylight" in lunar_record["summary"]


def test_peer_reviewed_extremophile_studies_are_linked_as_context_only():
    result = discover(ROOT, "mars-jezero", "dunes")
    by_site = {row["place"]["id"]: row for row in result["results"]}
    yungay = next(
        item
        for item in by_site["earth-atacama-yungay"]["dimension_scores"]
        if item["id"] == "biology_habitability"
    )
    assert yungay["status"] == "context_only"
    assert yungay["score"] is None
    yungay_study = yungay["evidence_items"][0]
    assert yungay_study["kind"] == "measured"
    assert yungay_study["location"]["latitude_deg"] == pytest.approx(-24.0848)
    assert yungay_study["location"]["longitude_east_deg"] == pytest.approx(290.08493)
    assert _distance_km(-24.1, 289.5, -24.0848, 290.08493) == pytest.approx(59.4, abs=0.1)
    assert "60 km away" in yungay_study["spatial_relation"]
    assert {measurement["name"] for measurement in yungay["measurements"]} == {
        "Relative humidity in a subsurface clay layer",
        "Water activity in a subsurface clay layer",
    }
    moisture = next(
        item
        for item in by_site["earth-atacama-yungay"]["dimension_scores"]
        if item["id"] == "water_resources"
    )
    assert moisture["status"] == "context_only"
    assert moisture["score"] is None
    assert "not a recoverable reserve" in moisture["summary"]
    assert {measurement["name"] for measurement in moisture["measurements"]} == {
        "Relative humidity in a subsurface clay layer",
        "Water activity in a subsurface clay layer",
        "RH2M",
        "ERA5 average monthly precipitation total",
    }

    haughton = next(
        item
        for item in by_site["earth-haughton-crater"]["dimension_scores"]
        if item["id"] == "biology_habitability"
    )
    assert haughton["evidence_items"][0]["spatial_coverage"]["location_precision"] == "region_only"
    assert haughton["measurements"][0]["units"] == "isolates"
    mc_murdo = next(
        item
        for item in by_site["earth-mcmurdo-dry-valleys"]["dimension_scores"]
        if item["id"] == "biology_habitability"
    )
    assert mc_murdo["evidence_items"][0]["temporal_coverage"].endswith("2012–2013 austral summer")

    source = next(
        item for item in source_inventory(ROOT) if item["id"] == "earth-extremophile-studies"
    )
    assert source["coverage_count"] == 3
    assert all(
        next(
            dimension
            for dimension in row["dimension_scores"]
            if dimension["id"] == "biology_habitability"
        )["score"]
        is None
        for row in result["results"]
    )


def test_usgs_earth_geology_is_linked_where_the_map_covers_and_outside_extent_is_explicit():
    result = discover(ROOT, "mars-jezero", "geology_materials")
    carlsbad = next(
        row for row in result["results"] if row["place"]["id"] == "earth-carlsbad-caverns"
    )
    geology = next(dim for dim in carlsbad["dimension_scores"] if dim["id"] == "geology_materials")
    assert geology["status"] == "available"
    assert geology["interpretations"][0]["map_unit_name"] == "Capitan Formation"
    assert geology["interpretations"][0]["major_materials"] == ["Carbonate"]
    assert geology["score"] is None
    geology_record = geology["evidence_items"][0]
    assert geology_record["kind"] == "interpreted"
    assert geology_record["spatial_coverage"]["nominal_cartographic_scale"] == "1:500,000"
    assert geology_record["interpretation"]["classification_status"] == "mapped"

    atacama = next(row for row in result["results"] if row["place"]["id"] == "earth-atacama-yungay")
    atacama_geology = next(
        dim for dim in atacama["dimension_scores"] if dim["id"] == "geology_materials"
    )
    assert atacama_geology["status"] == "outside_coverage"
    earth_source = next(
        item for item in atacama_geology["source_connections"] if item["id"] == "usgs-earth-geology"
    )
    assert earth_source["place_status"] == "outside_coverage"

    inventory = {item["id"]: item for item in source_inventory(ROOT)}
    assert inventory["usgs-earth-geology"]["coverage_count"] == 3


def test_mola_to_copernicus_discovery_ranks_unique_catalogue_places():
    result = discover(ROOT, "mars-jezero", "mission_operations", limit=10)
    assert len(result["results"]) == 8
    assert len({row["place"]["id"] for row in result["results"]}) == 8
    assert all(row["score"] is not None for row in result["results"])
    assert all(row["rank"] is not None for row in result["results"])


def test_sparse_mola_windows_are_excluded_and_geology_context_keeps_map_provenance():
    gale = discover(ROOT, "mars-gale", "mission_operations")
    assert all(row["score"] is None for row in gale["results"])
    assert all(
        "below the 25% comparison threshold" in row["dimension_scores"][1]["score_note"]
        for row in gale["results"]
    )

    mare = discover(ROOT, "moon-mare-tranquillitatis-pit", "geology_materials")
    geology = next(item for item in mare["target_evidence"] if item["id"] == "geology_materials")
    assert geology["interpretations"][0]["map_unit_code"] == "Im2"
    assert geology["interpretations"][0]["map_unit_interpretation"] == "Basaltic lava flows"
    assert any(
        layer["id"] == "geology_context" and layer["status"] == "point_context"
        for layer in mare["target_layers"]
    )
    lunar_coverage = next(
        layer for layer in mare["target_layers"] if layer["id"] == "terrain_coverage"
    )
    assert lunar_coverage["status"] == "metadata_only"
    assert lunar_coverage["observations"][0]["coverage_fraction"] is None
    assert lunar_coverage["observations"][0]["coverage_kind"] == "not_quantified"
