"""Geographic holdout splitting with explicit group-leakage checks."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.model_selection import GroupShuffleSplit

from twinworld.records import PatchRecord


@dataclass(frozen=True, slots=True)
class Split:
    """Record indices and group identities for a geographic holdout split."""

    development_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    development_groups: tuple[str, ...]
    test_groups: tuple[str, ...]


def geographic_holdout(records: list[PatchRecord], *, test_fraction: float, seed: int) -> Split:
    """Split by geographic_group; every observation ID must belong to one group."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    if len(records) < 2:
        raise ValueError("at least two records are required")
    source_groups: dict[tuple[str, str], str] = {}
    for record in records:
        source_key = (record.body, record.source_id)
        prior = source_groups.setdefault(source_key, record.geographic_group)
        if prior != record.geographic_group:
            raise ValueError(
                f"source observation {record.source_id} assigned to multiple geographic groups"
            )
    groups = [f"{record.body}:{record.geographic_group}" for record in records]
    if len(set(groups)) < 2:
        raise ValueError("at least two independent geographic groups are required")
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_fraction, random_state=seed)
    development, test = next(splitter.split(records, groups=groups))
    development_groups = tuple(sorted({groups[int(index)] for index in development}))
    test_groups = tuple(sorted({groups[int(index)] for index in test}))
    if set(development_groups) & set(test_groups):
        raise RuntimeError("geographic split leaked groups")
    return Split(
        tuple(int(index) for index in development),
        tuple(int(index) for index in test),
        development_groups,
        test_groups,
    )
