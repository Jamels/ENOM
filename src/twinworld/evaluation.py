"""Metrics with explicit denominators and review-status handling."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if len(ranked_ids) < k:
        raise ValueError("ranked result list must contain at least k candidates")
    return sum(item in relevant_ids for item in ranked_ids[:k]) / k


def average_precision(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    """AP is defined only for complete relevance judgements of the gallery."""
    if not relevant_ids:
        raise ValueError("average precision requires at least one known relevant item")
    hits = 0
    precision_sum = 0.0
    for rank, item_id in enumerate(ranked_ids, start=1):
        if item_id in relevant_ids:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / len(relevant_ids)


def reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    for rank, item_id in enumerate(ranked_ids, start=1):
        if item_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def random_precision_expectation(relevant_count: int, gallery_size: int, k: int) -> float:
    if not 0 <= relevant_count <= gallery_size or not 0 < k <= gallery_size:
        raise ValueError("invalid relevant_count, gallery_size, or k")
    return relevant_count / gallery_size


def random_ranking(candidate_ids: Sequence[str], *, seed: int) -> list[str]:
    """Return a reproducible random ordering for a fixed candidate gallery."""
    order = np.random.default_rng(seed).permutation(len(candidate_ids))
    return [candidate_ids[int(index)] for index in order]
