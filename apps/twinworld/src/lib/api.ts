import type {
  CatalogueResponse,
  Comparison,
  DatasetInfo,
  Profile,
  Region,
  ScoreConfig,
  ScorecardResult,
  ScorecardSite,
  SearchResponse,
} from "../types";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = response.status + " " + response.statusText;
    try {
      const payload = await response.json();
      message = payload?.detail?.message ?? payload?.detail ?? message;
    } catch {
      // preserve HTTP status fallback
    }
    throw new Error(String(message));
  }
  return response.json() as Promise<T>;
}

export const api = {
  getRegions: (limit = 200) => fetchJson<Region[]>("/api/regions?limit=" + limit),
  getProfiles: () => fetchJson<Profile[]>("/api/profiles"),
  getAnalogueProfiles: () => fetchJson<AnalogueProfile[]>("/api/analogue/profiles"),
  resolveDiscovery: (params: { body: "moon" | "mars"; latitude_deg: number; longitude_east_deg: number; signal?: AbortSignal }) =>
    fetchJson<DiscoveryResolve>("/api/discovery/resolve", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body: params.body, latitude_deg: params.latitude_deg, longitude_east_deg: params.longitude_east_deg }),
      signal: params.signal,
    }),
  rankDiscovery: (params: {
    index_id: string;
    context_id: string;
    weights: Record<string, number>;
    dimension_weights: Record<string, number>;
    result_limit: 10;
    signal?: AbortSignal;
  }) => fetchJson<DiscoveryRank>("/api/discovery/rank", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ index_id: params.index_id, context_id: params.context_id, weights: params.weights, dimension_weights: params.dimension_weights, result_limit: params.result_limit }),
    signal: params.signal,
  }),
  discoverAnalogues: (params: {
    target_site_id: string;
    profile_id: string;
    weights: Record<string, number>;
    limit?: number;
  }) => fetchJson<AnalogueDiscovery>("/api/analogue/discover", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...params, limit: params.limit ?? 10 }),
  }),
  getCatalogue: () => fetchJson<CatalogueResponse>("/api/catalogue"),
  getDatasets: () => fetchJson<DatasetInfo[]>("/api/datasets"),
  getScorecardSites: () =>
    fetchJson<{ status: string; sites: ScorecardSite[]; message?: string | null }>("/api/scorecards/sites"),
  getScorecardConfig: () => fetchJson<ScoreConfig>("/api/scorecards/config"),
  rankScorecard: (params: {
    site_id: string;
    mission_objective: string;
    weights: Record<string, number>;
    limit?: number;
  }) =>
    fetchJson<ScorecardResult>("/api/scorecards/rank", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        site_id: params.site_id,
        mission_objective: params.mission_objective,
        weights: params.weights,
        limit: params.limit ?? 50,
      }),
    }),
  searchPilot: (params: {
    observation_id: string;
    profile?: string;
    method: "visual" | "terrain" | "combined";
    limit?: number;
  }) =>
    fetchJson<SearchResponse>("/api/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        observation_id: params.observation_id,
        profile: params.profile ?? "aeolian",
        method: params.method,
        limit: params.limit ?? 50,
      }),
    }),
  getComparison: (queryId: string, candidateId: string) =>
    fetchJson<Comparison>(
      "/api/comparisons/" + encodeURIComponent(queryId) + "/" + encodeURIComponent(candidateId),
    ),
};

