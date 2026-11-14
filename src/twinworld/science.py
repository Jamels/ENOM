"""Shared measurement, provenance, and evidence types used across the API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Availability(StrEnum):
    """States that distinguish missing evidence from a negative measurement."""

    AVAILABLE = "available"
    NOT_OBSERVED = "not_observed"
    OUTSIDE_COVERAGE = "outside_coverage"
    PROCESSING_FAILED = "processing_failed"
    INAPPLICABLE = "inapplicable"
    UNCERTAIN = "uncertain"


class Uncertainty(BaseModel):
    """Uncertainty value and human-readable context for a measurement."""

    value: float | None = None
    units: str | None = None
    description: str | None = None


class ProvenanceRecord(BaseModel):
    """Source and processing details needed to trace evidence to its origin."""

    source_product_id: str
    source_url: str
    provider: str
    processing_method: str
    software_version: str | None = None


class PhysicalMeasurement(BaseModel):
    """A measured or derived value with units, scale, availability, and provenance."""

    name: str
    value: float | None
    units: str
    availability: Availability
    spatial_scale_m: float | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    provenance: ProvenanceRecord | None = None


class EvidenceRecord(BaseModel):
    """Evidence group attached to a candidate or scientific comparison."""

    category: str
    status: Availability
    summary: str
    supporting_observation_ids: list[str] = Field(default_factory=list)
    measurements: list[PhysicalMeasurement] = Field(default_factory=list)
