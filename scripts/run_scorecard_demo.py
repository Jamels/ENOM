"""Reproduce the default NASA LOLA–Copernicus scorecard example as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from twinworld.api import ScorecardRequest, rank_scorecard

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/moon-earth-scorecard-demo.json",
        help="JSON output path; use '-' to print to stdout",
    )
    args = parser.parse_args()
    response = rank_scorecard(
        ScorecardRequest(
            site_id="moon_mare_tranquillitatis_01",
            mission_objective="landing",
            weights={
                "mean_slope": 0.35,
                "slope_p90": 0.30,
                "median_local_relief_3x3": 0.20,
                "median_roughness_3x3": 0.15,
            },
            limit=20,
        )
    )
    rendered = json.dumps(response, indent=2, ensure_ascii=False) + "\n"
    if str(args.output) == "-":
        print(rendered, end="")
        return
    destination = args.output if args.output.is_absolute() else ROOT / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
