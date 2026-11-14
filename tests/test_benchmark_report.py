from typing import cast

from scripts.pilot_benchmark_report import render_report
from twinworld.records import Body, Landform, PatchRecord


def _record(image_id: str, body: str, label: Landform, provider: str) -> PatchRecord:
    return PatchRecord(
        image_id=image_id,
        body=cast(Body, body),
        path=f"{image_id}.tif",
        source_id=f"source-{image_id}",
        provider=provider,
        source_url="https://example.invalid/source",
        latitude=0.0,
        longitude=0.0,
        native_gsd_m=10.0,
        width_m=2000.0,
        height_m=2000.0,
        acquired_at=None,
        crs="TEST",
        label=label,
        label_status="unknown",
        geographic_group=f"group-{image_id}",
        checksum_sha256="0" * 64,
        processing={},
    )


def test_report_renders_prepared_previews_and_rankings():
    records = [
        _record("earth-1", "earth", "barchan_crescent_dune", "Earth & provider"),
        _record("mars-1", "mars", "linear_dune", "Mars provider"),
    ]
    metrics = {
        key: 0.5
        for key in (
            "earth_to_mars_p1",
            "earth_to_mars_p5",
            "mars_to_earth_p1",
            "mars_to_earth_p5",
            "macro_p1",
            "macro_p5",
        )
    }
    results = [
        {
            "method": "DINOv2",
            "metrics": metrics,
            "rankings": {
                "earth-1": [{"image_id": "mars-1", "score": 0.9}],
                "mars-1": [{"image_id": "earth-1", "score": 0.9}],
            },
        }
    ]

    report = render_report(
        records,
        {record.image_id: record.label for record in records},
        results,
        "provisional proposed labels",
        {"elapsed_seconds": 1.0, "images_per_second": 2.0},
        {"classical_seconds": 0.5, "classical_cache_hit": False, "retrieval_seconds": 0.1},
        {
            "measured_count": 1,
            "requested_count": 1,
            "mean_seconds": 2.0,
            "median_seconds": 2.0,
            "total_seconds": 2.0,
        },
        {"earth-1": "data:image/png;base64,earth", "mars-1": "data:image/png;base64,mars"},
    )

    assert "2 images · 1 Earth · 1 Mars" in report
    assert "Earth &amp; provider" in report
    assert "data:image/png;base64,earth" in report
    assert "cosine" in report
    assert "Category disagreement" in report
