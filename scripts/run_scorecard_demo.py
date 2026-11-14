"""Reproduce a default Moon- or Mars-to-Earth scorecard example as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from twinworld.api import ScorecardRequest, rank_scorecard
from twinworld.scorecards import MISSION_PRESETS

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site",
        default="moon_mare_tranquillitatis_01",
        help="NASA scorecard observation ID (for example a MOLA Mars context)",
    )
    parser.add_argument("--objective", choices=MISSION_PRESETS, default="landing")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON output path; use '-' to print to stdout",
    )
    args = parser.parse_args()
    default_name = (
        "mars-earth-scorecard-demo.json"
        if args.site.startswith("mars")
        else "moon-earth-scorecard-demo.json"
    )
    output = args.output or ROOT / "reports" / default_name
    response = rank_scorecard(
        ScorecardRequest(
            site_id=args.site,
            mission_objective=args.objective,
            weights=MISSION_PRESETS[args.objective]["weights"],
            limit=20,
        )
    )
    rendered = json.dumps(response, indent=2, ensure_ascii=False) + "\n"
    if str(output) == "-":
        print(rendered, end="")
        return
    destination = output if output.is_absolute() else ROOT / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
