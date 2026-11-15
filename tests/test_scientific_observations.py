import json

from twinworld.scientific_observations import DIMENSION_IDS, dimension_inputs


def test_local_adapter_links_exact_place_and_preserves_observation_provenance(tmp_path):
    env = tmp_path / "data/environment"
    env.mkdir(parents=True)
    (env / "climate.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "observation_id": "earth-one:era5",
                        "place_id": "earth-one",
                        "dataset_id": "era5-earth-candidate-climatology",
                        "source_url": "https://example.test/era5",
                        "measurements": [
                            {
                                "name": "ERA5 monthly mean 10 m wind speed",
                                "value": 3.1,
                                "units": "m/s",
                                "availability": "available",
                                "spatial_scale_m": 25000,
                            }
                        ],
                    },
                    {
                        "observation_id": "earth-two:era5",
                        "place_id": "earth-two",
                        "dataset_id": "era5-earth-candidate-climatology",
                        "measurements": [
                            {
                                "name": "ERA5 monthly mean 10 m wind speed",
                                "value": 99,
                                "units": "m/s",
                            }
                        ],
                    },
                ]
            }
        )
    )

    result = dimension_inputs(tmp_path, "earth-one")

    assert tuple(result) == DIMENSION_IDS
    assert len(result["dust_processes"]) == 1
    feature = result["dust_processes"][0]
    assert (feature["observation_id"], feature["value"], feature["units"]) == (
        "earth-one:era5",
        3.1,
        "m/s",
    )
    assert feature["spatial_scale_m"] == 25000
    assert feature["source_url"] == "https://example.test/era5"
    assert all(not result[key] for key in set(DIMENSION_IDS) - {"dust_processes"})


def test_adapter_keeps_geology_as_categorical_evidence_and_not_numeric_measurement(tmp_path):
    geology = tmp_path / "data/geology"
    geology.mkdir(parents=True)
    (geology / "mars.json").write_text(
        json.dumps(
            {
                "observation_id": "mars-one",
                "place_id": "mars-one",
                "dataset_id": "usgs-sim1083",
                "source_url": "https://doi.org/10.5066/P9UGAC18",
                "classification_status": "mapped",
                "map_unit_code": "Hpr",
                "map_unit_name": "Example unit",
                "map_unit_interpretation": "Mapped interpretation",
                "nominal_cartographic_scale": "1:25,000,000",
            }
        )
    )

    row = dimension_inputs(tmp_path, "mars-one")["geology_materials"][0]

    assert row["value"] is None
    assert row["availability"] == "mapped"
    assert row["map_unit_code"] == "Hpr"
    assert row["evidence_kind"] == "interpreted_map_unit"


def test_real_mare_pit_and_mojave_map_labels_have_explicit_coarse_group_overlap():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    moon = dimension_inputs(root, "moon-mare-tranquillitatis-pit")["geology_materials"][0]
    earth = dimension_inputs(root, "earth-mojave-lava-tube")["geology_materials"][0]

    assert moon["material_groups"] == ["mafic_volcanic"]
    assert earth["material_groups"] == ["mafic_volcanic"]
    assert moon["value"] is earth["value"] is None
    assert moon["material_crosswalk_version"] == earth["material_crosswalk_version"]
    assert (
        moon["nominal_cartographic_scale"] == "1:5,000,000 global map; regional-unit generalization"
    )
    assert earth["nominal_cartographic_scale"] == "1:750,000"


def test_adapter_preserves_missing_measurement_as_unavailable(tmp_path):
    observations = [
        {
            "place_id": "moon-one",
            "id": "moon-one:diviner",
            "dataset_id": "lro-diviner-south-polar-prp",
            "source_url": "https://pds.nasa.gov/example",
            "measurements": [
                {
                    "name": "modeled ice stability depth",
                    "value": None,
                    "units": "m",
                    "availability": "not_reported",
                }
            ],
        }
    ]

    row = dimension_inputs(tmp_path, "moon-one", observations=observations)["thermal_illumination"][
        0
    ]

    assert row["value"] is None
    assert row["availability"] == "not_reported"
    assert row["observation_id"] == "moon-one:diviner"
