import io
import json
import math
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
import shapefile
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from scripts import ingest_diviner_scorecard as diviner_module
from scripts import ingest_mars_geology as mars_geology_module
from scripts import ingest_nasadem_scorecard as nasadem_module
from twinworld import api as api_module
from twinworld.api import app
from twinworld.records import read_jsonl, write_jsonl
from twinworld.scorecards import compare_candidate, mission_suitability, validate_weights


def measurement(name, value, scale=926.1153343394911, units="degree"):
    return {
        "name": name,
        "value": value,
        "units": units,
        "availability": "available",
        "spatial_scale_m": scale,
    }


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


def test_measurements_marked_unavailable_do_not_affect_ranking_or_screening():
    unavailable = measurement("mean_slope", 0.0) | {"availability": "not_observed"}
    candidate = compare_candidate(
        [measurement("mean_slope", 5.0)],
        [unavailable],
        {"mean_slope": 1.0},
    )
    assert candidate["similarity_score"] is None
    assert candidate["data_completeness"] == 0
    assert candidate["variables"][0]["availability"] == "unmatched_or_missing"
    assert mission_suitability([unavailable], "landing")["status"] == "insufficient_data"


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_nonfinite_measurements_are_not_scored_or_used_for_mission_screening(bad_value):
    invalid = measurement("slope_p90", bad_value)
    candidate = compare_candidate([invalid], [invalid], {"slope_p90": 1.0})
    assert candidate["similarity_score"] is None
    assert candidate["data_completeness"] == 0
    assert mission_suitability([invalid], "landing")["status"] == "insufficient_data"


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


def test_mola_relief_compares_at_matching_footprint_and_leaves_other_features_missing():
    result = compare_candidate(
        [measurement("elevation_range", 200, scale=10187.27, units="m")],
        [measurement("elevation_range", 200, scale=10187.27, units="m")],
        {"elevation_range": 0.2, "mean_slope": 0.8},
    )
    assert result["similarity_score"] == pytest.approx(1.0)
    assert result["data_completeness"] == 0.5
    assert result["variables"][0]["score"] == pytest.approx(1.0)
    assert result["variables"][1]["score"] is None


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
    assert mission_suitability([], "landing")["checks"][0]["basis_source_url"].endswith(
        "VIPER_Technical_Information_AFPP.pdf"
    )
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
    moon = next(site for site in sites.json()["sites"] if site["body"] == "moon")
    assert moon["source_product_id"] == "LDEM_64"
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

    limited = client.post(
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
            "limit": 1,
        },
    )
    assert limited.status_code == 200, limited.text
    limited_payload = limited.json()
    assert len(limited_payload["candidates"]) == 1
    assert (
        limited_payload["candidate_coverage"]["indexed_earth_dem_contexts"]
        == payload["candidate_coverage"]["indexed_earth_dem_contexts"]
    )


def test_diviner_context_flows_through_scorecard_without_thermal_similarity(monkeypatch):
    monkeypatch.setattr(
        api_module, "_load", lambda: (_ for _ in ()).throw(AssertionError("visual index loaded"))
    )
    client = TestClient(app)
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "moon_mare_tranquillitatis_diviner_01",
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
    environment = payload["site"]["environmental_evidence"]
    assert environment["measurement"]["value"] == pytest.approx(94.48, abs=0.02)
    assert environment["measurement"]["units"] == "K"
    assert environment["earth_comparison_status"] == "not_compared"
    assert payload["site"]["measurements"]
    assert all("temperature" not in item["name"] for item in payload["site"]["measurements"])
    assert all("temperature" not in item["name"] for item in payload["candidates"][0]["variables"])