export type AnalogueDimension = {
  id: string;
  label: string;
  status: string;
  summary: string;
  observation_ids: string[];
  sources: { dataset_id: string | null; product_id: string | null; provider: string | null; url: string | null }[];
  measurements: { name: string; value: number | null; units: string; availability: string; spatial_scale_m?: number | null; temporal_coverage?: string; monthly_values?: Record<string, number | null>; summary_statistic?: string; sample_count?: number; source_row_count?: number; sample_percentiles?: { p10: number; p90: number }; sample_range?: { minimum: number; maximum: number }; uncertainty?: string | { description?: string | null; value?: number | null; units?: string | null } }[];
  evidence_items?: { id: string; kind: "interpreted" | "derived" | "measured" | "measured_remote_sensing"; dataset_id?: string | null; product_id?: string | null; provider?: string | null; source_url?: string | null; location: { body: string; latitude_deg?: number | null; longitude_east_deg?: number | null }; spatial_coverage: { location_precision?: string | null; context_size_m?: number | null; spatial_scale_m?: number | null; grid_spacing_deg?: number | null; nominal_cartographic_scale?: string | null; coverage_fraction?: number | null; sample_count?: number | null }; temporal_coverage?: string | null; measurements: { name: string; value: number | null; units: string; availability: string; uncertainty?: string | { description?: string | null; value?: number | null; units?: string | null }; sample_count?: number; sample_percentiles?: { p10: number; p90: number }; sample_range?: { minimum: number; maximum: number } }[]; units: string[]; summary?: string | null; measurement_semantics?: string | null; interpretation_note?: string | null; study_region?: string | null; spatial_relation?: string | null; use_limit?: string | null; quality_note?: string | null; interpretation?: { classification_status?: string | null; map_unit_code?: string | null; map_unit_name?: string | null; summary?: string | null } | null; uncertainty?: string | { description?: string | null; value?: number | null; units?: string | null } | null }[];
  context_evidence?: { id: string; kind: "interpreted" | "derived" | "measured"; label: string; summary: string; source_url?: string | null; location: { body: string; latitude_deg?: number | null; longitude_east_deg?: number | null }; uncertainty: string }[];
  interpretations?: { observation_id: string; classification_status?: string; map_unit_code?: string | null; map_unit_name?: string | null; map_unit_age?: string | null; map_unit_age_min?: string | null; map_unit_age_max?: string | null; map_unit_description?: string | null; map_unit_interpretation?: string | null; major_materials?: string[]; state?: string | null; map_reference?: string | null; ngmdb_urls?: string[]; digital_data_url?: string | null; candidate_unit_codes?: string[]; nominal_cartographic_scale?: string | null; source_description?: string | null; source_url?: string | null }[];
  source_guides: { name: string; url: string }[];
  source_connections?: { id: string; name: string; status: string; place_status: string; coverage_count: number; role: string; url: string }[];
  comparison_variables?: DiscoveryDimensionDetail[];
  score_coverage?: number;
  score_note?: string | null;
  weight?: number;
  score?: number | null;
  prototype_score?: number | null;
  observed_score?: number | null;
  score_origin?: "measured" | "estimated" | "simulated";
  evidence_backed?: boolean;
  effective_weight?: number;
  weight_contribution?: number;
  normalized_contribution?: number;
  methodology?: string | null;
  methodology_kind?: string;
  evidence_status?: string;
  reference_sources?: { dataset_id?: string | null; product_id?: string | null; provider?: string | null; url?: string | null }[];
  candidate_sources?: { dataset_id?: string | null; product_id?: string | null; provider?: string | null; url?: string | null }[];
  location?: { body?: string; latitude_deg?: number | null };
  prototype_context?: { candidate_type?: string; basis?: string; summary?: string; source_url?: string | null };
  scored?: boolean;
};
export type AnalogueProfile = { id: string; name: string; description: string; weights: Record<string, number>; dimensions: Record<string, { label: string; unit: string }> };
export type DiscoveryMeasurementDetail = {
  name: string;
  value?: number | null;
  units?: string | null;
  source_url?: string | null;
  dataset_id?: string | null;
  temporal_coverage?: string | null;
};
export type DiscoveryDimensionDetail = {
  name: string;
  label?: string;
  availability?: string;
  reference_value?: number | string | null;
  earth_value?: number | string | null;
  difference?: number | null;
  units?: string;
  score?: number | null;
  tolerance?: number;
  scale_match?: boolean;
  reference_spatial_scale_m?: number | null;
  earth_spatial_scale_m?: number | null;
  metric?: string;
  assumptions?: string[];
  normalization?: string;
  target_basis?: string;
  candidate_basis?: string;
  reference_body?: string;
  candidate_body?: string;
  reference_latitude_deg?: number;
  candidate_latitude_deg?: number;
  candidate_components?: { name: string; value: number; weight: number }[];
  reference_measurements?: DiscoveryMeasurementDetail[];
  candidate_measurements?: DiscoveryMeasurementDetail[];
  reference_source_url?: string | null;
  candidate_source_url?: string | null;
  support_note?: string;
  interpretation?: string;
  reference_groups?: string[];
  candidate_groups?: string[];
  nominal_cartographic_scales?: string[];
  reference_evidence?: { source_url?: string | null; url?: string | null; dataset_id?: string | null; candidate_type?: string; summary?: string | null }[] | Record<string, unknown>;
  candidate_evidence?: { source_url?: string | null; url?: string | null; dataset_id?: string | null; candidate_type?: string; summary?: string | null }[] | Record<string, unknown>;
};
export type DiscoveryDimensionScore = {
  dimension_id?: string;
  id: string;
  label?: string;
  weight?: number;
  score: number;
  prototype_score?: number;
  observed_score?: number | null;
  score_origin?: "measured" | "estimated" | "simulated";
  evidence_backed?: boolean;
  effective_weight?: number;
  weight_contribution?: number;
  normalized_contribution?: number;
  methodology?: string | null;
  methodology_kind?: string;
  evidence_status?: string;
  score_coverage?: number;
  score_note?: string | null;
  scored?: boolean;
  shared_comparison_variables?: string[];
  comparison_variables?: DiscoveryDimensionDetail[];
  sources?: { dataset_id?: string | null; product_id?: string | null; provider?: string | null; url?: string | null }[];
  reference_sources?: { dataset_id?: string | null; product_id?: string | null; provider?: string | null; url?: string | null }[];
  candidate_sources?: { dataset_id?: string | null; product_id?: string | null; provider?: string | null; url?: string | null }[];
};
export type DiscoveryContext = {
  observation_id: string;
  name?: string;
  dataset_id?: string;
  source_url?: string | null;
  source_catalog_url?: string | null;
  body?: "earth" | "mars" | "moon";
  place_id?: string;
  uncertainty_note?: string;
  missing_data_semantics?: string;
  land_cover?: { status?: string; valid_fraction?: number; group_fractions?: Record<string, number>; source_url?: string | null };
  index_center: { latitude_deg: number; longitude_east_deg: number };
};
export type DiscoveryResolve = {
  index_id: string;
  click: { body: "moon" | "mars"; latitude_deg: number; longitude_east_deg: number };
  status: "covered" | "out_of_coverage";
  coordinate_frame: string;
  contexts: DiscoveryContext[];
};
export type DiscoveryRankRow = {
  context: DiscoveryContext;
  rank: number;
  similarity_score: number;
  score_interpretation?: string;
  data_completeness: number;
  matched_variable_count: number;
  requested_variable_count: number;
  variables: { name: string; reference_value: number | null; earth_value: number | null; difference: number | null; units: string; score: number | null; reference_spatial_scale_m?: number; earth_spatial_scale_m?: number }[];
  dimensions?: DiscoveryDimensionScore[];
  dimension_scores?: DiscoveryDimensionScore[];
  score?: number | null;
  prototype_similarity?: number | null;
  observed_similarity?: number | null;
  evidence_coverage?: number;
  source_context_coverage?: number;
  measured_weight_coverage?: number;
  estimated_weight_coverage?: number;
  simulated_weight_coverage?: number;
  missing_dimensions?: string[];
  missing_evidence_dimensions?: string[];
  evidence_class?: string;
};
export type DiscoveryRank = {
  target: DiscoveryContext;
  status: string;
  results: DiscoveryRankRow[];
  recommendations: DiscoveryRankRow[];
  total_results: number;
  limitations: string[];
};
export type AnalogueDiscovery = {
  target: { id: string; name: string; body: string; longitude_east_deg: number; latitude_deg: number; status: string };
  profile: { id: string; name: string; description: string };
  weights: Record<string, number>;
  results: { place: { id: string; name: string; body: string; latitude_deg: number; longitude_east_deg: number; status: string; basis?: string; source_url?: string }; rank: number | null; score: number | null; prototype_similarity?: number | null; observed_similarity?: number | null; evidence_coverage: number; source_context_coverage?: number; measured_weight_coverage?: number; estimated_weight_coverage?: number; simulated_weight_coverage?: number; dimension_scores: AnalogueDimension[]; layers: PlaceLayer[]; mission_suitability: { status: string; note: string } }[];
  target_evidence: AnalogueDimension[];
  target_layers: PlaceLayer[];
  search_scope: string;
  unique_place_count: number;
  limitations: string[];
};
export type PlaceLayer = { id: string; label: string; status: string; body: string; crs: string | (string | null)[] | null; crs_detail?: string | (string | null)[] | null; alignment_group?: string | null; url?: string | null; context_size_m?: number | null; alignment_note: string; observations: { id: string; url?: string; source_url?: string; acquired_at?: string | null; latitude_deg?: number; longitude_east_deg?: number; context_size_m?: number; crs?: string; crs_detail?: string; coverage_fraction?: number | null; coverage_kind?: string }[] };
