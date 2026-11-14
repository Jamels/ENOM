from dataclasses import replace
from pathlib import Path

import pytest

from twinworld.records import read_jsonl, validate_records


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["native_gsd_m", "width_m", "height_m"])
def test_manifest_physical_dimensions_must_be_finite(field, invalid_value):
    record = read_jsonl(Path("data/manifests/pilot-100.jsonl"))[0]
    invalid_record = replace(record, **{field: invalid_value})

    errors = validate_records([invalid_record], Path("."), check_file=False)

    assert any(f"{field} must be finite and positive" in error for error in errors)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["latitude", "longitude"])
def test_manifest_coordinates_must_be_finite(field, invalid_value):
    record = read_jsonl(Path("data/manifests/pilot-100.jsonl"))[0]
    invalid_record = replace(record, **{field: invalid_value})

    errors = validate_records([invalid_record], Path("."), check_file=False)

    coordinate_error = "latitude is outside" if field == "latitude" else "longitude must be"
    assert any(coordinate_error in error for error in errors)
