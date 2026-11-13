"""Annotation CSV row defaults and safe preservation of human review work."""

from __future__ import annotations

from collections.abc import Mapping


def merge_review_row(
    image_id: str,
    proposed_label: str,
    source_reference: str,
    ambiguity_notes: str,
    previous: Mapping[str, str],
) -> dict[str, str]:
    """Update provenance while preserving any annotation already entered."""
    return {
        "image_id": image_id,
        "proposed_label": proposed_label,
        "reviewed_label": previous.get("reviewed_label", ""),
        "review_status": previous.get("review_status") or "unreviewed",
        "ambiguity_notes": previous.get("ambiguity_notes") or ambiguity_notes,
        "source_reference": previous.get("source_reference") or source_reference,
        "annotator_id": previous.get("annotator_id", ""),
        "reviewed_at": previous.get("reviewed_at", ""),
        "review_rationale": previous.get("review_rationale", ""),
    }
