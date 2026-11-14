from __future__ import annotations

import pytest

from twinworld.meda import summarize_product, validate_sol_rows


def test_meda_summary_excludes_fill_values_empty_cells_and_bad_rover_flags():
    table = """LMST,SPEED,SPEED_UNC,ROVER_STILL
00100M01:00:00,1.0,0.1,1
00100M02:00:00,999999999,,1
00100M03:00:00,9.0,0.5,0
00100M04:00:00,,0.2,1
00100M05:00:00,3.0,0.3,1
"""
    assert validate_sol_rows(table, 100) == 5
    summary = summarize_product(
        table,
        sensor="WS",
        value_column="SPEED",
        value_name="horizontal wind speed",
        units="m/s",
        uncertainty_column="SPEED_UNC",
        required_flags={"ROVER_STILL": "1"},
    )
    assert summary["value"] == pytest.approx(2.0)
    assert summary["sample_count"] == 2
    assert summary["source_row_count"] == 5
    assert summary["quality_filtered_row_count"] == 1
    assert summary["invalid_value_count"] == 2
    assert summary["uncertainty"]["value"] == pytest.approx(0.2)


def test_meda_rejects_a_csv_from_the_wrong_sol():
    table = "LMST,SPEED\n00101M01:00:00,1.0\n"
    with pytest.raises(ValueError, match="outside LMST sol 100"):
        validate_sol_rows(table, 100)
