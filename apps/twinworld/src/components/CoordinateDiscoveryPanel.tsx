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
      <h3 id="coordinate-discovery-title" className="text-xs font-semibold text-[var(--text-primary)]">Eight dimension discovery</h3>
      <p className="text-[10px] text-[var(--text-muted)]">Select a {targetBody === "moon" ? "lunar" : "Martian"} location to compare indexed Earth evidence. Visual similarity remains a separate image retrieval result.</p>
      <label className="block text-[10px] text-[var(--text-secondary)]">Comparison profile
        <select aria-label="Analogue comparison profile" value={profileId} onChange={(event) => onProfileChange(event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--border-strong)] bg-[#0b1119] px-2.5 py-2 text-xs text-[var(--text-primary)]">
          {profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {profile && <p className="text-[10px] leading-relaxed text-[var(--text-secondary)]">{profile.description}</p>}
      {profile && <details>
        <summary className="cursor-pointer text-[10px] text-[var(--text-secondary)]">Adjust eight dimension weights</summary>
        <div className="pt-2 space-y-2">
          {Object.entries(profile.dimensions).map(([id, dimension]) => <label key={id} className="block">
            <span className="flex justify-between gap-2 text-[10px] text-[var(--text-secondary)]"><span>{dimension.label}</span><span className="font-mono-tabular">{(weights[id] ?? 0).toFixed(2)}</span></span>
            <input aria-label={`${dimension.label} weight`} type="range" min="0" max="1" step="0.01" value={weights[id] ?? 0} onChange={(event) => onWeightChange(id, Number(event.target.value))} className="w-full accent-[var(--text-secondary)]" />
          </label>)}
          <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)]"><span>Weights are normalized over supported evidence</span><button type="button" onClick={onResetWeights} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Reset</button></div>
        </div>
      </details>}
    </div>
    {!targetName && <p className="p-3 text-[11px] text-[var(--text-secondary)]">Select a Moon or Mars point on the globe or choose a listed target to begin discovery.</p>}
    {busy && <p className="p-3 text-[11px] text-[var(--text-secondary)]" role="status">Resolving the selected location and ranking Earth evidence…</p>}
    {error && <p className="m-3 rounded-lg border border-amber-400/20 bg-amber-400/5 p-2 text-[11px] text-amber-100" role="status">{error}</p>}
    {result && <>
      <p className="px-3 py-2 border-b border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)]">Target: <span className="text-[var(--text-primary)]">{targetName ?? result.target.name ?? result.target.observation_id}</span>. Scores use compatible indexed evidence. Missing dimensions are shown as unavailable and do not score as zero.</p>
      {!rows.length && <p className="p-3 text-[11px] text-[var(--text-secondary)]">No Earth recommendations have enough compatible evidence for this request.</p>}
      <div className="divide-y divide-[var(--border-subtle)]">
        {rows.map((row) => <details key={row.context.observation_id} className="group">
          <summary className="cursor-pointer list-none px-3 py-2.5 flex items-center justify-between gap-3" onClick={() => onSelectPlace(row)}>
            <span className="min-w-0"><span className="block truncate text-xs text-[var(--text-primary)]">#{row.rank} {row.context.name ?? row.context.observation_id}</span><span className="block mt-1 text-[10px] text-[var(--text-muted)]">{row.evidence_class?.replaceAll("_", " ") ?? "evidence comparison"} · {Math.round((row.evidence_coverage ?? row.data_completeness) * 100)}% evidence coverage</span></span>
            <span className="shrink-0 font-mono-tabular text-xs text-[var(--text-secondary)]">{row.score == null ? "—" : row.score.toFixed(3)}</span>
          </summary>
          <div className="px-3 pb-3 space-y-2">
            <p className="text-[9px] leading-relaxed text-[var(--text-muted)]">Experimental ranking index; it is not a probability, geological validation, or mission suitability result.</p>
            {(row.dimension_scores ?? row.dimensions ?? []).map((dimension) => <DimensionLine key={dimension.dimension_id ?? dimension.id} dimension={dimension} label={profile?.dimensions[dimension.dimension_id ?? dimension.id]?.label ?? dimension.label ?? dimension.id} />)}
            {!(row.dimension_scores ?? row.dimensions)?.length && <p className="text-[10px] text-amber-200">The ranking response did not include its eight dimension evidence rows.</p>}
            {row.missing_dimensions?.length ? <p className="text-[10px] text-amber-200">Unavailable dimensions: {row.missing_dimensions.join(", ").replaceAll("_", " ")}</p> : null}
            {row.context.source_url && <a className="text-[10px] text-sky-300 underline" href={row.context.source_url} target="_blank" rel="noreferrer">Earth terrain source</a>}
          </div>
        </details>)}
      </div>
      {result.limitations.map((limitation) => <p key={limitation} className="px-3 py-1 text-[9px] text-[var(--text-muted)]">{limitation}</p>)}
    </>}
  </section>;
}

