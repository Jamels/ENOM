"""Shared test fixtures that keep tests independent of downloaded artifacts."""

import json

import numpy as np
import pytest
import yaml


@pytest.fixture(autouse=True)
def deterministic_api_embeddings(tmp_path, monkeypatch):
    """Supply a tiny synthetic embedding matrix instead of local model output."""
    from twinworld import api

    load = api._load
    records = api.read_jsonl(api.MANIFEST)
    config = yaml.safe_load(api.MODEL_CONFIG.read_text(encoding="utf-8"))
    profile = next(
        model
        for model in config["models"].values()
        if model.get("active_pilot_index")
    )
    preprocessing_id = config["preprocessing"]["id"]
    artifact = tmp_path / "embeddings_dinov2.npy"
    np.save(
        artifact,
        np.ones((len(records), profile["embedding_dimension"]), dtype=np.float32),
        allow_pickle=False,
    )
    artifact.with_suffix(".json").write_text(
        json.dumps(
            {
                "image_ids": [record.image_id for record in records],
                "model_id": profile["model_id"],
                "revision": profile["revision"],
                "preprocessing_id": preprocessing_id,
                "embedding_space_id": (
                    f"{profile['model_id']}@{profile['revision']}:{preprocessing_id}"
                ),
                "embedding_dimension": profile["embedding_dimension"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "EMBEDDINGS", artifact)
    load.cache_clear()
    yield
    load.cache_clear()