def test_tes_thermal_inertia_flows_as_mars_environmental_evidence_only(monkeypatch):
    monkeypatch.setattr(
        api_module, "_load", lambda: (_ for _ in ()).throw(AssertionError("visual index loaded"))
    )
    client = TestClient(app)
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "mars_aeolis_nondune-01",
            "mission_objective": "landing",
            "weights": {
                "elevation_range": 1.0,
                "mean_slope": 0.0,
                "slope_p90": 0.0,
                "median_local_relief_3x3": 0.0,
                "median_roughness_3x3": 0.0,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    evidence = payload["site"]["environmental_evidence"]
    assert evidence["dataset_id"] == "mgs-tes-derived-thermal-inertia"
    assert evidence["measurement"]["value"] == pytest.approx(68.0)
    assert evidence["summary"]["median"] == pytest.approx(68.0)
    assert evidence["measurement"]["units"] == "J/(m^2*K*sqrt(s))"
    assert evidence["valid_sample_count"] == 63
    assert evidence["mask_url"].endswith("global_ti_msk_night_2007.img")
    assert evidence["earth_comparison_status"] == "not_compared"
    assert evidence["scorecard_role"].startswith("environmental_evidence_only")
    assert all(
        "thermal inertia" not in variable["name"].lower()
        for variable in payload["candidates"][0]["variables"]
    )


def test_geologic_map_point_lookup_handles_wrapped_longitude_holes_and_boundaries():
    shp, shx, dbf = (io.BytesIO(), io.BytesIO(), io.BytesIO())
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    writer.field("Unit", "C", size=10)
    writer.poly(
        [
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
            [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)],
        ]
    )
    writer.record("TEST")
    writer.close()
    reader = shapefile.Reader(
        shp=io.BytesIO(shp.getvalue()),
        shx=io.BytesIO(shx.getvalue()),
        dbf=io.BytesIO(dbf.getvalue()),
    )

    assert mars_geology_module.normalize_east_longitude(342.0) == pytest.approx(-18.0)
    assert mars_geology_module.mapped_unit_at(reader, 5.0, 2.0) == ("mapped", "TEST")
    assert mars_geology_module.mapped_unit_at(reader, 5.0, 5.0) == ("unmapped", None)
    assert mars_geology_module.mapped_unit_at(reader, 0.0, 5.0) == (
        "boundary_ambiguous",
        None,
    )


