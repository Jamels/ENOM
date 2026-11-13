"""Typed patch records and JSONL manifest validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Body = Literal["earth", "mars", "moon"]
LabelStatus = Literal["verified", "tentative", "unknown"]
Landform = Literal[
    "barchan_crescent_dune",
    "linear_dune",
    "other_dune",
    "rocky_ridge_layered",
    "other_non_dune",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class PatchRecord:
    image_id: str
    body: Body
    path: str
    source_id: str
    provider: str
    source_url: str
    latitude: float
    longitude: float
    native_gsd_m: float
    width_m: float
    height_m: float
    acquired_at: str | None
    crs: str
    label: Landform
    label_status: LabelStatus
    geographic_group: str
    checksum_sha256: str
    processing: dict[str, str]

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> PatchRecord:
        return cls(**value)  # type: ignore[arg-type]

    def validate(self, root: Path, *, check_file: bool = True) -> list[str]:
        errors: list[str] = []
        if not self.image_id.strip():
            errors.append("image_id is empty")
        if self.body not in ("earth", "mars", "moon"):
            errors.append(f"invalid body: {self.body}")
        if not -90.0 <= self.latitude <= 90.0:
            errors.append("latitude is outside [-90, 90]")
        if self.body == "earth" and not -180.0 <= self.longitude < 180.0:
            errors.append("Earth longitude must be in [-180, 180)")
        if self.body == "mars" and not -180.0 <= self.longitude < 360.0:
            errors.append("Mars longitude must be in [-180, 360)")
        if self.body == "moon" and not 0.0 <= self.longitude < 360.0:
            errors.append("Moon east longitude must be in [0, 360)")
        for name in ("native_gsd_m", "width_m", "height_m"):
            if getattr(self, name) <= 0:
                errors.append(f"{name} must be positive")
        for name in ("source_id", "provider", "source_url", "crs", "geographic_group"):
            if not getattr(self, name).strip():
                errors.append(f"{name} is empty")
        if self.label_status not in ("verified", "tentative", "unknown"):
            errors.append(f"invalid label_status: {self.label_status}")
        if self.label_status == "unknown" and self.label != "unknown":
            errors.append("unknown label_status requires label='unknown'")
        if check_file and not (root / self.path).is_file():
            errors.append(f"patch file does not exist: {self.path}")
        return errors


def read_jsonl(path: Path) -> list[PatchRecord]:
    records: list[PatchRecord] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                records.append(PatchRecord.from_dict(value))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"invalid manifest row at {path}:{line_number}: {exc}") from exc
    return records


def write_jsonl(path: Path, records: list[PatchRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def validate_records(
    records: list[PatchRecord], root: Path, *, check_file: bool = True
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.image_id in seen:
            errors.append(f"duplicate image_id: {record.image_id}")
        seen.add(record.image_id)
        errors.extend(
            f"{record.image_id}: {error}" for error in record.validate(root, check_file=check_file)
        )
    return errors
