import type { DiscoveryDimensionScore, DiscoveryRank, AnalogueProfile } from "../lib/api";

type Props = {
  targetName: string | null;
  targetBody: string | null;
  profiles: AnalogueProfile[];
  profileId: string;
  weights: Record<string, number>;
  result: DiscoveryRank | null;
  busy: boolean;
  error: string;
  onProfileChange: (id: string) => void;
  onWeightChange: (id: string, value: number) => void;
  onResetWeights: () => void;
  onSelectPlace: (row: DiscoveryRank["recommendations"][number]) => void;
};

export function CoordinateDiscoveryPanel({ targetName, targetBody, profiles, profileId, weights, result, busy, error, onProfileChange, onWeightChange, onResetWeights, onSelectPlace }: Props) {
  const profile = profiles.find((item) => item.id === profileId);
  const rows = result?.recommendations ?? [];
  return <section className="m-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden" aria-labelledby="coordinate-discovery-title">
    <div className="p-3 border-b border-[var(--border-subtle)] space-y-2">
      <p className="text-[11.7px] uppercase tracking-[0.12em] text-[var(--text-muted)]">Overview</p>
      <h3 id="coordinate-discovery-title" className="text-xs font-semibold text-[var(--text-primary)]">Earth analogue comparison</h3>
      <p className="text-[13px] text-[var(--text-muted)]">Ranked Earth contexts for this {targetBody === "moon" ? "lunar" : "Martian"} target. The prototype similarity combines all eight weighted dimensions; visual retrieval remains a separate result.</p>
      <label className="block text-[13px] text-[var(--text-secondary)]">Comparison profile
        <select aria-label="Analogue comparison profile" value={profileId} onChange={(event) => onProfileChange(event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--border-strong)] bg-[#0b1119] px-2.5 py-2 text-xs text-[var(--text-primary)]">
          {profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {profile && <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">{profile.description}</p>}
      {profile && <details>
        <summary className="cursor-pointer text-[13px] text-[var(--text-secondary)]">Adjust eight dimension weights</summary>
        <div className="pt-2 space-y-2">
          {Object.entries(profile.dimensions).map(([id, dimension]) => <label key={id} className="block">
            <span className="flex justify-between gap-2 text-[13px] text-[var(--text-secondary)]"><span>{dimension.label}</span><span className="font-mono-tabular">{(weights[id] ?? 0).toFixed(2)}</span></span>
            <input aria-label={`${dimension.label} weight`} type="range" min="0" max="1" step="0.01" value={weights[id] ?? 0} onChange={(event) => onWeightChange(id, Number(event.target.value))} className="w-full accent-[var(--text-secondary)]" />
          </label>)}
          <div className="flex items-center justify-between gap-2 text-[13px] text-[var(--text-muted)]"><span>Weights apply to all prototype scores; evidence coverage stays separate.</span><button type="button" onClick={onResetWeights} className="shrink-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Reset</button></div>
        </div>
      </details>}
    </div>
    {!targetName && <p className="p-3 text-[14.3px] text-[var(--text-secondary)]">Select a Moon or Mars point on the globe or choose a listed target to begin discovery.</p>}
    {busy && <p className="p-3 text-[14.3px] text-[var(--text-secondary)]" role="status">Resolving the selected location and ranking Earth evidence…</p>}
    {error && <p className="m-3 rounded-lg border border-amber-400/20 bg-amber-400/5 p-2 text-[14.3px] text-amber-100" role="status">{error}</p>}
    {result && <>
      <p className="px-3 py-2 border-b border-[var(--border-subtle)] text-[13px] text-[var(--text-muted)]"><span className="text-[var(--text-primary)]">{targetName ?? result.target.name ?? result.target.observation_id}</span> · eight-dimension prototype ranking · {rows.length} ranked Earth analogues</p>
      {!rows.length && <p className="p-3 text-[14.3px] text-[var(--text-secondary)]">No Earth contexts meet the footprint and terrain-index requirements for this request.</p>}
      <div className="divide-y divide-[var(--border-subtle)]">
        {rows.map((row) => <details key={row.context.observation_id} className="group">
          <summary className="cursor-pointer list-none px-3 py-2.5 flex items-center justify-between gap-3" onClick={() => onSelectPlace(row)}>
            <span className="min-w-0"><span className="block truncate text-xs text-[var(--text-primary)]">#{row.rank} {row.context.name ?? row.context.observation_id}</span><span className="block mt-1 text-[13px] text-[var(--text-muted)]">{Math.round((row.evidence_coverage ?? row.data_completeness) * 100)}% source-backed evidence · {Math.round((row.estimated_weight_coverage ?? 0) * 100)}% estimated · {Math.round((row.simulated_weight_coverage ?? 0) * 100)}% simulated</span></span>
            <span className="shrink-0 text-right"><span className="block font-mono-tabular text-xs text-[var(--text-secondary)]">{(row.prototype_similarity ?? row.score ?? row.similarity_score).toFixed(3)}</span><span className="text-[10.4px] text-[var(--text-muted)]">prototype</span></span>
          </summary>
          <div className="px-3 pb-3 space-y-2">
            <p className="text-[11.7px] leading-relaxed text-[var(--text-muted)]">Prototype similarity is not a probability, validated geological analogue, or mission-suitability result.</p>
            <section className="space-y-2" aria-label="Eight-dimensional breakdown">
              <div><p className="text-[11.7px] uppercase tracking-[0.12em] text-[var(--text-muted)]">Eight-dimensional breakdown</p><p className="text-[11.7px] text-[var(--text-muted)]">Each score contributes through its profile weight, including estimates and simulations.</p></div>
              {(row.dimension_scores ?? row.dimensions ?? []).map((dimension) => <DimensionLine key={dimension.dimension_id ?? dimension.id} dimension={dimension} label={profile?.dimensions[dimension.dimension_id ?? dimension.id]?.label ?? dimension.label ?? dimension.id} />)}
              {!(row.dimension_scores ?? row.dimensions)?.length && <p className="text-[13px] text-amber-200">Eight-dimension scores were not returned for this result.</p>}
            </section>
            <details className="rounded-md border border-[var(--border-subtle)] bg-[#0b1119]">
              <summary className="cursor-pointer px-2.5 py-2 text-[13px] text-[var(--text-primary)]">Scientific details · terrain, context, sources, assumptions</summary>
              <div className="space-y-2 px-2.5 pb-2.5 text-[11.7px] text-[var(--text-secondary)]">
                <p>Observed evidence coverage: {Math.round((row.evidence_coverage ?? 0) * 100)}%. This reports supported source evidence, separately from prototype similarity.</p>
                {row.variables.map((variable) => <p key={variable.name} className="font-mono-tabular">Terrain · {variable.name.replaceAll("_", " ")}: target {variable.reference_value ?? "unavailable"} → Earth {variable.earth_value ?? "unavailable"} {variable.units} · component {variable.score?.toFixed(3) ?? "unavailable"}{variable.reference_spatial_scale_m != null && variable.earth_spatial_scale_m != null ? ` · scales ${Math.round(variable.reference_spatial_scale_m)} / ${Math.round(variable.earth_spatial_scale_m)} m` : ""}</p>)}
                {row.context.land_cover && <p>ESA WorldCover · {row.context.land_cover.status ?? "status unavailable"}{row.context.land_cover.group_fractions ? ` · ${Object.entries(row.context.land_cover.group_fractions).map(([name, fraction]) => `${name.replaceAll("_", " ")} ${(fraction * 100).toFixed(0)}%`).join(" · ")}` : ""}{row.context.land_cover.source_url ? <> · <a className="text-sky-300 underline" href={row.context.land_cover.source_url} target="_blank" rel="noreferrer">source</a></> : null}</p>}
                {row.missing_evidence_dimensions?.length ? <p>Dimensions without paired source-backed evidence: {row.missing_evidence_dimensions.join(", ").replaceAll("_", " ")}.</p> : null}
                {row.context.uncertainty_note && <p>{row.context.uncertainty_note}</p>}
                {row.context.source_url && <a className="text-sky-300 underline" href={row.context.source_url} target="_blank" rel="noreferrer">Open Earth terrain source</a>}
                {result.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
              </div>
            </details>
            {row.context.source_url && <a className="text-[13px] text-sky-300 underline" href={row.context.source_url} target="_blank" rel="noreferrer">Earth terrain source</a>}
          </div>
        </details>)}
      </div>
      {result.limitations.map((limitation) => <p key={limitation} className="px-3 py-1 text-[11.7px] text-[var(--text-muted)]">{limitation}</p>)}
    </>}
  </section>;
}

export function DimensionLine({ dimension, label }: { dimension: DiscoveryDimensionScore; label: string }) {
  const score = dimension.prototype_score ?? dimension.score;
  const scorePercent = Math.max(0, Math.min(100, score * 100));
  const origin = dimension.score_origin ?? (dimension.observed_score != null ? "measured" : "simulated");
  const originLabel = origin === "measured" ? "Measured" : origin === "estimated" ? "Estimated" : "Simulated";
  return <details className="rounded-md border border-[var(--border-subtle)] bg-[#0b1119]">
    <summary className="cursor-pointer list-none px-2.5 py-2 flex items-center justify-between gap-2 text-[13px]">
      <span className="min-w-0 flex-1 text-[var(--text-primary)]">{label}<span className="ml-1.5 text-[var(--text-muted)]">{originLabel}<span className="sr-only"> · {scorePercent}% prototype similarity</span></span><span className="mt-1.5 block h-1 overflow-hidden rounded bg-white/10"><span className="block h-full rounded bg-sky-300" style={{ width: `${scorePercent}%` }} /></span></span>
      <span className="text-right"><span className="block font-mono-tabular text-[var(--text-secondary)]">{score.toFixed(3)}</span><span className="font-mono-tabular text-[10.4px] text-[var(--text-muted)]">+{(dimension.normalized_contribution ?? 0).toFixed(3)}</span></span>
    </summary>
    <div className="px-2.5 pb-2.5 space-y-1.5 text-[11.7px] text-[var(--text-secondary)]">
      <p className="font-mono-tabular text-[var(--text-muted)]">{originLabel} prototype score {score.toFixed(3)} · supported evidence {Math.round((dimension.score_coverage ?? 0) * 100)}% · assigned weight {(dimension.weight ?? 0).toFixed(2)} · effective weight {(dimension.effective_weight ?? 0).toFixed(3)} · normalized contribution {(dimension.normalized_contribution ?? 0).toFixed(3)}</p>
      {dimension.observed_score != null && <p>Comparable measured score: {dimension.observed_score.toFixed(3)}.</p>}
      {dimension.score_note && <p>{dimension.score_note}</p>}
      {dimension.methodology && <p>{dimension.methodology}</p>}
      {dimension.shared_comparison_variables?.length ? <p>Uses terrain comparison measurements: {dimension.shared_comparison_variables.map((name) => name.replaceAll("_", " ")).join(", ")}. Expand Terrain for their values and sources.</p> : null}
      {(dimension.comparison_variables ?? []).map((variable) => <div key={variable.name} className="font-mono-tabular">
        <p>{variable.label ?? variable.name.replaceAll("_", " ")}: {variable.availability !== "available" ? "not compared: compatible measurements unavailable" : variable.reference_groups ? `target ${variable.reference_groups.join(", ").replaceAll("_", " ")} → Earth ${(variable.candidate_groups ?? []).join(", ").replaceAll("_", " ")} · component ${variable.score?.toFixed(3) ?? "—"}` : `target ${variable.reference_value ?? "—"} → Earth ${variable.earth_value ?? "—"} ${variable.units ?? ""} · component ${variable.score?.toFixed(3) ?? "—"}`}</p>
        {variable.metric && <p>Method: {variable.metric}</p>}
        {variable.target_basis && <p>Target basis: {variable.target_basis}</p>}
        {variable.candidate_basis && <p>Earth basis: {variable.candidate_basis}</p>}
        {variable.normalization && <p>Normalization: {variable.normalization}</p>}
        {variable.candidate_components?.map((component) => <p key={component.name}>{component.name.replaceAll("_", " ")}: {component.value.toFixed(3)} · weight {component.weight.toFixed(2)}</p>)}
        {variable.assumptions?.map((assumption) => <p key={assumption}>Assumption: {assumption}</p>)}
        {variable.support_note && <p>{variable.support_note}</p>}
        {variable.interpretation && <p>{variable.interpretation}</p>}
        {[...(variable.reference_measurements ?? []), ...(variable.candidate_measurements ?? [])].map((measurement, index) => <p key={`${measurement.dataset_id ?? measurement.name}-${index}`}>Input · {measurement.name}: {measurement.value ?? "unavailable"} {measurement.units ?? ""}{measurement.temporal_coverage ? ` · ${measurement.temporal_coverage}` : ""}{measurement.source_url ? <> · <a href={measurement.source_url} target="_blank" rel="noreferrer" className="text-sky-300 underline">{measurement.dataset_id ?? "source"}</a></> : null}</p>)}
        {[variable.reference_source_url, variable.candidate_source_url].filter((url): url is string => Boolean(url)).map((url) => <a key={url} href={url} target="_blank" rel="noreferrer" className="block text-sky-300 underline">Open method source</a>)}
        {variable.nominal_cartographic_scales?.length ? <p>Map scales: {variable.nominal_cartographic_scales.join(" · ")}</p> : null}
        {[variable.reference_evidence, variable.candidate_evidence].flatMap((evidence) => Array.isArray(evidence) ? evidence : evidence ? [evidence] : []).map((source, index) => typeof source.source_url === "string" && <a key={`${source.source_url}-${index}`} href={source.source_url} target="_blank" rel="noreferrer" className="block text-sky-300 underline">{typeof source.dataset_id === "string" ? source.dataset_id : "Comparison source"}</a>)}
      </div>)}
      {(dimension.sources ?? []).map((source, index) => source.url && <a key={`${source.dataset_id}-${index}`} href={source.url} target="_blank" rel="noreferrer" className="block text-sky-300 underline">{source.provider ?? source.dataset_id ?? "Evidence source"}</a>)}
    </div>
  </details>;
}
