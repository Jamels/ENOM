from twinworld.annotations import merge_review_row


def test_annotation_regeneration_preserves_human_review_fields():
    previous = {
        "reviewed_label": "linear_dune",
        "review_status": "reviewed",
        "ambiguity_notes": "mixed bedrock ridges at edge",
        "source_reference": "https://example.invalid/alternate-evidence",
        "annotator_id": "reviewer-1",
        "reviewed_at": "2026-11-05T10:00:00Z",
        "review_rationale": "parallel sand ridges visible",
    }
    row = merge_review_row(
        "mars-1",
        "other_dune",
        "https://example.invalid/source",
        "confirm morphology",
        previous,
    )

    assert row["proposed_label"] == "other_dune"
    assert row["reviewed_label"] == "linear_dune"
    assert row["review_status"] == "reviewed"
    assert row["review_rationale"] == "parallel sand ridges visible"
    assert row["source_reference"] == "https://example.invalid/alternate-evidence"


def test_annotation_defaults_keep_unreviewed_classification_provisional():
    row = merge_review_row(
        "earth-1", "barchan_crescent_dune", "https://example.invalid/source", "", {}
    )

    assert row["proposed_label"] == "barchan_crescent_dune"
    assert row["reviewed_label"] == ""
    assert row["review_status"] == "unreviewed"
