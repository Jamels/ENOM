import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, SlidersHorizontal } from "lucide-react";
import type { AnalogueDimension, AnalogueDiscovery, AnalogueProfile } from "../lib/api";
import { planetarySourceStyle } from "../planetaryTokens";

type Props = {
  targetId: string | null;
  targetName: string | null;
  targetBody: string | null;
  profiles: AnalogueProfile[];
  profileId: string;
  weights: Record<string, number>;
  result: AnalogueDiscovery | null;
  busy: boolean;
  error: string;
  onProfileChange: (id: string) => void;
  onWeightChange: (id: string, value: number) => void;
  onResetWeights: () => void;
  onSelectPlace?: (place: AnalogueDiscovery["results"][number]["place"]) => void;
};

export function AnalogueDiscoveryPanel({ targetId, targetName, targetBody, profiles, profileId, weights, result, busy, error, onProfileChange, onWeightChange, onResetWeights, onSelectPlace }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showWeights, setShowWeights] = useState(false);

  const activeProfile = useMemo(() => profiles.find((item) => item.id === profileId), [profiles, profileId]);
  const weightSum = Object.values(weights).reduce((sum, value) => sum + value, 0);

  return (
    <section className="m-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
      <div className="p-3 border-b border-[var(--border-subtle)] space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">Analogue discovery</h3>
            <p className="mt-1 text-[10px] text-[var(--text-muted)]">Best matches in ENOM’s current candidate coverage</p>
          </div>
          <button type="button" onClick={() => setShowWeights((open) => !open)} className="inline-flex items-center gap-1 text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <SlidersHorizontal size={13} /> Weights
          </button>
        </div>
        <select aria-label="Analogue comparison profile" value={profileId} onChange={(event) => onProfileChange(event.target.value)} className="w-full rounded-lg border border-[var(--border-strong)] bg-[#0b1119] px-2.5 py-2 text-xs text-[var(--text-primary)]">
          {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
        </select>
        {activeProfile && <p className="text-[10px] leading-relaxed text-[var(--text-secondary)]">{activeProfile.description}</p>}
        {showWeights && activeProfile && (
          <div className="space-y-2 pt-1">
            {Object.entries(activeProfile.dimensions).map(([id, dimension]) => (
              <label key={id} className="block">
                <span className="flex justify-between gap-2 text-[10px] text-[var(--text-secondary)]"><span>{dimension.label}</span><span className="font-mono-tabular">{(weights[id] ?? 0).toFixed(2)}</span></span>
                <input aria-label={`${dimension.label} weight`} type="range" min="0" max="1" step="0.01" value={weights[id] ?? 0} onChange={(event) => onWeightChange(id, Number(event.target.value))} className="w-full accent-[var(--text-secondary)]" />
              </label>
            ))}
            <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)]">
              <span>Weights are normalized during scoring</span>
              <button type="button" onClick={onResetWeights} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Reset</button>
            </div>
            {weightSum <= 0 && <p className="text-[10px] text-rose-300">Choose at least one dimension weight above zero.</p>}
          </div>
        )}
      </div>

      {targetBody === "earth" ? <p className="p-3 text-[11px] text-[var(--text-secondary)]">Select a Moon or Mars target to find Earth comparison places.</p> : null}
      {!targetId && <p className="p-3 text-[11px] text-[var(--text-secondary)]">Choose a target place to start a comparison.</p>}
      {busy && <p className="p-3 text-[11px] text-[var(--text-secondary)]">Comparing measured evidence…</p>}
      {error && <p className="m-3 rounded-lg border border-rose-400/20 bg-rose-400/5 p-2 text-[11px] text-rose-200">{error}</p>}

      {result && <>
        <div className="px-3 py-2 border-b border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)]">Target: <span className="text-[var(--text-primary)]">{targetName ?? result.target.name}</span>. Scores use only compatible measurements; gaps do not lower a score. Terrain and a slope/roughness comparison for landing or rover movement are the only dimensions that currently affect rankings. This does not show whether a real mission is safe; mission suitability is not assessed.</div>
        <details className="mx-3 my-2 rounded-lg border border-[var(--border-subtle)] bg-[#0b1119]">
          <summary className="cursor-pointer px-2.5 py-2 text-[10px] text-[var(--text-primary)]">Target evidence and available map layers</summary>
          <div className="p-2.5 space-y-2">
            {result.target_evidence.map((dimension) => <DimensionRow key={dimension.id} dimension={dimension} body={targetBody === "moon" ? "moon" : "mars"} />)}
            <LayerStatus layers={result.target_layers} body={targetBody === "moon" ? "moon" : "mars"} />
          </div>
        </details>
        <div className="max-h-[430px] overflow-y-auto divide-y divide-[var(--border-subtle)]">
          {result.results.map((candidate) => {
            const open = expanded === candidate.place.id;
            const requested = candidate.dimension_scores.filter((dimension) => (dimension.weight ?? 0) > 0);
            const contributing = requested.filter((dimension) => dimension.scored && dimension.score !== null && dimension.score !== undefined && (dimension.score_coverage ?? 0) > 0);
            return <div key={candidate.place.id}>
              <button type="button" onClick={() => { setExpanded(open ? null : candidate.place.id); onSelectPlace?.(candidate.place); }} className="w-full p-3 text-left hover:bg-[var(--bg-hover)]">
                <span className="flex items-start justify-between gap-2">
                  <span className="flex items-start gap-2 min-w-0">
                    <span className="pt-0.5 text-[10px] font-mono-tabular text-[var(--text-muted)]">{candidate.rank ? `#${candidate.rank}` : "—"}</span>
                    <span className="min-w-0"><span className="block truncate text-xs font-medium" style={{ color: "var(--planet-earth-primary)" }}>{candidate.place.name}</span><span className="mt-0.5 block text-[10px] text-[var(--text-muted)]">{contributing.length} of {requested.length} weighted dimensions contribute · {Math.round(candidate.evidence_coverage * 100)}% profile evidence coverage</span></span>
                  </span>
                  <span className="flex items-center gap-2 shrink-0">{candidate.score === null ? <span className="text-[10px] text-amber-300">Not scored</span> : <span className="font-mono-tabular text-xs text-[var(--text-primary)]">{candidate.score.toFixed(3)}</span>}{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                </span>
              </button>
              {open && <div className="px-3 pb-3 space-y-2">
                <p className="text-[10px] text-[var(--text-muted)]">{candidate.place.basis ?? candidate.mission_suitability.note}</p>
                <p className="rounded-md border border-[var(--border-subtle)] bg-[#0b1119] p-2 text-[9px] leading-relaxed text-[var(--text-secondary)]">The overall index combines scored dimensions using profile weight × comparison coverage. Expand a scored dimension below to inspect the values, spatial scales, tolerances, and component scores behind it. Unscored dimensions do not count as zero.</p>
                <SideBySideLayers targetLayers={result.target_layers} candidateLayers={candidate.layers} targetName={result.target.name} candidateName={candidate.place.name} targetBody={targetBody === "moon" ? "moon" : "mars"} />
                {candidate.dimension_scores.map((dimension) => <DimensionRow key={dimension.id} dimension={dimension} body="earth" />)}
                {candidate.place.source_url && <a href={candidate.place.source_url} target="_blank" rel="noreferrer" className="planetary-source inline-flex items-center gap-1 text-[10px]" style={planetarySourceStyle("earth")}>Place source <ExternalLink size={11} /></a>}
                <p className="text-[10px] text-amber-200">Mission suitability: not assessed</p>
              </div>}
            </div>;
          })}
        </div>
        <p className="px-3 py-2 border-t border-[var(--border-subtle)] text-[10px] leading-relaxed text-[var(--text-muted)]">{result.search_scope}</p>
      </>}
    </section>
  );
}

