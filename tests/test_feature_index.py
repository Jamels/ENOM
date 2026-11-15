import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from twinworld.feature_index import build_index, resolve
from twinworld.terrain import terrain_features

ROOT = Path(__file__).resolve().parents[1]


def _sparse_mola_earth_fixture(root: Path) -> Path:
    terrain = root / "data/terrain"
    terrain.mkdir(parents=True)
    source = ROOT / "data/terrain"
    mola = "mola-meg128-mars_aeolis_nondune-01"
    for name in (f"{mola}.tif", f"{mola}-counts.tif", f"{mola}.tif.json"):
        shutil.copy2(source / name, terrain / name)

    context_m = 10187.268677734402
    cells = 22
    posting = context_m / cells
    raster_path = terrain / "earth-fixture.tif"
    crs = "EPSG:32632"
    elevation = np.tile(np.linspace(0, 202, cells, dtype=np.float32), (cells, 1))
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=cells,
        height=cells,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(500_000 - context_m / 2, context_m / 2, posting, posting),
        nodata=np.nan,
    ) as destination:
        destination.write(elevation, 1)
    measurements = [
        item.model_dump(mode="json")
        for item in terrain_features(
            raster_path,
            observation_id="earth-fixture",
            provider="Synthetic test fixture",
            product_id="fixture",
            source_url="https://example.invalid/fixture",
        )
    ]
    earth_sidecar = {
                "observation_id": "earth-fixture",
                "place_id": "earth-fixture",
                "body": "earth",
                "name": "Earth test context",
                "longitude_east_deg": 9,
                "latitude_deg": 0,
                "dataset_id": "cop-dem-glo-90",
                "provider": "Synthetic test fixture",
                "source_product_id": "fixture",
                "source_url": "https://example.invalid/fixture",
                "source_resolution_m": 90,
                "source_vertical_reference": "fixture",
                "processing_crs": crs,
                "output_pixel_size_m": [posting, posting],
                "context_size_m": context_m,
                "valid_pixel_fraction": 1,
                "observed_cell_fraction": 1,
                "land_cover": {
                    "status": "available",
                    "dataset_id": "esa-worldcover-2021-v200",
                    "valid_fraction": 1.0,
                    "sample_count": 100,
                    "source_tile": "S03W003",
                    "group_fractions": {
                        "bare_sparse": 1.0,
                        "forest": 0.0,
                        "cropland": 0.0,
                        "built_up": 0.0,
                        "snow_ice": 0.0,
                        "water": 0.0,
                        "grass_shrub_wetland": 0.0,
                    },
                },
                "uncertainty_note": "Synthetic fixture, not a real observation.",
                "missing_data_semantics": "No missing cells.",
                "output": "data/terrain/earth-fixture.tif",
                "measurements": measurements,
            }
    (terrain / "earth-fixture.tif.json").write_text(
        json.dumps(earth_sidecar, indent=2)
    )

    second_raster = terrain / "earth-fixture-b.tif"
    with rasterio.open(raster_path) as source_raster:
        profile = source_raster.profile.copy()
        profile["transform"] = from_origin(
            600_000 - context_m / 2, context_m / 2, posting, posting
        )
        with rasterio.open(second_raster, "w", **profile) as destination:
            destination.write(source_raster.read(1), 1)
    second_measurements = [
        item.model_dump(mode="json")
        for item in terrain_features(
            second_raster,
            observation_id="earth-fixture-b",
            provider="Synthetic test fixture",
            product_id="fixture-b",
            source_url="https://example.invalid/fixture-b",
        )
    ]
    second_sidecar = earth_sidecar | {
        "observation_id": "earth-fixture-b",
        "place_id": "earth-fixture-b",
        "name": "Earth test context B",
        "longitude_east_deg": 10,
        "source_product_id": "fixture-b",
        "source_url": "https://example.invalid/fixture-b",
        "output": "data/terrain/earth-fixture-b.tif",
        "measurements": second_measurements,
    }
    (terrain / "earth-fixture-b.tif.json").write_text(
        json.dumps(second_sidecar, indent=2)
    )
    return root


