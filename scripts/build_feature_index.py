"""Build the offline discovery context index from local scientific rasters."""

import argparse
import fcntl
import json
from pathlib import Path
from time import perf_counter

from twinworld.feature_index import build_index

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/discovery/index.sqlite")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.output.with_suffix(args.output.suffix + ".build.lock")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit(f"an index build is already active for {args.output}") from error
        started = perf_counter()
        result = build_index(ROOT, args.output)
        result["elapsed_seconds"] = round(perf_counter() - started, 3)
        print(json.dumps(result, indent=2))