export function DimensionLine({ dimension, label }: { dimension: DiscoveryDimensionScore; label: string }) {
  const score = dimension.score;
  return <details className="rounded-md border border-[var(--border-subtle)] bg-[#0b1119]">
    <summary className="cursor-pointer list-none px-2.5 py-2 flex items-center justify-between gap-2 text-[10px]">
      <span className="text-[var(--text-primary)]">{label}<span className="ml-1.5 text-[var(--text-muted)]">{score == null ? `${dimension.evidence_status ?? "unavailable"} · not scored` : "scored"}</span></span>
      <span className="font-mono-tabular text-[var(--text-secondary)]">{score == null ? "—" : score.toFixed(3)}</span>
    </summary>
    <div className="px-2.5 pb-2.5 space-y-1.5 text-[9px] text-[var(--text-secondary)]">
      {dimension.score_note && <p>{dimension.score_note}</p>}
      {dimension.methodology && <p>{dimension.methodology}</p>}
      {dimension.shared_comparison_variables?.length ? <p>Uses terrain comparison measurements: {dimension.shared_comparison_variables.map((name) => name.replaceAll("_", " ")).join(", ")}. Expand Terrain for their values and sources.</p> : null}
      <p className="font-mono-tabular text-[var(--text-muted)]">Assigned weight {(dimension.weight ?? 0).toFixed(2)} · effective weight {(dimension.effective_weight ?? 0).toFixed(3)} · evidence coverage {Math.round((dimension.score_coverage ?? 0) * 100)}%</p>
      {score != null && <p className="font-mono-tabular text-[var(--text-muted)]">Weighted score contribution {(dimension.weight_contribution ?? 0).toFixed(3)} (score × effective weight, before normalization)</p>}
      {(dimension.comparison_variables ?? []).map((variable) => <div key={variable.name} className="font-mono-tabular">
        <p>{variable.label ?? variable.name.replaceAll("_", " ")}: {variable.availability !== "available" ? "not compared: compatible measurements unavailable" : variable.reference_groups ? `target ${variable.reference_groups.join(", ").replaceAll("_", " ")} → Earth ${(variable.candidate_groups ?? []).join(", ").replaceAll("_", " ")} · component ${variable.score?.toFixed(3) ?? "—"}` : `target ${variable.reference_value ?? "—"} → Earth ${variable.earth_value ?? "—"} ${variable.units ?? ""} · component ${variable.score?.toFixed(3) ?? "—"}`}</p>
        {variable.nominal_cartographic_scales?.length ? <p>Map scales: {variable.nominal_cartographic_scales.join(" · ")}</p> : null}
        {[variable.reference_evidence, variable.candidate_evidence].flatMap((evidence) => Array.isArray(evidence) ? evidence : evidence ? [evidence] : []).map((source, index) => typeof source.source_url === "string" && <a key={`${source.source_url}-${index}`} href={source.source_url} target="_blank" rel="noreferrer" className="block text-sky-300 underline">{typeof source.dataset_id === "string" ? source.dataset_id : "Comparison source"}</a>)}
      </div>)}
      {(dimension.sources ?? []).map((source, index) => source.url && <a key={`${source.dataset_id}-${index}`} href={source.url} target="_blank" rel="noreferrer" className="block text-sky-300 underline">{source.provider ?? source.dataset_id ?? "Evidence source"}</a>)}
    </div>
  </details>;
}