def test_real_index_build_is_reproducible_and_looks_up_actual_footprints(tmp_path):
    # The global acquisition can update its manifest between builds. Use the
    # same real terrain inputs while excluding that independently changing job.
    snapshot = tmp_path / "snapshot"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data/terrain").symlink_to(ROOT / "data/terrain", target_is_directory=True)
    index = tmp_path / "index.sqlite"
    first = build_index(snapshot, index)
    second = build_index(snapshot, tmp_path / "second.sqlite")
    assert first == second
    assert first["contexts"] >= 3
    mare = resolve(index, "moon", 8.3355, 33.222)
    assert any(
        row["observation_id"] == "moon_candidate_moon_mare_tranquillitatis_pit" for row in mare
    )
    aeolis = resolve(index, "mars", -3, 149.99156469757094)
    assert any(row["observation_id"] == "mars_aeolis_nondune-01" for row in aeolis)
    assert resolve(index, "moon", 0, 180) == []
    assert resolve(index, "moon", 8.3355, 393.222) == mare


def test_rejects_invalid_coordinates(tmp_path):
    with pytest.raises(ValueError):
        resolve(tmp_path / "missing.sqlite", "mars", float("nan"), 0)


def test_land_cover_summary_requires_consistent_complete_worldcover_metadata():
    from twinworld.feature_index import _validated_land_cover

    groups = {
        "bare_sparse": 0.1,
        "forest": 0.2,
        "cropland": 0.1,
        "built_up": 0.1,
        "snow_ice": 0.1,
        "water": 0.1,
        "grass_shrub_wetland": 0.3,
    }
    good = {
        "land_cover": {
            "status": "available",
            "dataset_id": "esa-worldcover-2021-v200",
            "valid_fraction": 1.0,
            "sample_count": 10_404,
            "source_tile": "S03W003",
            "group_fractions": groups,
        }
    }
    assert _validated_land_cover(good) == good["land_cover"]
    assert _validated_land_cover(
        good | {"land_cover": good["land_cover"] | {"valid_fraction": True}}
    ) is None
    assert _validated_land_cover(
        good | {"land_cover": good["land_cover"] | {"group_fractions": groups | {"water": 0.4}}}
    ) is None
    assert _validated_land_cover(
        good | {"land_cover": good["land_cover"] | {"status": "available", "valid_fraction": 0.9}}
    ) is None


def test_index_marks_inconsistent_worldcover_unavailable(tmp_path):
    import sqlite3

    fixture_root = _sparse_mola_earth_fixture(tmp_path)
    sidecar = fixture_root / "data/terrain/earth-fixture.tif.json"
    metadata = json.loads(sidecar.read_text())
    metadata["land_cover"]["group_fractions"]["water"] = 0.5
    sidecar.write_text(json.dumps(metadata))

    index = tmp_path / "index.sqlite"
    build_index(fixture_root, index)
    with sqlite3.connect(index) as db:
        row = db.execute(
            "SELECT metadata FROM contexts WHERE observation_id='earth-fixture'"
        ).fetchone()
    indexed = json.loads(row[0])
    assert indexed["land_cover"]["status"] == "unavailable"
    assert "invalid" in indexed["land_cover"]["unavailable_reason"]


def test_mola_footprint_width_accounts_for_latitude(tmp_path):
    from twinworld.discovery import read_index

    index = tmp_path / "index.sqlite"
    build_index(ROOT, index)
    _, rows = read_index(index)
    jezero = next(row for row in rows if row["observation_id"] == "mars-jezero")
    assert jezero["index_ground_width_m"] == pytest.approx(9664, abs=30)
    assert jezero["index_ground_height_m"] == pytest.approx(10187, abs=30)


def test_footprint_matching_is_rotation_invariant_and_preserves_rectangular_shape():
    from twinworld.discovery import _footprint_compatible

    reference = {"index_ground_width_m": 20_000, "index_ground_height_m": 10_000}
    rotated = {"index_ground_width_m": 10_000, "index_ground_height_m": 20_000}
    same_shape = {"index_ground_width_m": 20_500, "index_ground_height_m": 10_000}
    wrong_area = {"index_ground_width_m": 20_000, "index_ground_height_m": 11_000}
    invalid_boolean = {"index_ground_width_m": True, "index_ground_height_m": 10_000}
    assert _footprint_compatible(reference, rotated)
    assert _footprint_compatible(reference, same_shape)
    assert not _footprint_compatible(reference, wrong_area)
    assert not _footprint_compatible(reference, invalid_boolean)


