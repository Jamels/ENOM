"""Exact cross-planet nearest-neighbour retrieval."""

from __future__ import annotations

import numpy as np

from twinworld.records import PatchRecord


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise ValueError("vectors must be a finite 2D matrix")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("zero-length feature vector")
    return matrix / norms


def search(
    vectors: np.ndarray,
    records: list[PatchRecord],
    query_index: int,
    *,
    top_k: int = 5,
    class_filter: str | None = None,
    exclude_groups: set[str] | None = None,
) -> list[tuple[int, float]]:
    if len(vectors) != len(records):
        raise ValueError("vector order/count must exactly match records")
    if not 0 <= query_index < len(records):
        raise IndexError("query_index outside records")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    matrix = normalize_rows(vectors)
    query = records[query_index]
    candidates = [
        i
        for i, record in enumerate(records)
        if record.body != query.body
        and i != query_index
        and (class_filter is None or record.label == class_filter)
        and (exclude_groups is None or record.geographic_group not in exclude_groups)
    ]
    scores = matrix[candidates] @ matrix[query_index]
    order = np.argsort(-scores, kind="stable")[:top_k]
    return [(candidates[int(i)], float(scores[int(i)])) for i in order]
