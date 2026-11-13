"""Typed scientific catalogue entities shared by ingestion, retrieval and API layers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanetaryBody(StrEnum):
    EARTH = "earth"
    MARS = "mars"
    MOON = "moon"


class Availability(StrEnum):
    AVAILABLE = "available"
    NOT_OBSERVED = "not_observed"
    OUTSIDE_COVERAGE = "outside_coverage"
    PROCESSING_FAILED = "processing_failed"
    INAPPLICABLE = "inapplicable"
    UNCERTAIN = "uncertain"


class Uncertainty(BaseModel):
    value: float | None = None
    units: str | None = None
    description: str | None = None


class ProvenanceRecord(BaseModel):
    source_product_id: str
    source_url: str
    provider: str
    processing_method: str
    software_version: str | None = None


class SourceDataset(BaseModel):
    id: str
    provider: str
    name: str
    version: str
    body: PlanetaryBody
    variable: str
    units: str
    native_resolution_m: float | None
    spatial_coverage: str
    observation_period: str | None
    crs: str
    access_method: str
    licence: str
    uncertainty: str | None
    missing_data_semantics: str
    source_url: str
    status: str = Field(pattern="^(registered|operational|validated)$")


class PhysicalMeasurement(BaseModel):
    name: str
    value: float | None
    units: str
    availability: Availability
    spatial_scale_m: float | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    provenance: ProvenanceRecord | None = None


class FeatureVector(BaseModel):
    body: PlanetaryBody
    measurements: list[PhysicalMeasurement]
    source_observation_id: str


class EvidenceRecord(BaseModel):
    category: str
    status: Availability
    summary: str
    supporting_observation_ids: list[str] = Field(default_factory=list)
    measurements: list[PhysicalMeasurement] = Field(default_factory=list)


class DataCoverage(BaseModel):
    dataset_id: str
    observation_ids: list[str]
    coverage_count: int
    spatial_extent: dict[str, float] | None
    status: Availability


class RegionOfInterest(BaseModel):
    id: str
    body: PlanetaryBody
    longitude_east_deg: float
    latitude_deg: float
    width_m: float
    height_m: float
    crs: str


class Observation(BaseModel):
    id: str
    body: PlanetaryBody
    dataset_id: str
    observed_at: datetime | None
    footprint: dict[str, Any] | None
    crs: str
    resolution_m: float | None
    source_url: str
    provenance: ProvenanceRecord


class RasterObservation(Observation):
    bands: list[str]
    nodata: float | None
    asset_path: str


class GeologicalUnit(BaseModel):
    unit_id: str
    name: str | None
    lithology: str | None
    age: str | None
    map_scale: str | None
    interpretation_uncertainty: str | None
    provenance: ProvenanceRecord


class AnalogueCandidate(BaseModel):
    observation_id: str
    retrieval_method: str
    rank: int
    score: float
    score_interpretation: str
    evidence: list[EvidenceRecord]


class ScientificComparison(BaseModel):
    query_observation_id: str
    candidate_observation_id: str
    supporting_evidence: list[EvidenceRecord]
    contradictory_evidence: list[EvidenceRecord]
    data_gaps: list[EvidenceRecord]
    interpretation_limitations: list[str]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