def test_partial_mola_range_remains_scoring_input_with_observation_semantics():
    from twinworld.discovery import comparison_measurements

    sparse = {
        "dataset_id": "mola-meg128",
        "observed_cell_fraction": 153 / 484,
        "measurements": [{"name": "elevation_range", "value": 202, "units": "m"}],
    }
    complete = sparse | {"observed_cell_fraction": 1.0}
    assert comparison_measurements(sparse) == sparse["measurements"]
    assert comparison_measurements(complete) == sparse["measurements"]


def test_mola_range_minimum_support_threshold_is_inclusive():
    from twinworld.discovery import _support_ok

    assert _support_ok({"dataset_id": "mola-meg128", "observed_cell_fraction": 0.25})
    assert not _support_ok(
        {"dataset_id": "mola-meg128", "observed_cell_fraction": 0.249}
    )
    assert not _support_ok(
        {"dataset_id": "mola-meg128", "observed_cell_fraction": True}
    )
    assert not _support_ok(
        {"dataset_id": "mola-meg128", "observed_cell_fraction": 1.1}
    )


def test_near_equivalent_candidates_respect_score_tolerance_and_evidence_tier():
    from twinworld.discovery import _near_equivalent_candidates

    results = [
        {
            "context": {"observation_id": "a"},
            "evidence_class": "limited_evidence",
            "matched_variable_count": 1,
            "similarity_score": 0.90,
        },
        {
            "context": {"observation_id": "b"},
            "evidence_class": "limited_evidence",
            "matched_variable_count": 1,
            "similarity_score": 0.895,
        },
        {
            "context": {"observation_id": "c"},
            "evidence_class": "limited_evidence",
            "matched_variable_count": 1,
            "similarity_score": 0.88,
        },
        {
            "context": {"observation_id": "d"},
            "evidence_class": "multi_feature",
            "matched_variable_count": 4,
            "similarity_score": 0.899,
        },
    ]
    tied = _near_equivalent_candidates(results, tolerance=0.01)
    assert [item["context"]["observation_id"] for item in tied] == ["a", "b"]


def test_land_cover_filter_requires_complete_classification():
    from twinworld.discovery import _passes_land_cover

    filters = {"built_up": 0.1}
    complete = {
        "land_cover": {
            "status": "available",
            "valid_fraction": 1.0,
            "group_fractions": {"built_up": 0.05},
        }
    }
    partial = {
        "land_cover": {
            "status": "partial",
            "valid_fraction": 0.95,
            "group_fractions": {"built_up": 0.0},
        }
    }
    corrupt = {
        "land_cover": {
            "status": "available",
            "valid_fraction": True,
            "group_fractions": {"built_up": 0.0},
        }
    }
    assert _passes_land_cover(complete, filters)
    assert not _passes_land_cover(partial, filters)
    assert not _passes_land_cover(corrupt, filters)


def test_discovery_ranks_real_moon_and_sparse_mars_as_limited(tmp_path):
    from twinworld.discovery import rank
    from twinworld.scorecards import MISSION_PRESETS

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    weights = MISSION_PRESETS["landing"]["weights"]
    moon = rank(index, release, "lola_polar_moon_shackleton_rim", weights)
    assert moon["results"][0]["evidence_class"] == "multi_feature"
    sparse_index = tmp_path / "sparse-index.sqlite"
    sparse_root = _sparse_mola_earth_fixture(tmp_path / "sparse-root")
    sparse_release = build_index(sparse_root, sparse_index)["id"]
    mars = rank(sparse_index, sparse_release, "mars_aeolis_nondune-01", weights)
    assert mars["status"] == "ranked"
    assert mars["results"][0]["context"]["observation_id"] == "earth-fixture"
    assert mars["results"][0]["evidence_class"] == "limited_evidence"
    assert mars["results"][0]["matched_variable_count"] == 1
    assert mars["near_equivalent_context_ids"] == ["earth-fixture", "earth-fixture-b"]
    assert mars["target"]["observed_cell_fraction"] == pytest.approx(153 / 484)
    with pytest.raises(ValueError, match="mapping"):
        rank(sparse_index, sparse_release, "mars_aeolis_nondune-01", weights, [])
    with pytest.raises(RuntimeError):
        rank(index, "wrong-release", "mars_aeolis_nondune-01", weights)


