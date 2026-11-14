import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  ChevronDown,
  CircleHelp,
  Globe2,
  Layers3,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import "./style.css";
import { ScorecardView } from "./ScorecardView";
import { formatLongitude } from "./format";
import type {
  Comparison,
  Profile,
  Region,
  Result,
  ScorecardResult,
  ScorecardSite,
  ScoreConfig,
  SearchResponse,
} from "./types";

const get = async <T,>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};
function App() {
  const [body, setBody] = useState<"earth" | "mars">("earth");
  const [regions, setRegions] = useState<Region[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState("");
  const [profile, setProfile] = useState("aeolian");
  const [method, setMethod] = useState<"visual" | "terrain" | "combined">(
    "visual",
  );
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [active, setActive] = useState<Result | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"overview" | "sources">("overview");
  const [view, setView] = useState<"explorer" | "scorecard">("explorer");
  const [scoreSites, setScoreSites] = useState<ScorecardSite[]>([]);
  const [scoreConfig, setScoreConfig] = useState<ScoreConfig | null>(null);
  const [scoreSiteId, setScoreSiteId] = useState("");
  const [missionObjective, setMissionObjective] = useState("landing");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [scorecard, setScorecard] = useState<ScorecardResult | null>(null);
  const [scorecardBusy, setScorecardBusy] = useState(false);
  useEffect(() => {
    Promise.all([
      get<Region[]>("/api/regions?limit=200"),
      get<Profile[]>("/api/profiles"),
    ])
      .then(([r, p]) => {
        setRegions(r);
        setProfiles(p);
        if (r.length) setSelected(r[0].id);
      })
      .catch((e) => setError(`API unavailable · ${e.message}`));
  }, []);
  useEffect(() => {
    Promise.all([
      get<{ sites: ScorecardSite[] }>("/api/scorecards/sites"),
      get<ScoreConfig>("/api/scorecards/config"),
    ])
      .then(([siteData, config]) => {
        setScoreSites(siteData.sites);
        setScoreSiteId(siteData.sites[0]?.id ?? "");
        setScoreConfig(config);
        setWeights(config.mission_objectives.landing.weights);
      })
      .catch((e) => setError(`Scorecard API unavailable · ${e.message}`));
  }, []);
  useEffect(() => {
    const first = regions.find((r) => r.body === body);
    if (first) setSelected(first.id);
    setResults(null);
    setActive(null);
    setComparison(null);
  }, [body, regions]);
  const visible = useMemo(
    () => regions.filter((r) => r.body === body),
    [regions, body],
  );
  const query = regions.find((r) => r.id === selected);
  const selectCandidate = async (candidate: Result) => {
    setActive(candidate);
    setComparison(null);
    setError("");
    try {
      const params = `${encodeURIComponent(selected)}/${encodeURIComponent(candidate.observation_id)}`;
      setComparison(await get<Comparison>(`/api/comparisons/${params}`));
    } catch (e) {
      setError(`Comparison unavailable · ${String(e)}`);
    }
  };
  const run = async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    setResults(null);
    setActive(null);
    setComparison(null);
    try {
      const r = await fetch("/api/search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          observation_id: selected,
          profile,
          method,
          limit: 20,
        }),
      });
      const data = await r.json();
      if (!r.ok)
        throw new Error(data.detail?.message ?? data.detail ?? "Search failed");
      setResults(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const runScorecard = async () => {
    if (!scoreSiteId || !missionObjective) return;
    setScorecardBusy(true);
    setError("");
    try {
      const response = await fetch("/api/scorecards/rank", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          site_id: scoreSiteId,
          mission_objective: missionObjective,
          weights,
          limit: 50,
        }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(
          payload.detail?.message ??
            payload.detail ??
            "Scorecard ranking failed",
        );
      setScorecard(payload);
    } catch (e) {
      setError(String(e));
    } finally {
      setScorecardBusy(false);
    }
  };
  const setMission = (id: string) => {
    setMissionObjective(id);
    setWeights(scoreConfig?.mission_objectives[id]?.weights ?? {});
    setScorecard(null);
  };
  if (view === "scorecard")
    return (
      <ScorecardView
        sites={scoreSites}
        config={scoreConfig}
        siteId={scoreSiteId}
        objective={missionObjective}
        weights={weights}
        result={scorecard}
        busy={scorecardBusy}
        error={error}
        onBack={() => setView("explorer")}
        onSiteChange={(id) => {
          setScoreSiteId(id);
          setScorecard(null);
        }}
        onMissionChange={setMission}
        onWeightChange={(id, value) => {
          setWeights((current) => ({ ...current, [id]: value }));
          setScorecard(null);
        }}
        onInvalidate={() => setScorecard(null)}
        onRank={runScorecard}
      />
    );
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Globe2 size={17} />
          </div>
          <div>
            <strong>TwinWorld</strong>
            <span>Planetary analogue explorer</span>
          </div>
        </div>
        <div className="top-meta">
          <span className="live-dot" /> Local pilot index{" "}
          <span className="divider" /> Phase 0.5
        </div>
        <button
          className="nav-button"
          onClick={() => {
            setView("scorecard");
            setError("");
          }}
        >
          NASA scorecards
        </button>
        <button className="icon-button" title="About this interface">
          <CircleHelp size={17} />
        </button>
      </header>
      <section className="workspace-head">
        <div>
          <div className="eyebrow">
            Scientific workspace / cross-planet retrieval
          </div>
          <h1>Explore planetary analogues</h1>
          <p>
            Compare indexed surface observations and inspect the evidence
            available for each candidate.
          </p>
        </div>
        <div className="index-count">
          <span>Indexed observations</span>
          <b>{regions.length.toLocaleString()}</b>
          <small>Limited pilot · 2 bodies</small>
        </div>
      </section>
      {error && <div className="error-banner">{error}</div>}
      <div className="workspace">
        <aside className="panel controls">
          <div className="panel-title">
            <span>Explorer</span>
            <SlidersHorizontal size={16} />
          </div>
          <label className="field-label">Planetary body</label>
          <div className="segmented">
            <button
              className={body === "earth" ? "chosen" : ""}
              onClick={() => {
                setBody("earth");
                setResults(null);
              }}
            >
              Earth{" "}
              <small>{regions.filter((r) => r.body === "earth").length}</small>
            </button>
            <button
              className={body === "mars" ? "chosen" : ""}
              onClick={() => {
                setBody("mars");
                setResults(null);
              }}
            >
              Mars{" "}
              <small>{regions.filter((r) => r.body === "mars").length}</small>
            </button>
          </div>
          <label className="field-label" htmlFor="region">
            Indexed region
          </label>
          <select
            id="region"
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setResults(null);
            }}
          >
            {visible.map((r) => (
              <option key={r.id} value={r.id}>
                {r.geographic_group} · {r.id.split("-").at(-1)}
              </option>
            ))}
          </select>
          {query && (
            <div className="selected-summary">
              <img
                src={query.image_url}
                alt={`Indexed ${body} surface image for ${query.geographic_group}`}
              />
              <div>
                <b>{query.geographic_group.replaceAll("_", " ")}</b>
                <span>
                  {Math.abs(query.latitude_deg).toFixed(3)}°{" "}
                  {query.latitude_deg >= 0 ? "N" : "S"} ·{" "}
                  {formatLongitude(query.longitude_east_deg, query.body)}
                </span>
                <span>
                  {query.width_m.toLocaleString()} ×{" "}
                  {query.height_m.toLocaleString()} m ·{" "}
                  {query.native_resolution_m} m/px
                </span>
              </div>
            </div>
          )}
          <label className="field-label" htmlFor="profile">
            Scientific objective
          </label>
          <select
            id="profile"
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.status !== "visual retrieval only" ? " · unavailable" : ""}
              </option>
            ))}
          </select>
          <label className="field-label" htmlFor="retrieval-mode">
            Retrieval mode
          </label>
          <select
            id="retrieval-mode"
            value={method}
            onChange={(e) =>
              setMethod(e.target.value as "visual" | "terrain" | "combined")
            }
          >
            <option value="visual">Visual</option>
            <option value="terrain">Terrain</option>
            <option value="combined">Combined</option>
          </select>
          <div className="profile-note">
            <Activity size={14} />
            <span>
              {profiles.find((p) => p.id === profile)?.status}. Combined mode
              uses terrain only when query and candidate evidence pass quality
              checks.
            </span>
          </div>
          <button
            className="search-button"
            onClick={run}
            disabled={!selected || busy}
          >
            {busy ? <span className="spinner" /> : <Search size={16} />}{" "}
            {busy ? "Searching index" : "Find cross-planet candidates"}
          </button>
          <div className="coverage-note">
            <b>Coverage boundary</b>
            <p>
              Searches only these 100 pilot image records. A location outside
              this index cannot be queried.
            </p>
          </div>
        </aside>
        <section className="panel map-panel">
          <div className="panel-title">
            <span>Index coverage · {body}</span>
            <div className="map-tools">
              <span>East-positive longitude / latitude</span>
              <Layers3 size={16} />
            </div>
          </div>
          <div className="map-view">
            <div className="map-grid">
              <div className="latitude lat-top">90°N</div>
              <div className="latitude lat-mid">0°</div>
              <div className="latitude lat-bottom">90°S</div>
              <div className="longitude lon-left">0°E</div>
              <div className="longitude lon-mid">180°E</div>
              <div className="longitude lon-right">360°E</div>
              {visible.map((r) => {
                // Wrap east-positive longitude so signed and 0–360 inputs share one map position.
                const x =
                  ((((r.longitude_east_deg % 360) + 360) % 360) / 360) * 100;
                const y = ((90 - r.latitude_deg) / 180) * 100;
                return (
                  <button
                    key={r.id}
                    className={`map-point ${r.id === selected ? "selected" : ""}`}
                    style={{ left: `${x}%`, top: `${y}%` }}
                    title={`${r.geographic_group} · ${r.id}`}
                    aria-label={`Select ${r.geographic_group}`}
                    onClick={() => setSelected(r.id)}
                  />
                );
              })}
              {!visible.length && (
                <div className="empty-map">
                  No indexed observations for this body.
                </div>
              )}
            </div>
            <div className="map-legend">
              <span>
                <i className="legend-dot" /> Indexed observation
              </span>
              <span>
                <i className="legend-ring" /> Selected region
              </span>
              <span>
                Mercator-independent equirectangular locator · no basemap
              </span>
            </div>
          </div>
          <div className="map-footer">
            <span>
              <b>{visible.length}</b> indexed footprints
            </span>
            <span>Longitude convention: east-positive · 0–360°</span>
            <span className="attribution">
              Image source attribution in region details
            </span>
          </div>
        </section>
        <aside className="panel results-panel">
          <div className="panel-title">
            <span>Analogue candidates</span>
            {results && (
              <span className="result-count">
                {results.results.length} results
              </span>
            )}
          </div>
          {!results ? (
            <div className="result-empty">
              <div className="empty-icon">
                <Search size={19} />
              </div>
              <b>Run a retrieval query</b>
              <p>
                Choose an indexed region and objective. Results are calculated
                from the precomputed pilot embedding index.
              </p>
            </div>
          ) : (
            <>
              <div className="result-scope">
                {results.scope}
                <br />
                Terrain eligible: {results.terrain_eligible_candidates} ·
                excluded for missing or low quality:{" "}
                {results.terrain_excluded_candidates}
                {!results.query_terrain_quality.eligible
                  ? ` · query terrain unavailable: ${results.query_terrain_quality.reason}`
                  : ""}
              </div>
              <div className="result-list">
                {results.results.map((r) => (
                  <button
                    className={`result-card ${active?.observation_id === r.observation_id ? "active" : ""}`}
                    key={r.observation_id}
                    onClick={() => void selectCandidate(r)}
                  >
                    <img
                      src={r.image_url}
                      alt={`Surface image candidate ${r.observation_id}`}
                    />
                    <div className="result-copy">
                      <div className="rank">
                        Candidate {r.rank} <span>{r.location.body}</span>
                      </div>
                      <b>{r.location.geographic_group.replaceAll("_", " ")}</b>
                      <span>
                        {Math.abs(r.location.latitude_deg).toFixed(2)}°
                        {r.location.latitude_deg >= 0 ? "N" : "S"},{" "}
                        {formatLongitude(
                          r.location.longitude_east_deg,
                          r.location.body,
                        )}
                      </span>
                      <small>
                        Visual {r.cosine_similarity.toFixed(4)}
                        {r.terrain_similarity !== null
                          ? ` · terrain ${r.terrain_similarity.toFixed(3)}`
                          : ""}
                        {r.rank_change_within_eligible
                          ? ` · eligible rank ${r.eligible_visual_rank} (${r.rank_change_within_eligible > 0 ? "+" : ""}${r.rank_change_within_eligible})`
                          : ""}
                      </small>
                    </div>
                    <ArrowUpRight size={16} />
                  </button>
                ))}
              </div>
              {active && (
                <div className="detail">
                  <div className="detail-head">
                    <span>Pair evidence</span>
                    <button
                      onClick={() =>
                        setTab(tab === "overview" ? "sources" : "overview")
                      }
                    >
                      {tab === "overview" ? "Sources" : "Overview"}{" "}
                      <ChevronDown size={16} />
                    </button>
                  </div>
                  <div className="pair-images">
                    <img src={query?.image_url} alt="Query observation" />
                    <img src={active.image_url} alt="Candidate observation" />
                  </div>
                  <div className="pair-labels">
                    <span>{query?.body} · query</span>
                    <span>{active.location.body} · candidate</span>
                  </div>
                  {tab === "overview" ? (
                    <>
                      <div className="metric-row">
                        <span>Visual retrieval · cosine</span>
                        <b>{active.cosine_similarity.toFixed(4)}</b>
                      </div>
                      <div className="metric-row">
                        <span>Candidate terrain coverage</span>
                        <b>
                          {(active.terrain_quality.coverage * 100).toFixed(1)}%
                        </b>
                      </div>
                      {active.terrain_similarity !== null && (
                        <div className="metric-row">
                          <span>
                            Terrain similarity · robust scaled features
                          </span>
                          <b>{active.terrain_similarity.toFixed(4)}</b>
                        </div>
                      )}
                      {active.combined_score !== null && (
                        <div className="metric-row">
                          <span>Combined score · equal weighted</span>
                          <b>{active.combined_score.toFixed(4)}</b>
                        </div>
                      )}
                      {active.rank_change_from_visual !== null &&
                        active.rank_change_from_visual !== 0 && (
                          <div className="metric-row">
                            <span>Rank change from visual-only</span>
                            <b>
                              {active.rank_change_from_visual > 0 ? "+" : ""}
                              {active.rank_change_from_visual} · visual rank{" "}
                              {active.visual_rank}
                            </b>
                          </div>
                        )}
                      {active.rank_change_within_eligible !== null &&
                        active.rank_change_within_eligible !== 0 && (
                          <div className="metric-row">
                            <span>Rank change on terrain-eligible set</span>
                            <b>
                              {active.rank_change_within_eligible > 0
                                ? "+"
                                : ""}
                              {active.rank_change_within_eligible} · eligible
                              visual rank {active.eligible_visual_rank}
                            </b>
                          </div>
                        )}
                      {!active.terrain_quality?.eligible && (
                        <p className="limitation">
                          Terrain did not influence this result:{" "}
                          {active.terrain_quality?.reason ??
                            "quality evidence unavailable"}
                        </p>
                      )}
                      <div className="terrain-pair">
                        <div className="evidence-state">
                          <b>{query?.body} · terrain</b>
                          {query?.measurements?.length ? (
                            query.measurements.map((m) => (
                              <div className="measurement" key={m.name}>
                                <span>
                                  {m.name.replaceAll("_", " ")}:{" "}
                                  {m.value?.toFixed(2) ?? "Unavailable"}{" "}
                                  {m.units} · {m.spatial_scale_m?.toFixed(0)} m
                                  context
                                </span>
                                {m.uncertainty.description && (
                                  <small>{m.uncertainty.description}</small>
                                )}
                              </div>
                            ))
                          ) : (
                            <span>
                              Unavailable · no terrain observation indexed
                            </span>
                          )}
                          {query?.terrain_contexts?.map((c) => {
                            const count =
                              c.observed_cell_count ?? c.valid_pixel_count;
                            const fraction =
                              c.observed_cell_fraction ??
                              c.valid_pixel_fraction;
                            return (
                              <span key={c.dataset_id}>
                                {c.dataset_id} ·{" "}
                                {count !== undefined && fraction !== undefined
                                  ? `valid support ${count}/${c.grid_cell_count} (${(fraction * 100).toFixed(1)}%)`
                                  : "coverage not recorded"}{" "}
                                · ${c.context_size_m.toFixed(0)} m window
                              </span>
                            );
                          })}
                        </div>
                        <div className="evidence-state">
                          <b>{active.location.body} · terrain</b>
                          {active.evidence.find((e) => e.category === "terrain")
                            ?.measurements?.length ? (
                            active.evidence
                              .find((e) => e.category === "terrain")
                              ?.measurements?.map((m) => (
                                <div className="measurement" key={m.name}>
                                  <span>
                                    {m.name.replaceAll("_", " ")}:{" "}
                                    {m.value?.toFixed(2) ?? "Unavailable"}{" "}
                                    {m.units} · {m.spatial_scale_m?.toFixed(0)}{" "}
                                    m context
                                  </span>
                                  {m.uncertainty.description && (
                                    <small>{m.uncertainty.description}</small>
                                  )}
                                </div>
                              ))
                          ) : (
                            <span>
                              {active.evidence.find(
                                (e) => e.category === "terrain",
                              )?.summary ?? "Unavailable"}
                            </span>
                          )}
                        </div>
                      </div>
                      {comparison?.terrain_measurement_differences.map((d) => (
                        <div
                          className="metric-row terrain-difference"
                          key={d.name}
                        >
                          <span>
                            {d.name.replaceAll("_", " ")} · candidate minus
                            query
                          </span>
                          <b>
                            {d.difference_candidate_minus_query >= 0 ? "+" : ""}
                            {d.difference_candidate_minus_query.toFixed(2)}{" "}
                            {d.units}
                          </b>
                        </div>
                      ))}
                      {comparison?.terrain_measurement_differences.map((d) => (
                        <p className="limitation" key={`${d.name}-caution`}>
                          {d.query_uncertainty_note}{" "}
                          {d.candidate_uncertainty_note}
                        </p>
                      ))}
                      {comparison?.data_gaps.map((gap) => (
                        <p className="limitation" key={gap}>
                          Unavailable or unmatched: {gap}.
                        </p>
                      ))}
                    </>
                  ) : (
                    <div className="source-links">
                      {query?.source_url && (
                        <a
                          href={query.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open query image source <ArrowUpRight size={13} />
                        </a>
                      )}
                      <a
                        href={active.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open candidate image source <ArrowUpRight size={13} />
                      </a>
                      {query?.terrain_contexts?.map((c) => (
                        <a
                          key={c.dataset_id}
                          href={c.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open query {c.dataset_id} product{" "}
                          <ArrowUpRight size={13} />
                        </a>
                      ))}
                      {active.evidence
                        .find((e) => e.category === "terrain")
                        ?.measurements?.map(
                          (m) =>
                            m.provenance?.source_url && (
                              <a
                                key={m.name}
                                href={m.provenance.source_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Open candidate {m.provenance.source_product_id}{" "}
                                product <ArrowUpRight size={13} />
                              </a>
                            ),
                        )}
                      <p>
                        Products are linked to the indexed regions through their
                        observation and processing records.
                      </p>
                    </div>
                  )}
                  <p className="limitation">
                    A high visual retrieval score is not a physical similarity
                    percentage or a validated analogue claim.
                  </p>
                </div>
              )}
              <div className="limitations">
                {results.limitations.map((x) => (
                  <p key={x}>• {x}</p>
                ))}
              </div>
            </>
          )}
        </aside>
      </div>
      <footer>
        <span>ENOM / TwinWorld · Research preview</span>
        <span>
          Precomputed source observations · no live planetary coverage implied
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
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
