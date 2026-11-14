import { ArrowUpRight, Globe2, Search, SlidersHorizontal } from "lucide-react";
import type { ScorecardResult, ScorecardSite, ScoreConfig } from "./types";
import { formatLongitude } from "./format";

type Props = {
  sites: ScorecardSite[];
  config: ScoreConfig | null;
  siteId: string;
  objective: string;
  weights: Record<string, number>;
  result: ScorecardResult | null;
  busy: boolean;
  error: string;
  onBack: () => void;
  onSiteChange: (siteId: string) => void;
  onMissionChange: (objective: string) => void;
  onWeightChange: (name: string, value: number) => void;
  onInvalidate: () => void;
  onRank: () => void;
};

export function ScorecardView({
  sites: scoreSites,
  config: scoreConfig,
  siteId: scoreSiteId,
  objective: missionObjective,
  weights,
  result: scorecard,
  busy: scorecardBusy,
  error,
  onBack,
  onSiteChange,
  onMissionChange,
  onWeightChange,
  onInvalidate,
  onRank,
}: Props) {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Globe2 size={17} />
          </div>
          <div>
            <strong>TwinWorld</strong>
            <span>NASA-first analogue scorecards</span>
          </div>
        </div>
        <div className="top-meta">
          <span className="live-dot" /> LRO LOLA + MGS MOLA + Copernicus{" "}
          <span className="divider" /> Research preview
        </div>
        <button className="nav-button" onClick={onBack}>
          Open explorer
        </button>
      </header>
      <section className="workspace-head">
        <div>
          <div className="eyebrow">
            Scientific workspace / planetary–Earth terrain scorecard
          </div>
          <h1>Compare Moon or Mars terrain with Earth</h1>
          <p>
            Rank indexed Earth DEM contexts against selected LOLA or MOLA
            observations. Similarity, observation support, feature
            completeness and mission screening stay separate.
          </p>
        </div>
        <div className="index-count">
          <span>Earth terrain products</span>
          <b>
            {scorecard?.candidate_coverage.indexed_earth_dem_contexts ?? "—"}
          </b>
          <small>
            {scorecard?.candidate_coverage.dataset_ids
              .map((id) =>
                id === "cop-dem-glo-30"
                  ? "Copernicus GLO-30"
                  : id === "nasadem-hgt"
                    ? "NASA NASADEM HGT"
                    : id,
              )
              .join(" + ") ?? "Local index"}
          </small>
        </div>
      </section>
      {error && <div className="error-banner">{error}</div>}
      <div className="scorecard-workspace">
        <section className="panel score-controls">
          <div className="panel-title">
            <span>Scorecard setup</span>
            <SlidersHorizontal size={16} />
          </div>
          <label className="field-label" htmlFor="lunar-site">
            Moon or Mars location
          </label>
          <select
            id="lunar-site"
            value={scoreSiteId}
            onChange={(e) => {
              onSiteChange(e.target.value);
              onInvalidate();
            }}
          >
            {scoreSites.map((site) => (
              <option value={site.id} key={site.id}>
                {site.body.toUpperCase()} · {site.name} ·{" "}
                {Math.abs(site.latitude_deg).toFixed(2)}°
                {site.latitude_deg < 0 ? "S" : "N"},{" "}
                {formatLongitude(site.longitude_east_deg, site.body)}
              </option>
            ))}
          </select>
          {!scoreSites.length && (
            <div className="coverage-note">
              <b>Planetary observations not ingested</b>
              <p>
                Use the bounded LOLA or MOLA ingestion scripts to add NASA
                terrain observations.
              </p>
            </div>
          )}
          <label className="field-label" htmlFor="mission-objective">
            Mission objective
          </label>
          <select
            id="mission-objective"
            value={missionObjective}
            onChange={(e) => onMissionChange(e.target.value)}
          >
            {Object.entries(scoreConfig?.mission_objectives ?? {}).map(
              ([id, preset]) => (
                <option value={id} key={id}>
                  {preset.name}
                </option>
              ),
            )}
          </select>
          <div className="weight-heading">
            <span>Mission weights</span>
            <small>Adjust any variable; zero omits it.</small>
          </div>
          {Object.entries(scoreConfig?.variables ?? {}).map(
            ([id, variable]) => (
              <label className="weight-control" key={id}>
                <span>
                  {variable.label}
                  <small>
                    {" "}
                    ±{variable.tolerance} {variable.units} tolerance
                  </small>
                </span>
                <input
                  aria-label={`${variable.label} weight`}
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={weights[id] ?? 0}
                  onChange={(e) => {
                    onWeightChange(id, Number(e.target.value));
                    onInvalidate();
                  }}
                />
                <b>{(weights[id] ?? 0).toFixed(2)}</b>
              </label>
            ),
          )}
          <button
            className="search-button"
            onClick={onRank}
            disabled={!scoreSiteId || scorecardBusy}
          >
            {scorecardBusy ? (
              <span className="spinner" />
            ) : (
              <Search size={16} />
            )}{" "}
            {scorecardBusy ? "Ranking contexts" : "Rank Earth candidates"}
          </button>
          <div className="coverage-note">
            <b>Bounded coverage</b>
            <p>
              Ranking covers only local Earth contexts with an indexed
              Copernicus DEM. It is not a global search.
            </p>
          </div>
        </section>
        <section className="panel score-main">
          <div className="panel-title">
            <span>
              {scorecard?.mission_objective_name ?? "Ranked Earth candidates"}
            </span>
            {scorecard && (
              <span className="result-count">
                {scorecard.candidates.length} indexed
              </span>
            )}
          </div>
          {!scorecard ? (
            <div className="result-empty">
              <div className="empty-icon">
                <Globe2 size={19} />
              </div>
              <b>Build a terrain scorecard</b>
              <p>
                Choose an objective, tune the terrain weights, then rank the
                available Earth contexts against the selected NASA planetary
                observation.
              </p>
            </div>
          ) : (
            <>
              <div className="score-site">
                <div>
                  <span>NASA {scorecard.site.body} reference</span>
                  <h2>{scorecard.site.name}</h2>
                  <p>
                    {Math.abs(scorecard.site.latitude_deg).toFixed(3)}°
                    {scorecard.site.latitude_deg < 0 ? "S" : "N"},{" "}
                    {formatLongitude(
                      scorecard.site.longitude_east_deg,
                      scorecard.site.body,
                    )}{" "}
                    · {scorecard.site.source.product_id} ·{" "}
                    {scorecard.site.source.retrieved_at
                      ? `retrieved ${scorecard.site.source.retrieved_at}`
                      : "retrieval date not recorded"}
                  </p>
                </div>
                <div
                  className={`suitability ${scorecard.site.mission_suitability.status}`}
                >
                  <small>Provisional mission terrain screen</small>
                  <b>
                    {scorecard.site.mission_suitability.status.replaceAll(
                      "_",
                      " ",
                    )}
                  </b>
                  {scorecard.site.mission_suitability.checks.map((check) => (
                    <div className="mission-check" key={check.name}>
                      <span>
                        {check.name.replaceAll("_", " ")}:{" "}
                        {check.value === null
                          ? "unavailable"
                          : `${check.value.toFixed(2)} ${check.units}`}{" "}
                        / limit {check.maximum} {check.units}
                      </span>
                      <p>{check.basis}</p>
                      {check.basis_source_url && (
                        <a
                          href={check.basis_source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open engineering reference{" "}
                          <ArrowUpRight size={12} />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              {scorecard.site.environmental_evidence && (
                <section className="environmental-evidence">
                  <div>
                    <span>
                      NASA environmental evidence · {scorecard.site.environmental_evidence.body === "moon" ? "Moon" : "Mars"}
                    </span>
                    <b>
                      {scorecard.site.environmental_evidence.summary.median.toFixed(1)} {scorecard.site.environmental_evidence.measurement.units}
                      <small> median {scorecard.site.environmental_evidence.measurement.name.toLowerCase()}</small>
                    </b>
                    <p>
                      Mean {scorecard.site.environmental_evidence.summary.mean.toFixed(1)} ·
                      P10–P90 {scorecard.site.environmental_evidence.summary.p10.toFixed(1)}–{scorecard.site.environmental_evidence.summary.p90.toFixed(1)} {scorecard.site.environmental_evidence.measurement.units} ·
                      {" "}{(scorecard.site.environmental_evidence.context_size_m / 1000).toFixed(1)} km context ·
                      {" "}{(scorecard.site.environmental_evidence.valid_sample_fraction * 100).toFixed(1)}% valid cells
                    </p>
                    <p>
                      {scorecard.site.environmental_evidence.source_description} {scorecard.site.environmental_evidence.observation_period} Valid-cell coverage is not an observation count. Earth data are not paired, and this evidence does not affect the terrain ranking.
                    </p>
                  </div>
                  <a
                    href={scorecard.site.environmental_evidence.label_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {scorecard.site.environmental_evidence.product_id} PDS label{" "}
                    <ArrowUpRight size={13} />
                  </a>
                </section>
              )}
              {scorecard.site.geology_evidence && (
                <section className="environmental-evidence geology-evidence">
                  <div>
                      <span>Regional geological context · USGS</span>
                    <b>
                      {scorecard.site.geology_evidence.classification_status === "mapped"
                        ? [scorecard.site.geology_evidence.map_unit_code, scorecard.site.geology_evidence.map_unit_name, scorecard.site.geology_evidence.map_unit_age].filter(Boolean).join(" · ")
                        : "Map status: " + scorecard.site.geology_evidence.classification_status.replaceAll("_", " ")}
                      <small> categorical regional map evidence</small>
                    </b>
                    <p>
                        {scorecard.site.geology_evidence.source_description} {scorecard.site.geology_evidence.map_unit_interpretation && `Mapped interpretation: ${scorecard.site.geology_evidence.map_unit_interpretation}. `}{scorecard.site.geology_evidence.map_unit_description && `${scorecard.site.geology_evidence.map_unit_description} `}Nominal scale: {scorecard.site.geology_evidence.nominal_cartographic_scale}. This evidence does not affect terrain similarity or mission screening.
                    </p>
                  </div>
                  <a
                    href={scorecard.site.geology_evidence.dataset_reference_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {scorecard.site.geology_evidence.product_id} <ArrowUpRight size={13} />
                  </a>
                </section>
              )}
              <p className="score-method">
                {scorecard.ranking_method}. Scores are 0–1 ranking indices,
                not probabilities. Measurements are included only when units
                match and feature scales are within 5%.
              </p>
              <div className="score-results">
                {scorecard.candidates.map((candidate) => (
                  <article
                    className="score-candidate"
                    key={candidate.observation_id}
                  >
                    <div className="score-candidate-head">
                      <div>
                        <span>Candidate {candidate.rank} · Earth</span>
                        <h3>{candidate.name}</h3>
                        <small>
                          {Math.abs(candidate.latitude_deg).toFixed(2)}°
                          {candidate.latitude_deg < 0 ? "S" : "N"} ·{" "}
                          {formatLongitude(
                            candidate.longitude_east_deg,
                            "earth",
                          )}
                        </small>
                      </div>
                      <div className="score-number">
                        <b>
                          {candidate.similarity_score === null
                            ? "—"
                            : candidate.similarity_score.toFixed(3)}
                        </b>
                        <small>terrain index</small>
                      </div>
                    </div>
                    <div className="completeness">
                      <span>Terrain feature completeness</span>
                      <b>
                        {candidate.matched_variable_count}/
                        {candidate.requested_variable_count} comparable
                        variables ·{" "}
                        {(candidate.data_completeness * 100).toFixed(0)}%
                      </b>
                    </div>
                    <div className="score-variable-list">
                      {candidate.variables.map((item) => (
                        <div className="score-variable" key={item.name}>
                          <div>
                            <b>{item.label}</b>
                            <small>
                              {item.availability === "available"
                                ? `${item.reference_value?.toFixed(2)} ${scorecard.site.body.toUpperCase()} · ${item.earth_value?.toFixed(2)} Earth · Δ ${item.difference !== null ? (item.difference >= 0 ? "+" : "") + item.difference.toFixed(2) : "—"} ${item.units}`
                                : "Unavailable or scale unmatched"}
                            </small>
                          </div>
                          <span>
                            {item.score === null
                              ? "—"
                              : item.score.toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>
                    {!!candidate.why_ranked.length && (
                      <p className="rank-reason">
                        Why ranked: {candidate.why_ranked.join(" · ")}
                      </p>
                    )}
                    <div className="score-candidate-foot">
                      <span>
                        {candidate.source.dataset_id} · Earth analogue-site
                        suitability not assessed
                        {candidate.source.retrieved_at
                          ? ` · retrieved ${candidate.source.retrieved_at}`
                          : " · retrieval date not recorded"}
                        {candidate.source.direct_srtm_source_fraction !== null
                          ? ` · ${(candidate.source.direct_srtm_source_fraction * 100).toFixed(1)}% direct SRTM-class support in context`
                          : ""}
                      </span>
                      <a
                        href={
                          candidate.source.documentation_url ??
                          candidate.source.url
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        {candidate.source.product_id} source{" "}
                        <ArrowUpRight size={13} />
                      </a>
                    </div>
                  </article>
                ))}
              </div>
              <div className="score-disclosure">
                <b>Data quality and limitations</b>
                <p>
                  Observation support ·{" "}
                  {scorecard.site.data_coverage.status === "partial"
                    ? `${scorecard.site.data_coverage.observed_cell_count}/${scorecard.site.data_coverage.grid_cell_count} bins (${((scorecard.site.data_coverage.observed_cell_fraction ?? 0) * 100).toFixed(1)}%)`
                    : scorecard.site.data_coverage.note}
                </p>
                <p>{scorecard.site.data_quality}</p>
                <p>{scorecard.site.mission_suitability.qualification}</p>
                {scorecard.limitations.map((item) => (
                  <p key={item}>{item}</p>
                ))}
                {scorecard.site.source.label_url && (
                  <a
                    href={scorecard.site.source.label_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open NASA PDS product documentation{" "}
                    <ArrowUpRight size={13} />
                  </a>
                )}
                {scorecard.site.source.support_url && (
                  <a
                    href={scorecard.site.source.support_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open MOLA count product <ArrowUpRight size={13} />
                  </a>
                )}
              </div>
            </>
          )}
        </section>
      </div>
      <footer>
        <span>
          ENOM / TwinWorld · NASA LRO LOLA + MGS MOLA + Copernicus DEM
        </span>
        <span>
          NASA, PDS, Copernicus and Planetary Computer provenance shown per
          product
        </span>
        <span>
          <a href="/api/docs" target="_blank">
            API documentation <ArrowUpRight size={16} />
          </a>
        </span>
      </footer>
    </main>
  );
}