def test_discovery_api_real_data(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from twinworld import api
    from twinworld.scorecards import MISSION_PRESETS

    sparse_root = _sparse_mola_earth_fixture(tmp_path / "api-root")
    index = tmp_path / "index.sqlite"
    build_index(sparse_root, index)
    monkeypatch.setattr(api, "DISCOVERY_INDEX", index)
    client = TestClient(api.app)
    info = client.get("/api/discovery/index").json()
    coverage = client.get("/api/discovery/coverage?body=mars").json()["contexts"]
    eligibility = {row["observation_id"]: row["eligible_for_ranking"] for row in coverage}
    assert eligibility["mars_aeolis_nondune-01"] is True
    found = client.post(
        "/api/discovery/resolve",
        json={"body": "mars", "latitude_deg": -3, "longitude_east_deg": 149.9915647},
    ).json()
    assert found["status"] == "covered"
    assert "planetocentric" in found["coordinate_frame"]
    response = client.post(
        "/api/discovery/rank",
        json={
            "index_id": info["index_id"],
            "context_id": "mars_aeolis_nondune-01",
            "weights": MISSION_PRESETS["landing"]["weights"],
        },
    )
    assert response.status_code == 200
    assert response.json()["policy_hash"] == info["policy_hash"]
    assert response.json()["weights"] == MISSION_PRESETS["landing"]["weights"]
    assert response.json()["status"] == "ranked"
    assert response.json()["results"][0]["evidence_class"] == "limited_evidence"
    assert response.json()["ranking_tie_tolerance"] == 0.01
    assert response.json()["near_equivalent_context_ids"] == [
        "earth-fixture",
        "earth-fixture-b",
    ]
    assert response.json()["applied_land_cover_filters"] == {}
    page_one = client.post(
        "/api/discovery/rank",
        json={
            "index_id": info["index_id"],
            "context_id": "mars_aeolis_nondune-01",
            "weights": MISSION_PRESETS["landing"]["weights"],
            "result_limit": 1,
        },
    ).json()
    assert page_one["total_results"] == 2
    assert page_one["result_offset"] == 0
    assert page_one["next_result_offset"] == 1
    assert len(page_one["results"]) == 1
    page_two = client.post(
        "/api/discovery/rank",
        json={
            "index_id": info["index_id"],
            "context_id": "mars_aeolis_nondune-01",
            "weights": MISSION_PRESETS["landing"]["weights"],
            "result_limit": 1,
            "result_offset": 1,
        },
    ).json()
    assert page_two["total_results"] == 2
    assert page_two["next_result_offset"] is None
    assert page_two["results"][0]["context"]["observation_id"] == "earth-fixture-b"
    filtered = client.post(
        "/api/discovery/rank",
        json={
            "index_id": info["index_id"],
            "context_id": "mars_aeolis_nondune-01",
            "weights": MISSION_PRESETS["landing"]["weights"],
            "land_cover_max_fractions": {"bare_sparse": 0.5},
        },
    ).json()
    assert filtered["status"] == "insufficient_evidence"
    assert filtered["land_cover_filter_excluded_count"] == 2
    invalid_filter = client.post(
        "/api/discovery/rank",
        json={
            "index_id": info["index_id"],
            "context_id": "mars_aeolis_nondune-01",
            "weights": MISSION_PRESETS["landing"]["weights"],
            "land_cover_max_fractions": {"unknown_class": 0.5},
        },
    )
    assert invalid_filter.status_code == 422
    assert response.json()["mission_suitability"]["status"] == "not_assessed"
    assert (
        client.post(
            "/api/discovery/resolve",
            json={"body": "moon", "latitude_deg": 0, "longitude_east_deg": 180},
        ).json()["status"]
        == "out_of_coverage"
    )


def test_overlapping_footprints_prioritize_eligible_measurements(tmp_path):
    import json
    import sqlite3

    index = tmp_path / "index.sqlite"
    build_index(ROOT, index)
    with sqlite3.connect(index) as db:
        row = db.execute(
            "SELECT id,metadata FROM contexts WHERE observation_id=?",
            ("moon_candidate_moon_mare_tranquillitatis_pit",),
        ).fetchone()
        source_id, raw = row
        invalid = json.loads(raw)
        invalid["observation_id"] = "aaa_unsupported"
        invalid["valid_pixel_fraction"] = 0.0
        db.execute(
            "INSERT INTO contexts SELECT 99999, ?, body, crs, geographic_crs, affine, width, "
            "height, ? FROM contexts WHERE id=?",
            (invalid["observation_id"], json.dumps(invalid), source_id),
        )
        db.execute("INSERT INTO bounds VALUES (99999, 99999)")
        db.execute(
            "INSERT INTO measurements SELECT 99999,ordinal,name,value,units,availability,"
            "spatial_scale_m,payload FROM measurements WHERE context_id=?",
            (source_id,),
        )
        db.execute(
            "INSERT INTO bounds_index SELECT 99999,min_lon,max_lon,min_lat,max_lat "
            "FROM bounds_index WHERE id=?",
            (source_id,),
        )
    matches = resolve(index, "moon", 8.3355, 33.222)
    assert matches[0]["observation_id"] == "moon_candidate_moon_mare_tranquillitatis_pit"
    assert any(m["observation_id"] == "aaa_unsupported" for m in matches)


def test_diversification_keeps_full_ranking(tmp_path):
    from twinworld.discovery import rank
    from twinworld.scorecards import MISSION_PRESETS

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    result = rank(
        index,
        release,
        "lola_polar_moon_shackleton_rim",
        MISSION_PRESETS["landing"]["weights"],
    )
    full = result["results"]
    shown = result["recommendations"]
    assert len(full) == result["diversified_count"] + result["suppressed_neighbours"]
    assert len(shown) == min(10, result["diversified_count"])
    assert shown[0] == full[0]
    assert [row["rank"] for row in full] == list(range(1, len(full) + 1))


def test_measurements_and_provenance_have_queryable_rows(tmp_path):
    import sqlite3

    index = tmp_path / "index.sqlite"
    build_index(ROOT, index)
    with sqlite3.connect(index) as db:
        rows = db.execute(
            "SELECT m.name,m.units,m.availability,s.product_id FROM measurements m "
            "JOIN contexts c ON c.id=m.context_id "
            "JOIN source_products s ON s.context_id=c.id AND s.role='elevation' "
            "WHERE c.observation_id=?",
            ("mars_aeolis_nondune-01",),
        ).fetchall()
        assert rows == [("elevation_range", "m", "available", rows[0][3])]
        assert "mola" in rows[0][3]
        quality = db.execute(
            "SELECT p.body,q.retained_cell_fraction,q.native_direct_fraction "
            "FROM contexts c JOIN context_places cp ON cp.context_id=c.id "
            "JOIN places p ON p.id=cp.place_id "
            "JOIN context_quality q ON q.context_id=c.id WHERE c.observation_id=?",
            ("mars_aeolis_nondune-01",),
        ).fetchone()
        assert quality[0] == "mars"
        assert quality[1] == pytest.approx(153 / 484)
        assert quality[2] is None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    ("body", "dataset", "crs", "points", "outside"),
    [
        (
            "mars",
            "mola-meg128",
            "+proj=eqc +lat_ts=0 +lon_0=180 +R=3396000 +units=m",
            [(0, 180), (0, -180), (0, 540)],
            (0, 179),
        ),
        (
            "moon",
            "lro-lola-gdr-polar-ldem-120m",
            "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +R=1737400 +units=m",
            [(-90, 0), (-90, 180), (-89.99, 270)],
            (-89, 0),
        ),
    ],
)
def test_synthetic_footprint_containment_at_seam_and_pole(
    tmp_path, body, dataset, crs, points, outside
):
    import json

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    terrain = tmp_path / "data" / "terrain"
    terrain.mkdir(parents=True)
    raster = terrain / "synthetic.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=20,
        height=20,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(-5000, 5000, 500, 500),
    ) as dst:
        dst.write(np.ones((20, 20), dtype="float32"), 1)
    metadata = {
        "observation_id": "fixture",
        "dataset_id": dataset,
        "output": "data/terrain/synthetic.tif",
        "count_raster": "data/terrain/synthetic.tif",
        "observed_cell_fraction": 1.0,
        "native_count_crop_fraction": 1.0,
        "measurements": [],
    }
    raster.with_suffix(".tif.json").write_text(json.dumps(metadata))
    index = tmp_path / "index.sqlite"
    build_index(tmp_path, index)
    for latitude, longitude in points:
        assert [m["observation_id"] for m in resolve(index, body, latitude, longitude)] == [
            "fixture"
        ]
    assert resolve(index, body, *outside) == []


