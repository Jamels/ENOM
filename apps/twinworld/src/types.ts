export type PlanetaryBody = "mars" | "moon";
export type AnyBody = "earth" | "mars" | "moon";

export type Measurement = {
  name: string;
  value: number | null;
  units: string;
  availability: string;
  spatial_scale_m: number | null;
  uncertainty: { description: string | null };
  provenance?: { source_url: string; source_product_id: string };
};

export type TerrainContextMeta = {
  dataset_id: string;
  provider: string;
  source_product_id: string;
  source_url: string;
  context_size_m: number;
  observed_cell_count?: number;
  valid_pixel_count?: number;
  grid_cell_count?: number;
  observed_cell_fraction?: number;
  valid_pixel_fraction?: number;
  missing_data_semantics: string;
};

export type Region = {
  id: string;
  body: "earth" | "mars";
  longitude_east_deg: number;
  latitude_deg: number;
  width_m: number;
  height_m: number;
  native_resolution_m: number;
  crs?: string;
  source_id?: string;
  source_url: string;
  provider: string;
  acquired_at?: string;
  label: string;
  label_status: string;
  geographic_group: string;
  image_url: string;
  available_evidence: string[];
  unavailable_evidence: string[];
  measurements: Measurement[];
  terrain_contexts: TerrainContextMeta[];
};

export type Profile = {
  id: string;
  name: string;
  status: string;
  criteria?: string[];
  limitations: string[];
};

export type SearchResult = {
  observation_id: string;
  rank: number;
  cosine_similarity: number;
  terrain_similarity: number | null;
  combined_score: number | null;
  visual_rank: number | null;
  rank_change_from_visual: number | null;
  eligible_visual_rank: number | null;
  rank_change_within_eligible: number | null;
  ranking_evidence: string[];
  terrain_quality: { eligible: boolean; coverage: number; reason?: string };
  retrieval_method: string;
  source_url: string;
  location: {
    body: string;
    longitude_east_deg: number;
    latitude_deg: number;
    geographic_group: string;
  };
  image_url: string;
  evidence: {
    category: string;
    status: string;
    summary: string;
    measurements?: Measurement[];
  }[];
};

export type SearchResponse = {
  query_observation_id: string;
  profile: string;
  method: string;
  results: SearchResult[];
  scope: string;
  terrain_eligible_candidates: number;
  terrain_excluded_candidates: number;
  query_terrain_quality: {
    eligible: boolean;
    coverage: number;
    reason?: string;
  };
  limitations: string[];
};

export type Comparison = {
  query?: Region;
  candidate?: Region;
  supporting_evidence?: { category: string; status: string; summary: string }[];
  terrain_measurement_differences: {
    name: string;
    query_value: number;
    candidate_value: number;
    difference_candidate_minus_query: number;
    units: string;
    query_scale_m: number;
    candidate_scale_m: number;
    scale_match_tolerance?: string;
    query_uncertainty_note: string | null;
    candidate_uncertainty_note: string | null;
  }[];
  data_gaps: string[];
  limitations: string[];
};

export type EnvironmentalEvidence = {
  body: "moon" | "mars";
  dataset_id: string;
  product_id: string;
  source_url: string;
  label_url: string;
  retrieved_at: string;
  valid_sample_fraction: number;
  sample_count: number;
  valid_sample_count: number;
  context_size_m: number;
  product_start_time?: string;
  product_stop_time?: string;
  source_description: string;
  earth_comparison_status: string;
  scorecard_role: string;
  units: string;
  observation_period?: string;
  mask_url?: string;
  summary: { mean: number; median: number; p10: number; p90: number };
  measurement: Measurement & {
    summary: Record<string, number>;
  };
};

export type GeologyEvidence = {
  dataset_id: string;
  product_id: string;
  source_url: string;
  dataset_reference_url: string;
  retrieved_at: string;
  map_unit_code: string | null;
  map_unit_name?: string | null;
  map_unit_age?: string | null;
  map_unit_description?: string | null;
  map_unit_interpretation?: string | null;
  candidate_unit_codes?: string[];
  classification_status: string;
  nominal_cartographic_scale: string;
  source_description: string;
  usage_note?: string;
  scorecard_role: string;
};

export type ScorecardSite = {
  id: string;
  name: string;
  body: "moon" | "mars";
  longitude_east_deg: number;
  latitude_deg: number;
  dataset_id: string;
  source_product_id: string;
  source_url: string;
  counts_source_url: string | null;
  retrieved_at: string | null;
  measurements: Measurement[];
  environmental_evidence: EnvironmentalEvidence | null;
  geology_evidence: GeologyEvidence | null;
  data_quality: string;
  data_coverage: {
    status: string;
    observed_cell_count: number | null;
    grid_cell_count: number | null;
    observed_cell_fraction: number | null;
    note: string;
  };
};