function SideBySideLayers({ targetLayers, candidateLayers, targetName, candidateName, targetBody }: {
  targetLayers: AnalogueDiscovery["target_layers"];
  candidateLayers: AnalogueDiscovery["results"][number]["layers"];
  targetName: string;
  candidateName: string;
  targetBody: "mars" | "moon";
}) {
  return <div className="rounded-lg border border-[var(--border-subtle)] p-2.5 space-y-2">
    <div><p className="text-[10px] font-medium text-[var(--text-primary)]">Source layers</p><p className="text-[9px] text-[var(--text-muted)]">Separate local views; not pixel-aligned.</p></div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <LayerPreview title={targetName} layers={targetLayers} body={targetBody} />
      <LayerPreview title={candidateName} layers={candidateLayers} body="earth" />
    </div>
  </div>;
}

function LayerPreview({ title, layers, body }: { title: string; layers: AnalogueDiscovery["target_layers"]; body: "mars" | "moon" | "earth" }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showSlopeOverlay, setShowSlopeOverlay] = useState(false);
  const [showRoverPositions, setShowRoverPositions] = useState(false);
  const selected = layers.find((layer) => layer.id === selectedId) ?? layers[0];
  const observation = selected?.observations.find((item) => item.url) ?? selected?.observations[0];
  const previewUrl = selected?.url ?? observation?.url;
  const elevationLayer = layers.find((layer) => layer.id === "terrain_dem");
  const slopeLayer = layers.find((layer) => layer.id === "terrain_slope");
  const roverLayer = layers.find((layer) => layer.id === "rover_operations");
  const elevationUrl = elevationLayer?.url ?? elevationLayer?.observations.find((item) => item.url)?.url;
  const slopeUrl = slopeLayer?.url ?? slopeLayer?.observations.find((item) => item.url)?.url;
  const roverUrl = roverLayer?.url ?? roverLayer?.observations.find((item) => item.url)?.url;
  const overlaySelection = ["terrain_dem", "terrain_slope", "rover_operations"].includes(selected?.id ?? "");
  const canOverlaySlope = Boolean(
    elevationUrl && slopeUrl && elevationLayer?.alignment_group
    && elevationLayer.alignment_group === slopeLayer?.alignment_group
    && elevationLayer.body === slopeLayer?.body
    && overlaySelection,
  );
  const canOverlayRover = Boolean(
    elevationUrl && roverUrl && elevationLayer?.alignment_group
    && elevationLayer.alignment_group === roverLayer?.alignment_group
    && elevationLayer.body === roverLayer?.body
    && elevationLayer.body === "mars"
    && overlaySelection,
  );
  const showComposite = (showSlopeOverlay && canOverlaySlope) || (showRoverPositions && canOverlayRover);
  const crs = observation?.crs ?? (Array.isArray(selected?.crs) ? selected.crs.find(Boolean) : selected?.crs);
  const contextSize = observation?.context_size_m ?? selected?.context_size_m;
  return <div className="min-w-0 rounded-md border border-[var(--border-subtle)] bg-[#0b1119] p-2 space-y-1.5">
    <p className="truncate text-[10px] font-medium text-[var(--text-primary)]" title={title}>{title}</p>
    {selected && <>
      <select aria-label={`${title} map layer`} value={selected.id} onChange={(event) => setSelectedId(event.target.value)} className="w-full rounded border border-[var(--border-strong)] bg-[#0b1119] px-1.5 py-1 text-[9px] text-[var(--text-primary)]">
        {layers.map((layer) => <option key={layer.id} value={layer.id}>{layer.label} · {layer.status.replaceAll("_", " ")}</option>)}
      </select>
      {canOverlaySlope && <label className="flex items-center gap-1.5 text-[9px] text-[var(--text-secondary)]"><input type="checkbox" checked={showSlopeOverlay} onChange={(event) => setShowSlopeOverlay(event.target.checked)} />Show slope over elevation</label>}
      {canOverlayRover && <label className="flex items-center gap-1.5 text-[9px] text-[var(--text-secondary)]"><input type="checkbox" checked={showRoverPositions} onChange={(event) => setShowRoverPositions(event.target.checked)} />Show rover positions</label>}
      {showComposite ? <div className="relative aspect-square w-full overflow-hidden rounded bg-black">
        <img src={elevationUrl} alt={`Elevation at ${title}`} loading="lazy" className="absolute inset-0 h-full w-full object-contain" />
        {showSlopeOverlay && canOverlaySlope && <img src={slopeUrl} alt={`Slope overlay at ${title}`} loading="lazy" className="absolute inset-0 h-full w-full object-contain opacity-50 mix-blend-screen" />}
        {showRoverPositions && canOverlayRover && <img src={roverUrl} alt={`Perseverance position overlay at ${title}`} loading="lazy" className="absolute inset-0 h-full w-full object-contain" />}
      </div> : previewUrl && <img src={previewUrl} alt={`${selected.label} at ${title}`} loading="lazy" className="aspect-square w-full rounded object-contain bg-black" />}
      {showComposite && <p className="text-[9px] text-[var(--text-muted)]">These layers share the same local DEM grid and {body} coordinates. Slope colours use 0–30°. Rover dots are selected drive-position fixes in this map window; they do not trace the wheel path. The other place is shown separately.</p>}
      <p className="text-[9px] leading-relaxed text-[var(--text-muted)]">{selected.alignment_note}</p>
      {(contextSize || crs) && <p className="break-all font-mono-tabular text-[8px] text-[var(--text-muted)]">{contextSize ? `${(contextSize / 1000).toFixed(1)} km context` : ""}{contextSize && crs ? " · " : ""}{crs ?? ""}</p>}
      {observation?.coverage_fraction != null && <p className="text-[9px] text-[var(--text-secondary)]">Indexed coverage: {Math.round(observation.coverage_fraction * 100)}% ({observation.coverage_kind?.replaceAll("_", " ")})</p>}
      {observation?.source_url && <a href={observation.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[9px] text-sky-300">Open source product <ExternalLink size={9} /></a>}
      {!previewUrl && <p className="text-[9px] text-amber-200">No map image available here.</p>}
    </>}
    {!selected && <p className="text-[9px] text-[var(--text-muted)]">No source layer is linked to this place.</p>}
  </div>;
}

function LayerStatus({ layers, body }: { layers: AnalogueDiscovery["target_layers"]; body: "mars" | "moon" | "earth" }) {
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);
  const [selectedObservationId, setSelectedObservationId] = useState<string | null>(null);
  if (!layers.length) return <p className="text-[10px] text-[var(--text-muted)]">No source imagery or georeferenced map layer is linked to this place yet.</p>;
  const selected = layers.find((layer) => layer.id === selectedLayerId) ?? layers[0];
  const observation = selected.observations.find((item) => item.id === selectedObservationId) ?? selected.observations.find((item) => item.url);
  const previewUrl = selected.url ?? observation?.url;
  const crs = observation?.crs ?? (Array.isArray(selected.crs) ? selected.crs.find(Boolean) : selected.crs);
  const contextSize = observation?.context_size_m ?? selected.context_size_m;
  const coords = observation?.latitude_deg !== undefined && observation.longitude_east_deg !== undefined
    ? `${observation.latitude_deg.toFixed(3)}°, ${observation.longitude_east_deg.toFixed(3)}°E`
    : null;
  return <div className="space-y-1.5">
    <p className="text-[10px] font-medium text-[var(--text-primary)]">Local source layers</p>
    <div className="flex flex-wrap gap-1">
      {layers.map((layer) => <button key={layer.id} type="button" onClick={() => setSelectedLayerId(layer.id)} className={`rounded-md border px-2 py-1 text-[10px] ${selected.id === layer.id ? "planetary-selection" : "border-[var(--border-subtle)] text-[var(--text-muted)]"}`} style={selected.id === layer.id ? planetarySourceStyle(body) : undefined}>{layer.label}</button>)}
    </div>
    {selected.observations.length > 1 && <div className="flex flex-wrap gap-1">{selected.observations.filter((item) => item.url).map((item, index) => <button key={item.id} type="button" onClick={() => setSelectedObservationId(item.id)} className="rounded border border-[var(--border-subtle)] px-1.5 py-0.5 text-[9px] text-[var(--text-muted)]">Image {index + 1}</button>)}</div>}
    <div className="rounded-md border border-[var(--border-subtle)] p-2 text-[10px]">
      <div className="flex justify-between gap-2"><span className="text-[var(--text-primary)]">{selected.label}</span><span className={selected.status === "available" ? "text-emerald-300" : "text-amber-300"}>{selected.status.replaceAll("_", " ")}</span></div>
      {previewUrl && <img src={previewUrl} alt={`${selected.label} local context`} loading="lazy" className="mt-2 w-full max-h-40 rounded-md object-contain bg-black" />}
      <p className="mt-1 text-[var(--text-muted)]">{selected.alignment_note}</p>
      {(contextSize || crs || coords) && <p className="mt-1 font-mono-tabular text-[var(--text-muted)]">{contextSize ? `${(contextSize / 1000).toFixed(1)} km patch` : ""}{contextSize && (crs || coords) ? " · " : ""}{crs ?? ""}{crs && coords ? " · " : ""}{coords ?? ""}</p>}
      {observation?.source_url && <a href={observation.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-sky-300">Open source product <ExternalLink size={10} /></a>}
      {!previewUrl && <p className="mt-1 text-amber-200">No map image available here.</p>}
    </div>
  </div>;
}

function formatUncertainty(value: string | { description?: string | null; value?: number | null; units?: string | null } | null | undefined) {
  if (!value) return null;
  if (typeof value === "string") return value;
  const magnitude = value.value == null ? "" : ` · ${value.value} ${value.units ?? ""}`;
  return `${value.description ?? "Uncertainty not supplied"}${magnitude}`;
}

function DimensionRow({ dimension, body }: { dimension: AnalogueDimension; body: "mars" | "moon" | "earth" }) {
  const [expanded, setExpanded] = useState(Boolean(dimension.scored));
  const scored = Boolean(dimension.scored && dimension.score !== null && dimension.score !== undefined);
  const weight = dimension.weight ?? 0;
  const coverage = dimension.score_coverage ?? 0;
  return <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)} className="rounded-lg border border-[var(--border-subtle)] bg-[#0b1119]">
    <summary className="cursor-pointer list-none px-2.5 py-2 text-[10px] flex items-center justify-between gap-2">
      <span className="text-[var(--text-primary)]">{dimension.label}<span className="ml-1.5 text-[var(--text-muted)]">{scored ? weight > 0 ? "scored" : "scored · zero weight" : dimension.status === "available" ? "evidence linked · not scored" : dimension.status === "not_observed" ? "no linked measurement" : `${dimension.status.replaceAll("_", " ")} · not scored`}</span></span>
      <span className="shrink-0 font-mono-tabular text-[var(--text-secondary)]">{dimension.score === null || dimension.score === undefined ? "—" : dimension.score.toFixed(3)}</span>
    </summary>
    <div className="px-2.5 pb-2.5 space-y-2 text-[10px] text-[var(--text-secondary)]">
      <p>{dimension.summary}</p>
      {scored && <p className="font-mono-tabular text-[var(--text-muted)]">Profile weight {weight.toFixed(2)} · comparable measurement coverage {Math.round(coverage * 100)}% · effective weight {(weight * coverage).toFixed(3)}</p>}
      {dimension.score_note && <p className="text-amber-200">Not scored: {dimension.score_note}</p>}
      {dimension.evidence_items?.map((item) => <div key={item.id} className="rounded border border-[var(--border-subtle)] p-2 space-y-1"><p className="text-[var(--text-primary)]">{item.provider ?? item.dataset_id ?? "Source"} · {item.kind.replaceAll("_", " ")} evidence</p><p>{item.summary ?? item.interpretation?.summary ?? item.interpretation?.map_unit_name ?? item.product_id ?? "Source-linked observation"}</p>{item.measurement_semantics && <p>{item.measurement_semantics}</p>}{item.interpretation_note && <p>{item.interpretation_note}</p>}{item.study_region && <p>Study area: {item.study_region}</p>}<p className="text-[var(--text-muted)]">{item.location.body}{item.spatial_coverage.location_precision ? ` · ${item.spatial_coverage.location_precision.replaceAll("_", " ")}` : ""}: {item.location.latitude_deg?.toFixed(3) ?? "?"}°, {item.location.longitude_east_deg?.toFixed(3) ?? "?"}°E{item.spatial_coverage.context_size_m ? ` · ${(item.spatial_coverage.context_size_m / 1000).toFixed(1)} km window` : ""}{item.spatial_coverage.nominal_cartographic_scale ? ` · map scale ${item.spatial_coverage.nominal_cartographic_scale}` : ""}{item.temporal_coverage ? ` · ${item.temporal_coverage}` : ""}</p>{item.spatial_coverage.sample_count != null && <p className="text-[var(--text-muted)]">Valid samples: {item.spatial_coverage.sample_count.toLocaleString()}</p>}{item.units.length > 0 && <p className="text-[var(--text-muted)]">Units: {item.units.join(", ")}</p>}{item.spatial_relation && <p className="text-[var(--text-muted)]">Location match: {item.spatial_relation}</p>}{item.uncertainty && <p className="text-[var(--text-muted)]">Uncertainty: {formatUncertainty(item.uncertainty)}</p>}{item.quality_note && <p className="text-[var(--text-muted)]">Data quality: {item.quality_note}</p>}{item.use_limit && <p className="text-[var(--text-muted)]">Use: {item.use_limit}</p>}{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="text-sky-300">Open source record <ExternalLink size={9} className="inline" /></a>}</div>)}
      {dimension.context_evidence?.map((item) => <div key={item.id} className="rounded border border-amber-900/50 bg-amber-950/20 p-2 space-y-1"><p className="text-amber-100">{item.label} · {item.kind}</p><p>{item.summary}</p><p className="text-[var(--text-muted)]">Uncertainty: {item.uncertainty}</p><p className="text-[var(--text-muted)]">Location: {item.location.body}, {item.location.latitude_deg?.toFixed(3) ?? "?"}°, {item.location.longitude_east_deg?.toFixed(3) ?? "?"}°E</p>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="text-sky-300">Open catalogue source <ExternalLink size={9} className="inline" /></a>}</div>)}
      {dimension.interpretations?.map((item) => <div key={item.observation_id} className="rounded border border-[var(--border-subtle)] p-2 space-y-1"><p className="text-[var(--text-primary)]">Map unit: {item.map_unit_code ?? item.candidate_unit_codes?.join(", ") ?? "not classified"}{item.map_unit_name ? ` · ${item.map_unit_name}` : ""}{item.map_unit_age ? ` · ${item.map_unit_age}` : ""}{formatAgeRange(item.map_unit_age_min, item.map_unit_age_max)}</p>{item.map_unit_interpretation && <p>{item.map_unit_interpretation}</p>}{item.major_materials?.length ? <p>Mapped major materials: {item.major_materials.join(", ")}</p> : null}{item.map_unit_description && <p>{item.map_unit_description}</p>}{item.state && <p>Mapped state: {item.state}</p>}{item.nominal_cartographic_scale && <p>Map scale: {item.nominal_cartographic_scale}</p>}{item.map_reference && <p>{item.map_reference}</p>}{item.ngmdb_urls?.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer" className="block text-sky-300">USGS map record <ExternalLink size={9} className="inline" /></a>)}{item.digital_data_url && <a href={item.digital_data_url} target="_blank" rel="noreferrer" className="block text-sky-300">Source map data <ExternalLink size={9} className="inline" /></a>}{item.source_description && <p className="text-[var(--text-muted)]">{item.source_description}</p>}</div>)}
      {dimension.measurements.slice(0, 5).map((measurement, index) => <div key={`${measurement.name}-${index}`}><p className="font-mono-tabular">{measurement.name}: {measurement.value ?? "unavailable"} {measurement.units}{measurement.spatial_scale_m ? ` · ${measurement.spatial_scale_m.toFixed(0)} m scale` : ""}</p>{measurement.sample_count != null && <p className="text-[var(--text-muted)]">{measurement.summary_statistic ?? "Summary"}: {measurement.sample_count.toLocaleString()} valid rows{measurement.source_row_count != null ? ` of ${measurement.source_row_count.toLocaleString()}` : ""}</p>}{measurement.sample_percentiles && measurement.sample_range && <p className="font-mono-tabular text-[var(--text-muted)]">Sample p10–p90: {measurement.sample_percentiles.p10}–{measurement.sample_percentiles.p90} {measurement.units} · range {measurement.sample_range.minimum}–{measurement.sample_range.maximum} {measurement.units}</p>}{measurement.temporal_coverage && <p className="text-[var(--text-muted)]">Period: {measurement.temporal_coverage}</p>}{measurement.uncertainty && <p className="text-[var(--text-muted)]">Uncertainty: {formatUncertainty(measurement.uncertainty)}</p>}{measurement.monthly_values && <details className="mt-1"><summary className="cursor-pointer text-sky-300">Monthly values</summary><p className="mt-1 font-mono-tabular text-[var(--text-muted)]">{Object.entries(measurement.monthly_values).map(([month, value]) => `${month}: ${value ?? "—"}`).join(" · ")}</p></details>}</div>)}
      {dimension.comparison_variables?.map((variable) => <p key={variable.name} className="rounded border border-[var(--border-subtle)] p-2 font-mono-tabular">{variable.label}: {variable.availability === "available" ? <>Target {formatComparisonValue(variable.reference_value)} {variable.units} → Earth {formatComparisonValue(variable.earth_value)} {variable.units}{variable.difference !== null && variable.difference !== undefined ? ` · Δ ${variable.difference > 0 ? "+" : ""}${formatComparisonValue(variable.difference)} ${variable.units}` : ""} · scales {variable.reference_spatial_scale_m?.toFixed(0) ?? "?"} m / {variable.earth_spatial_scale_m?.toFixed(0) ?? "?"} m · tolerance {variable.tolerance !== undefined ? `${formatComparisonValue(variable.tolerance)} ${variable.units}` : "not supplied"} · component score {variable.score?.toFixed(3) ?? "—"}</> : <>Not compared: a value is missing or units/spatial scales are incompatible{variable.reference_value !== null ? ` · target ${formatComparisonValue(variable.reference_value)} ${variable.units}` : " · target value unavailable"}{variable.earth_value !== null ? ` · Earth ${formatComparisonValue(variable.earth_value)} ${variable.units}` : " · Earth value unavailable"}</>}</p>)}
      {dimension.sources.map((source, index) => source.url && <a key={`${source.dataset_id}-${index}`} href={source.url} target="_blank" rel="noreferrer" className="planetary-source block" style={planetarySourceStyle(body)}>{source.provider ?? source.dataset_id ?? "Dataset source"} <ExternalLink size={10} className="inline" /></a>)}
      {dimension.source_connections?.length ? <div className="pt-1 space-y-1"><p className="text-[var(--text-muted)]">Dataset connection status</p>{dimension.source_connections.map((source) => <p key={source.id} className="flex items-start justify-between gap-2"><a href={source.url} target="_blank" rel="noreferrer" className="planetary-source" style={planetarySourceStyle(body)}>{source.name}</a><span className="shrink-0 text-[var(--text-muted)]">{source.place_status.replaceAll("_", " ")}{source.coverage_count > 0 ? ` · ${source.coverage_count}` : ""}</span></p>)}</div> : null}
      {!dimension.sources.length && dimension.source_guides.slice(0, 3).map((source) => <a key={source.url} href={source.url} target="_blank" rel="noreferrer" className="planetary-source block" style={planetarySourceStyle(body)}>{source.name} <ExternalLink size={10} className="inline" /></a>)}
    </div>
  </details>;
}

function formatComparisonValue(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
}

function formatAgeRange(minimum?: string | null, maximum?: string | null) {
  if (!minimum && !maximum) return "";
  if (minimum && minimum === maximum) return ` · ${minimum}`;
  return ` · ${minimum ?? "age unknown"} to ${maximum ?? "age unknown"}`;
}