def test_discovery_api_validation_and_release_errors(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from twinworld import api
    from twinworld.scorecards import MISSION_PRESETS

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    monkeypatch.setattr(api, "DISCOVERY_INDEX", index)
    client = TestClient(api.app)
    base = {
        "index_id": release,
        "context_id": "mars_aeolis_nondune-01",
        "weights": MISSION_PRESETS["landing"]["weights"],
    }
    assert client.post("/api/discovery/rank", json=base | {"index_id": "stale"}).status_code == 409
    assert (
        client.post("/api/discovery/rank", json=base | {"context_id": "missing"}).status_code == 404
    )
    assert (
        client.post(
            "/api/discovery/rank", json=base | {"weights": {"mean_slope": True}}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/discovery/rank", json=base | {"weights": {"mean_slope": 1}}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/discovery/resolve",
            json={"body": "earth", "latitude_deg": 0, "longitude_east_deg": 0},
        ).status_code
        == 422
    )
    monkeypatch.setattr(api, "DISCOVERY_INDEX", tmp_path / "absent.sqlite")
    assert client.get("/api/discovery/index").status_code == 503
    broken = tmp_path / "corrupt.sqlite"
    broken.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(api, "DISCOVERY_INDEX", broken)
    assert client.get("/api/discovery/index").status_code == 503


def test_changing_terrain_weights_changes_scores_without_rebuilding_index(tmp_path):
    from twinworld.discovery import rank

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    names = [
        "elevation_range",
        "mean_slope",
        "slope_p90",
        "median_local_relief_3x3",
        "median_roughness_3x3",
    ]
    relief = {name: float(name == "elevation_range") for name in names}
    slope = {name: float(name == "mean_slope") for name in names}
    first = rank(index, release, "lola_polar_moon_shackleton_rim", relief)
    second = rank(index, release, "lola_polar_moon_shackleton_rim", slope)
    first_scores = {
        row["context"]["observation_id"]: row["similarity_score"] for row in first["results"]
    }
    second_scores = {
        row["context"]["observation_id"]: row["similarity_score"] for row in second["results"]
    }
    assert first_scores.keys() == second_scores.keys()
    assert any(abs(first_scores[key] - second_scores[key]) > 0.01 for key in first_scores)
    assert all(row["evidence_class"] == "limited_evidence" for row in first["results"])


def test_index_identity_changes_when_raster_data_changes(tmp_path):
    import json

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    terrain = tmp_path / "data" / "terrain"
    terrain.mkdir(parents=True)
    raster = terrain / "source.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000, 10000, 500, 500),
    ) as dst:
        dst.write(np.zeros((4, 4), dtype="float32"), 1)
    raster.with_suffix(".tif.json").write_text(
        json.dumps(
            {
                "observation_id": "source",
                "dataset_id": "cop-dem-glo-30",
                "output": "data/terrain/source.tif",
            }
        )
    )
    first = build_index(tmp_path, tmp_path / "first.sqlite")
    with rasterio.open(raster, "r+") as dst:
        dst.write(np.ones((4, 4), dtype="float32"), 1)
    second = build_index(tmp_path, tmp_path / "second.sqlite")
    assert first["id"] != second["id"]


