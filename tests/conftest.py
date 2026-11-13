"""Shared test fixtures that keep tests independent of downloaded artifacts."""

import json

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def deterministic_api_embeddings(tmp_path, monkeypatch):
    """Supply a tiny synthetic embedding matrix instead of local model output."""
    from twinworld import api

    load = api._load
    records = api.read_jsonl(api.MANIFEST)
    artifact = tmp_path / "embeddings_dinov2.npy"
    np.save(artifact, np.ones((len(records), 2), dtype=np.float32), allow_pickle=False)
    artifact.with_suffix(".json").write_text(
        json.dumps(
            {
                "image_ids": [record.image_id for record in records],
                "embedding_dimension": 2,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "EMBEDDINGS", artifact)
    load.cache_clear()
    yield
    load.cache_clear()
