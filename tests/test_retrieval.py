from dataclasses import replace

import numpy as np
import pytest

from twinworld.evaluation import (
    average_precision,
    precision_at_k,
    random_precision_expectation,
    random_ranking,
)
from twinworld.records import PatchRecord
from twinworld.retrieval import search
from twinworld.splits import geographic_holdout


def record(image_id: str, body: str, group: str = "g") -> PatchRecord:
    return PatchRecord(
        image_id=image_id,
        body=body,  # type: ignore[arg-type]
        path=f"{image_id}.tif",
        source_id=f"source-{image_id}",
        provider="test fixture",
        source_url="https://example.invalid/source",
        latitude=0,
        longitude=0,
        native_gsd_m=10,
        width_m=2000,
        height_m=2000,
        acquired_at=None,
        crs="TEST",
        label="unknown",
        label_status="unknown",
        geographic_group=group,
        checksum_sha256="test",
        processing={"fixture": "unit test only"},
    )


def test_search_returns_cross_planet_cosine_neighbours():
    records = [record("e", "earth"), record("m1", "mars"), record("m2", "mars")]
    vectors = np.array([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)
    results = search(vectors, records, 0, top_k=2)
    assert [index for index, _ in results] == [1, 2]
    assert results[0][1] > results[1][1]


def test_search_rejects_misaligned_metadata():
    with pytest.raises(ValueError, match="order/count"):
        search(np.ones((1, 2)), [record("e", "earth"), record("m", "mars")], 0)


def test_search_can_exclude_geographic_group():
    records = [record("e", "earth"), record("m1", "mars", "same"), record("m2", "mars", "other")]
    results = search(np.array([[1, 0], [1, 0], [0.8, 0.2]]), records, 0, exclude_groups={"same"})
    assert [i for i, _ in results] == [2]


def test_metrics_and_random_expectation():
    ranked = ["a", "b", "c", "d", "e"]
    relevant = {"b", "d"}
    assert precision_at_k(ranked, relevant, 5) == pytest.approx(0.4)
    assert average_precision(ranked, relevant) == pytest.approx((1 / 2 + 2 / 4) / 2)
    assert random_precision_expectation(2, 10, 5) == pytest.approx(0.2)
    assert random_ranking(ranked, seed=7) == random_ranking(ranked, seed=7)


def test_geographic_holdout_keeps_groups_disjoint():
    records = [
        record("e1", "earth", "a"),
        record("e2", "earth", "a"),
        record("e3", "earth", "b"),
        record("e4", "earth", "c"),
    ]
    split = geographic_holdout(records, test_fraction=0.34, seed=9)
    assert not set(split.development_groups) & set(split.test_groups)
    assert len(split.development_indices) + len(split.test_indices) == 4


def test_geographic_holdout_rejects_split_source_assignment():
    records = [
        record("e1", "earth", "a"),
        record("e2", "earth", "b"),
        record("m1", "mars", "c"),
    ]
    records[1] = replace(records[1], source_id=records[0].source_id)
    with pytest.raises(ValueError, match="multiple geographic groups"):
        geographic_holdout(records, test_fraction=0.34, seed=9)