def test_nasadem_manifest_excludes_stale_contexts_and_requires_current_files(tmp_path):
    import json

    directory = tmp_path / "artifacts" / "discovery" / "nasadem"
    directory.mkdir(parents=True)
    (directory / "nasadem_stale_00_00.tif.json").write_text("not valid JSON")
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "contexts": []}))
    assert build_index(tmp_path, tmp_path / "index.sqlite")["contexts"] == 0
    manifest.write_text(json.dumps({"version": 1, "contexts": ["nasadem_missing_00_00"]}))
    with pytest.raises(ValueError, match="missing context"):
        build_index(tmp_path, tmp_path / "other.sqlite")


def test_copernicus_manifest_rejects_missing_contexts(tmp_path):
    import json

    directory = tmp_path / "artifacts" / "discovery" / "copernicus"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"version": 1, "contexts": ["candidate_earth_expanded_missing"]})
    )
    with pytest.raises(ValueError, match="Copernicus manifest references missing context"):
        build_index(tmp_path, tmp_path / "index.sqlite")


def test_footprint_compatibility_checks_both_dimensions_and_area():
    from twinworld.discovery import _footprint_compatible

    reference = {"index_ground_width_m": 10000, "index_ground_height_m": 10000}
    similar = {"index_ground_width_m": 10200, "index_ground_height_m": 10200}
    too_large = {"index_ground_width_m": 10400, "index_ground_height_m": 10400}
    invalid = {"index_ground_width_m": float("nan"), "index_ground_height_m": 10000}
    assert _footprint_compatible(reference, similar)
    assert not _footprint_compatible(reference, too_large)
    assert not _footprint_compatible(reference, invalid)