export type ScoreVariable = { label: string; units: string; tolerance: number };

export type ScoreConfig = {
  variables: Record<string, ScoreVariable>;
  mission_objectives: Record<
    string,
    {
      name: string;
      weights: Record<string, number>;
      limits: Record<string, number>;
    }
  >;
};

export type ScoreVariableResult = {
  name: string;
  label: string;
  availability: string;
  reference_value: number | null;
  earth_value: number | null;
  difference: number | null;
  units: string;
  weight: number;
  score: number | null;
  tolerance: number;
  scale_match: boolean;
  reference_spatial_scale_m?: number;
  earth_spatial_scale_m?: number;
};

export type MissionCheck = {
  name: string;
  value: number | null;
  units: string;
  maximum: number;
  status: string;
  basis: string;
  basis_source_url: string | null;
};

export type CandidateScore = {
  observation_id: string;
  name: string;
  rank: number;
  latitude_deg: number;
  longitude_east_deg: number;
  similarity_score: number | null;
  score_interpretation: string;
  data_completeness: number;
  matched_variable_count: number;
  requested_variable_count: number;
  variables: ScoreVariableResult[];
  why_ranked: string[];
  mission_suitability: {
    status: string;
    qualification: string;
    checks: MissionCheck[];
  };
  source: {
    dataset_id: string;
    product_id: string;
    url: string;
    documentation_url: string | null;
    retrieved_at: string | null;
    processing_method: string;
    data_coverage: {
      observed_cell_fraction: number | null;
      note: string;
    } | null;
    direct_srtm_source_fraction: number | null;
  };
};

export type ScorecardResult = {
  site: {
    id: string;
    name: string;
    body: "moon" | "mars";
    longitude_east_deg: number;
    latitude_deg: number;
    measurements: Measurement[];
    environmental_evidence: EnvironmentalEvidence | null;
    geology_evidence: GeologyEvidence | null;
    data_quality: string;
    data_coverage: ScorecardSite["data_coverage"];
    source: {
      dataset_id: string;
      product_id: string;
      url: string;
      support_url: string | null;
      label_url: string | null;
      retrieved_at: string | null;
      observation_period: string | null;
    };
    mission_suitability: {
      status: string;
      qualification: string;
      checks: MissionCheck[];
    };
  };
  mission_objective: string;
  mission_objective_name: string;
  weights: Record<string, number>;
  ranking_method: string;
  candidates: CandidateScore[];
  candidate_coverage: {
    indexed_earth_dem_contexts: number;
    dataset_ids: string[];
    status: string;
    note: string;
  };
  limitations: string[];
};

export type CatalogueEntry = {
  id: string;
  name: string;
  body: AnyBody;
  longitude_east_deg: number;
  latitude_deg: number;
  candidate_type: string;
  status: string;
  basis: string;
  source_url: string;
  dataset_refs: string[];
};

export type CatalogueResponse = {
  catalogue_id: string;
  catalogue_status: string;
  coordinate_precision_note: string;
  coordinate_convention: string;
  entries: CatalogueEntry[];
};

export type DatasetInfo = {
  id: string;
  provider: string;
  name: string;
  version: string;
  bodies: string[];
  variable: string;
  units: string;
  native_resolution_m: number | string;
  access_method: string;
  status: string;
  source_url: string;
  coverage_count?: number;
  uncertainty?: string;
  missing_data_semantics?: string;
  observation_period?: string;
  crs?: string;
};

export type EquipmentId = "rover" | "lander" | "habitat" | "drill" | "drone" | "suit";

export type TargetDataTier = "scorecard_imagery" | "scorecard_only" | "imagery_only" | "catalogue_only";

export type PlanetaryTarget = {
  id: string;
  name: string;
  subtitle: string;
  body: PlanetaryBody;
  latitude_deg: number;
  longitude_east_deg: number;
  tier: TargetDataTier;
  scorecardSite: ScorecardSite | null;
  pilotRegion: Region | null;
  catalogueEntry: CatalogueEntry | null;
  equipmentTags: EquipmentId[];
};

export type EarthCandidate = {
  id: string;
  name: string;
  regionLabel: string;
  latitude_deg: number;
  longitude_east_deg: number;
  rank: number | null;
  scorecardCandidate: CandidateScore | null;
  searchResult: SearchResult | null;
  pilotRegion: Region | null;
  catalogueEntry: CatalogueEntry | null;
};
