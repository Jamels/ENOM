"""Report source-stratified discovery rankings without claiming DEM calibration.

Run after building the local scientific index. Same nominal analysis posting
does not remove source resolution, surface representation, or datum differences.
This report separates source products and checks whether co-centred observations
exist for a future paired comparison; it does not estimate a correction from
unpaired landscapes.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from twinworld.discovery import _footprint_compatible, rank, read_index
from twinworld.scorecards import MISSION_PRESETS


def assess(index: Path, context_id: str) -> dict[str, Any]:
    release, contexts = read_index(index)
    ranking = rank(index, release, context_id, MISSION_PRESETS["landing"]["weights"])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in ranking["results"]:
        context = result["context"]
        groups[context["dataset_id"]].append(
            {
                "context_id": context["observation_id"],
                "global_rank": result["rank"],
                "score": result["similarity_score"],
                "evidence_class": result["evidence_class"],
                "matched_variable_count": result["matched_variable_count"],
            }
        )
    # Matching reported centres is a strict prerequisite, not proof that source
    # observations have identical support. Do not infer pairs from nearby sites.
    centers: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for context in contexts:
        if context["index_body"] == "earth":
            center = context["index_center"]
            centers[(center["latitude_deg"], center["longitude_east_deg"])].append(context)
    pairs = []
    for rows in centers.values():
        for position, first in enumerate(rows):
            for second in rows[position + 1 :]:
                if first["dataset_id"] != second["dataset_id"] and _footprint_compatible(
                    first, second
                ):
                    pairs.append([first["observation_id"], second["observation_id"]])
    return {
        "index_id": release,
        "target_context_id": context_id,
        "status": ranking["status"],
        "source_strata": {
            source: {
                "eligible_count": len(results),
                "top_results": results[:5],
                "score_minimum": min(row["score"] for row in results),
                "score_maximum": max(row["score"] for row in results),
            }
            for source, results in sorted(groups.items())
        },
        "co_centred_compatible_footprint_pairs": pairs,
        "bias_calibration": "not_established",
        "interpretation": (
            "These are source-restricted alternatives from the same exact ranking. "
            "Differences combine landscape sampling and DEM source effects. They "
            "cannot isolate source bias or validate cross-product equivalence. "
            "Co-centred pairs, if present, still need native support and datum review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("artifacts/discovery/index.sqlite"))
    parser.add_argument("--context-id", default="mars_aeolis_nondune-01")
    args = parser.parse_args()
    print(json.dumps(assess(args.index, args.context_id), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