def test_usgs_geology_evidence_flows_to_mars_scorecard_only(monkeypatch):
    monkeypatch.setattr(
        api_module, "_load", lambda: (_ for _ in ()).throw(AssertionError("visual index loaded"))
    )
    api_module._mars_geology_records.cache_clear()
    client = TestClient(app)
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "mars_aeolis_nondune-01",
            "mission_objective": "landing",
            "weights": {
                "elevation_range": 1.0,
                "mean_slope": 0.0,
                "slope_p90": 0.0,
                "median_local_relief_3x3": 0.0,
                "median_roughness_3x3": 0.0,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    evidence = payload["site"]["geology_evidence"]
    assert evidence["dataset_id"] == "usgs-sim-1083-mars-global-geology"
    assert evidence["classification_status"] == "mapped"
    assert evidence["map_unit_code"] == "Hpr"
    assert evidence["dataset_reference_url"] == "https://doi.org/10.5066/P9UGAC18"
    assert evidence["scorecard_role"].startswith("geology_context_only")
    assert all(
        "geology" not in variable["name"].lower()
        for variable in payload["candidates"][0]["variables"]
    )
    mars_record = next(
        record
        for record in read_jsonl(api_module.MANIFEST)
        if record.image_id == "mars_aeolis_nondune-01"
    )
    record_payload = api_module._record_payload(mars_record)
    assert "geology" in record_payload["available_evidence"]
    assert "geology" not in record_payload["unavailable_evidence"]


def test_unified_lunar_geology_flows_to_moon_scorecard_as_context_only():
    client = TestClient(app)
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "moon_mare_tranquillitatis_01",
            "mission_objective": "landing",
            "weights": {
                "elevation_range": 0.0,
                "mean_slope": 1.0,
                "slope_p90": 0.0,
                "median_local_relief_3x3": 0.0,
                "median_roughness_3x3": 0.0,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()["site"]["geology_evidence"]
    assert payload["dataset_id"] == "usgs-fortezzo-2020-unified-lunar-geology"
    assert payload["classification_status"] == "mapped"
    assert payload["map_unit_code"] == "Im2"
    assert payload["map_unit_name"] == "Upper Mare Unit"
    assert payload["map_unit_interpretation"] == "Basaltic lava flows"
    assert payload["scorecard_role"].startswith("geology_context_only")
    assert api_module._geology_evidence_for("moon_mare_tranquillitatis_diviner_01")[
        "map_unit_code"
    ] == "Im2"


def test_lunar_geology_projection_wraps_east_longitude_and_validates_latitude():
    from scripts import ingest_lunar_geology as lunar_geology_module

    assert lunar_geology_module.normalize_east_longitude(-328.0) == pytest.approx(32.0)
    assert lunar_geology_module.mercator_point(-328.0, 8.5) == pytest.approx(
        lunar_geology_module.mercator_point(32.0, 8.5)
    )
    with pytest.raises(ValueError, match="latitude"):
        lunar_geology_module.mercator_point(32.0, 90.0)


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


def test_real_mola_scorecard_api_exposes_partial_support_and_limited_features(monkeypatch):
    monkeypatch.setattr(
        api_module, "_load", lambda: (_ for _ in ()).throw(AssertionError("visual index loaded"))
    )
    client = TestClient(app)
    sites = client.get("/api/scorecards/sites").json()["sites"]
    mars = next(site for site in sites if site["body"] == "mars")
    assert mars["dataset_id"] == "mola-meg128"
    assert mars["counts_source_url"].endswith(".img")
    assert mars["data_coverage"]["status"] == "partial"
    assert 0 < mars["data_coverage"]["observed_cell_fraction"] < 1
    response = client.post(
        "/api/scorecards/rank",
        json={
            "site_id": "mars_aeolis_nondune-01",
            "mission_objective": "landing",
            "weights": {
                "elevation_range": 0.2,
                "mean_slope": 0.28,
                "slope_p90": 0.24,
                "median_local_relief_3x3": 0.16,
                "median_roughness_3x3": 0.12,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["site"]["body"] == "mars"
    assert payload["site"]["source"]["dataset_id"] == "mola-meg128"
    assert payload["site"]["source"]["support_url"].endswith(".img")
    assert payload["site"]["source"]["label_url"].endswith(".xml")
    assert payload["site"]["source"]["retrieved_at"] is None
    assert payload["site"]["mission_suitability"]["status"] == "insufficient_data"
    assert payload["candidates"]
    for candidate in payload["candidates"]:
        assert candidate["data_completeness"] == 0.2
        assert candidate["matched_variable_count"] == 1
        assert candidate["variables"][0]["name"] == "elevation_range"
        assert candidate["variables"][0]["availability"] == "available"


def test_diviner_ingestion_writes_separate_environmental_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(diviner_module, "ROOT", tmp_path)
    crop = np.full((44, 44), 94.5, dtype=np.float32)
    crop[:4, :4] = np.nan
    monkeypatch.setattr(
        diviner_module,
        "fetch_crop",
        lambda *args, **kwargs: (crop, 4000, 9000),
    )

    metadata = diviner_module.ingest(output_id="moon_diviner_test")

    assert metadata["dataset_id"] == "lro-diviner-gdr-level3-st-clc"
    assert metadata["valid_sample_fraction"] == pytest.approx(1 - 16 / 1936)
    assert metadata["measurement"]["value"] == pytest.approx(94.5)
    assert metadata["measurement"]["units"] == "K"
    assert metadata["scorecard_role"] == (
        "environmental_evidence_only; excluded from terrain ranking"
    )
    assert (tmp_path / metadata["output"]).is_file()
    assert (tmp_path / "data/terrain/diviner_moon_diviner_test.tif.json").is_file()


def test_diviner_evidence_is_attached_without_becoming_terrain_measurement(tmp_path, monkeypatch):
    sidecar = tmp_path / "data/terrain/diviner_moon_diviner_test.tif.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(
        json.dumps(
            {
                "observation_id": "moon_diviner_test",
                "dataset_id": "lro-diviner-gdr-level3-st-clc",
                "source_product_id": "DGDR_ST_CLC_CYL_20120114N_128_IMG",
                "measurement": {"name": "nighttime regolith temperature", "value": 94.5},
                "scorecard_role": "environmental_evidence_only; excluded from terrain ranking",
                "earth_comparison_status": "not_compared",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_module, "ROOT", tmp_path)

    evidence = api_module._environmental_evidence_for("moon_diviner_test")

    assert evidence is not None
    assert evidence["measurement"]["value"] == 94.5
    assert evidence["scorecard_role"].startswith("environmental_evidence_only")


def test_nasadem_tile_name_and_source_classes_are_parsed_without_inventing_nodata(tmp_path):
    assert nasadem_module.tile_name(-67.5, -20.2) == "s21w068"
    assert nasadem_module.tile_name(15.1, -24.7) == "s25e015"
    with pytest.raises(ValueError):
        nasadem_module.tile_name(0, 61)
    zip_path = tmp_path / "tile.zip"
    heights = np.array([[10, 11], [12, -32768]], dtype=">i2")
    numbers = np.array([[1, 41], [250, 0]], dtype=np.uint8)
    water = np.array([[0, 0], [0, 255]], dtype=np.uint8)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("tile.hgt", heights.tobytes())
        archive.writestr("tile.num", numbers.tobytes())
        archive.writestr("tile.swb", water.tobytes())
    got_hgt, got_num, got_water = nasadem_module._read_members(zip_path, "s00e000", samples=2)
    assert got_hgt.tolist() == [[10.0, 11.0], [12.0, -32768.0]]
    assert got_num.tolist() == [[1, 41], [250, 0]]
    assert got_water.tolist() == [[0, 0], [0, 255]]


def test_nasadem_cmr_lookup_uses_exact_tile_and_archive_link(monkeypatch):
    entry = {
        "producer_granule_id": "NASADEM_HGT_s25e015",
        "updated": "2018-09-12T13:31:05.386Z",
        "links": [
            {
                "title": "Download NASADEM_HGT_s25e015.zip",
                "href": "https://data.example/NASADEM_HGT_s25e015.zip",
            }
        ],
    }
    observed = {}

    def fake_get(url, *, params, timeout):
        observed.update(params)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"feed": {"entry": [entry]}},
        )

    monkeypatch.setattr(nasadem_module.requests, "get", fake_get)
    granule = nasadem_module._granule("s25e015")
    assert observed["short_name"] == "NASADEM_HGT"
    assert observed["version"] == "001"
    assert observed["bounding_box"] == "15,-25,16,-24"
    assert granule["granule_id"] == "NASADEM_HGT_s25e015"
    assert granule["granule_url"].endswith(".zip")


def test_nasadem_ingestion_writes_scale_matched_measures_and_context_quality(tmp_path, monkeypatch):
    from rasterio.crs import CRS
    from rasterio.warp import transform

    root = tmp_path
    manifest = root / "manifest.jsonl"
    observation_id = "earth_namib_barchan-01"
    latitude, longitude = -24.736, 15.141
    crs = CRS.from_epsg(32733)
    x_values, y_values = transform("EPSG:4326", crs, [longitude], [latitude])
    x, y = x_values[0], y_values[0]
    patch_path = root / "patch.tif"
    with rasterio.open(
        patch_path,
        "w",
        driver="GTiff",
        width=20,
        height=20,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=from_origin(x - 100, y + 100, 10, 10),
    ) as raster:
        raster.write(np.ones((20, 20), dtype=np.uint8), 1)
    original = read_jsonl(Path("data/manifests/pilot-100.jsonl"))[0]
    record = replace(
        original,
        image_id=observation_id,
        body="earth",
        path=patch_path.name,
        latitude=latitude,
        longitude=longitude,
    )
    write_jsonl(manifest, [record])
    monkeypatch.setattr(nasadem_module, "ROOT", root)
    monkeypatch.setattr(nasadem_module, "MANIFEST", manifest)
    monkeypatch.setattr(nasadem_module, "PIXELS_PER_DEGREE", 10)
    monkeypatch.setattr(nasadem_module, "TILE_SAMPLES", 11)
    monkeypatch.setattr(
        nasadem_module,
        "_granule",
        lambda tile: {
            "granule_id": f"NASADEM_HGT_{tile}",
            "granule_url": "https://example.test/tile.zip",
            "granule_updated_at": "2018-09-12T13:31:05.386Z",
        },
    )

    def fake_download(url, cache, token):
        cache.parent.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(nasadem_module, "_download_tile", fake_download)
    y_grid, x_grid = np.mgrid[0:11, 0:11]
    hgt = (100 + x_grid + y_grid).astype(np.float32)
    num = np.full((11, 11), 1, dtype=np.uint8)
    num[0, 0] = 250
    swb = np.zeros((11, 11), dtype=np.uint8)
    monkeypatch.setattr(nasadem_module, "_read_members", lambda *args, **kwargs: (hgt, num, swb))
    output = root / "terrain.tif"
    metadata = nasadem_module.ingest(
        observation_id, output, token="test-token", context_size_m=500, target_pixel_m=23
    )
    assert metadata["source_product_id"] == "NASADEM_HGT_s25e015"
    assert metadata["vertical_datum"] == "EGM96 geoid"
    assert metadata["retrieved_at"] is not None
    assert sum(metadata["num_class_histogram"].values()) > 0
    assert 0 <= metadata["direct_srtm_class_fraction"] <= 1
    assert {item["name"] for item in metadata["measurements"]} >= {
        "elevation_range",
        "mean_slope",
        "slope_p90",
    }
    assert all(item["spatial_scale_m"] is not None for item in metadata["measurements"])
    assert output.with_suffix(".tif.json").is_file()


def test_nasadem_earth_products_rank_as_distinct_candidates(tmp_path, monkeypatch):
    original_sidecars = list(api_module.TERRAIN_SIDECARS)
    moon_sidecar = next(
        path
        for path in original_sidecars
        if json.loads(path.read_text())["dataset_id"] == "lro-lola-gdr-ldem-64"
    )
    earth_sidecar = next(
        path
        for path in original_sidecars
        if json.loads(path.read_text()).get("dataset_id") == "cop-dem-glo-30"
    )
    earth = json.loads(earth_sidecar.read_text())
    nasa = earth | {
        "dataset_id": "nasadem-hgt",
        "source_product_id": "NASADEM_HGT_s25e015",
        "source_url": "https://data.lpdaac.earthdatacloud.nasa.gov/tile.zip",
        "dataset_reference_url": "https://doi.org/10.5067/MEASURES/NASADEM/NASADEM_HGT.001",
        "measurements": [measurement("mean_slope", 2.0)],
        "data_coverage": {
            "status": "complete",
            "observed_cell_fraction": 1.0,
            "note": "NASADEM context data coverage fixture",
        },
        "direct_srtm_class_fraction": 0.91,
    }
    nasa_sidecar = tmp_path / "nasadem.tif.json"
    nasa_sidecar.write_text(json.dumps(nasa))
    monkeypatch.setattr(api_module, "TERRAIN_SIDECARS", [moon_sidecar, earth_sidecar, nasa_sidecar])
    response = TestClient(app).post(
        "/api/scorecards/rank",
        json={
            "site_id": "moon_mare_tranquillitatis_01",
            "mission_objective": "landing",
            "weights": {"mean_slope": 1},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    nasa_candidate = next(
        candidate
        for candidate in payload["candidates"]
        if candidate["source"]["dataset_id"] == "nasadem-hgt"
    )
    assert nasa_candidate["observation_id"].startswith("nasadem:")
    assert nasa_candidate["source"]["documentation_url"].endswith("NASADEM_HGT.001")
    assert nasa_candidate["source"]["direct_srtm_source_fraction"] == pytest.approx(0.91)
    assert "nasadem-hgt" in payload["candidate_coverage"]["dataset_ids"]
