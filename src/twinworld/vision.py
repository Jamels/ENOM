"""Portable DINOv2 embedding generation with identity-checked model caches."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from twinworld.features import read_grayscale, select_device
from twinworld.records import PatchRecord


def file_sha256(path: Path) -> str:
    """Hash a source image incrementally so large rasters stay memory bounded."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def embedding_cache_stem(model_id: str) -> str:
    """Return a model-specific artifact name while preserving the pilot small-model path."""
    model_slug = model_id.rsplit("/", 1)[-1].lower().replace("-", "_")
    return "embeddings_dinov2" if model_slug == "dinov2_small" else f"embeddings_{model_slug}"


def _valid_embedding_matrix(
    matrix: np.ndarray, *, row_count: int, embedding_dimension: object
) -> bool:
    """Check cached vectors against the matrix shape and value contract."""
    if (
        isinstance(embedding_dimension, bool)
        or not isinstance(embedding_dimension, int)
        or embedding_dimension < 1
        or matrix.ndim != 2
        or matrix.shape != (row_count, embedding_dimension)
        or not np.isfinite(matrix).all()
    ):
        return False
    return bool(np.all(np.linalg.norm(matrix, axis=1) > 0))


def embed_dinov2(
    records: list[PatchRecord],
    root: Path,
    output_dir: Path,
    *,
    model_id: str,
    revision: str,
    device_preference: str = "auto",
    batch_size: int = 16,
) -> tuple[np.ndarray, dict[str, object]]:
    """Embed grayscale patches with the pinned DINOv2 model and cache their identity.

    Each source is percentile-stretched (2nd–98th), resized to 224×224, copied
    into three RGB channels, and passed through the model's image processor.
    The final-layer CLS token is the global image descriptor; rows are L2
    normalized so their dot product is cosine similarity. Cache reuse requires
    the same ordered IDs, source checksums, model revision, and preprocessing
    ID. Similarity is a visual retrieval signal, not a geological measurement.

    DINOv2's self-supervised visual features follow Oquab et al.,
    *DINOv2: Learning Robust Visual Features without Supervision*
    (https://arxiv.org/abs/2304.07193).
    """
    if not revision:
        raise ValueError("an immutable model revision is required")
    if not records:
        raise ValueError("cannot embed an empty dataset")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    import torch
    from transformers import AutoImageProcessor, AutoModel

    ids = [record.image_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("image IDs must be unique")
    checksums = [file_sha256(root / record.path) for record in records]
    preprocessing_id = "grayscale-p02-p98-rgb224-maskfill-v2"
    # Keep the original small-model filenames so existing 384-D indexes remain usable.
    # Other model IDs receive separate files and can never overwrite that index.
    stem = embedding_cache_stem(model_id)
    cache_meta_path = output_dir / f"{stem}.json"
    cache_array_path = output_dir / f"{stem}.npy"
    if cache_meta_path.is_file() and cache_array_path.is_file():
        cached = json.loads(cache_meta_path.read_text(encoding="utf-8"))
        if (
            cached.get("image_ids") == ids
            and cached.get("source_sha256") == checksums
            and cached.get("model_id") == model_id
            and cached.get("revision") == revision
            and cached.get("preprocessing_id") == preprocessing_id
        ):
            cached_matrix = np.load(cache_array_path, allow_pickle=False)
            if _valid_embedding_matrix(
                cached_matrix,
                row_count=len(records),
                embedding_dimension=cached.get("embedding_dimension"),
            ):
                return cached_matrix, cached

    device = select_device(device_preference)  # type: ignore[arg-type]
    processor = AutoImageProcessor.from_pretrained(model_id, revision=revision)
    model = AutoModel.from_pretrained(model_id, revision=revision).to(device).eval()
    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings: list[np.ndarray] = []
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(records), batch_size):
            images = []
            for record in records[start : start + batch_size]:
                gray = read_grayscale(root / record.path, size=224)
                rgb = np.repeat(np.rint(gray[..., None] * 255).astype(np.uint8), 3, axis=-1)
                images.append(rgb)
            inputs = processor(images=images, return_tensors="pt")
            inputs = {key: value.to(device) for key, value in inputs.items()}
            result = model(**inputs).last_hidden_state[:, 0]
            embeddings.extend(result.float().cpu().numpy())
    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(records) or not np.isfinite(matrix).all():
        raise RuntimeError("DINOv2 produced an invalid embedding matrix")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise RuntimeError("DINOv2 produced a zero-length embedding vector")
    matrix /= norms
    elapsed = time.perf_counter() - started
    metadata: dict[str, object] = {
        "image_ids": ids,
        "source_sha256": checksums,
        "model_id": model_id,
        "model_family": "dinov2",
        "revision": revision,
        "embedding_space_id": f"{model_id}@{revision}:{preprocessing_id}",
        "preprocessing_id": preprocessing_id,
        "device": device,
        "batch_size": batch_size,
        "embedding_dimension": int(matrix.shape[1]) if matrix.ndim == 2 else 0,
        "elapsed_seconds": elapsed,
        "images_per_second": len(records) / elapsed if elapsed else None,
        "torch_version": torch.__version__,
        "transformers_version": __import__("transformers").__version__,
    }
    if device == "cuda":
        metadata["gpu_name"] = torch.cuda.get_device_name(0)
        metadata["peak_memory_bytes"] = int(torch.cuda.max_memory_allocated(0))
    np.save(cache_array_path, matrix, allow_pickle=False)
    cache_meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return matrix, metadata