def test_discovery_runtime_never_reads_rasters_or_fetches_sources(tmp_path, monkeypatch):
    import rasterio
    import requests

    from twinworld.discovery import rank
    from twinworld.scorecards import MISSION_PRESETS

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]

    def forbidden(*args, **kwargs):
        raise AssertionError("runtime attempted scientific ingestion")

    monkeypatch.setattr(rasterio, "open", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    matches = resolve(index, "mars", -3, 149.9915647)
    assert matches
    result = rank(
        index,
        release,
        "lola_polar_moon_shackleton_rim",
        MISSION_PRESETS["landing"]["weights"],
    )
    assert result["status"] == "ranked"


def test_mismatched_observation_count_raster_is_excluded(tmp_path):
    import shutil

    import numpy as np
    import rasterio

    terrain = tmp_path / "data" / "terrain"
    terrain.mkdir(parents=True)
    source_dir = ROOT / "data" / "terrain"
    base = "mola-meg128-mars_aeolis_nondune-01"
    for name in (f"{base}.tif", f"{base}-counts.tif", f"{base}.tif.json"):
        shutil.copy2(source_dir / name, terrain / name)
    with rasterio.open(terrain / f"{base}-counts.tif", "r+") as dst:
        dst.write(np.zeros((dst.height, dst.width), dtype="uint8"), 1)
    report = build_index(tmp_path, tmp_path / "index.sqlite")
    assert report["contexts"] == 0
    assert any("count support mismatch" in item for item in report["skipped"])


def test_mola_elevation_mask_must_match_count_grid(tmp_path):
    import shutil

    import numpy as np
    import rasterio

    terrain = tmp_path / "data" / "terrain"
    terrain.mkdir(parents=True)
    source_dir = ROOT / "data" / "terrain"
    base = "mola-meg128-mars_aeolis_nondune-01"
    for name in (f"{base}.tif", f"{base}-counts.tif", f"{base}.tif.json"):
        shutil.copy2(source_dir / name, terrain / name)
    with rasterio.open(terrain / f"{base}.tif", "r+") as dst:
        values = dst.read(1)
        with rasterio.open(terrain / f"{base}-counts.tif") as counts:
            count_values = counts.read(1)
        row, column = np.argwhere(count_values == 0)[0]
        values[row, column] = 1  # count grid has no observation in this cell
        dst.write(values, 1)
    report = build_index(tmp_path, tmp_path / "index.sqlite")
    assert report["contexts"] == 0
    assert any("elevation/count grid mismatch" in item for item in report["skipped"])


def test_multifeature_requires_sufficient_retained_output_support(tmp_path):
    import json
    import sqlite3

    from twinworld.discovery import rank
    from twinworld.scorecards import MISSION_PRESETS

    index = tmp_path / "index.sqlite"
    release = build_index(ROOT, index)["id"]
    with sqlite3.connect(index) as db:
        row = db.execute(
            "SELECT id, metadata FROM contexts WHERE observation_id=?",
            ("lola_polar_moon_shackleton_rim",),
        ).fetchone()
        metadata = json.loads(row[1])
        metadata["observed_cell_fraction"] = 0.5
        metadata["native_count_crop_fraction"] = 1.0
        db.execute("UPDATE contexts SET metadata=? WHERE id=?", (json.dumps(metadata), row[0]))
    result = rank(
        index, release, "lola_polar_moon_shackleton_rim", MISSION_PRESETS["landing"]["weights"]
    )
    assert result["results"]
    assert all(r["evidence_class"] == "limited_evidence" for r in result["results"])
