import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import type { DiscoveryDimensionScore } from "../lib/api";
import { DimensionLine } from "./CoordinateDiscoveryPanel";

export type DiscoveryScorecardRow = {
  context: { observation_id: string; name?: string; body?: "earth" | "mars" | "moon"; source_url?: string | null; source_catalog_url?: string | null; index_center?: { latitude_deg: number; longitude_east_deg: number }; land_cover?: { status?: string; group_fractions?: Record<string, number>; source_url?: string | null }; uncertainty_note?: string | null };
  rank: number;
  score?: number | null;
  prototype_similarity?: number | null;
  observed_similarity?: number | null;
  similarity_score: number;
  evidence_class?: string;
  evidence_coverage?: number;
  source_context_coverage?: number;
  measured_weight_coverage?: number;
  estimated_weight_coverage?: number;
  simulated_weight_coverage?: number;
  data_completeness?: number;
  matched_variable_count: number;
  requested_variable_count?: number;
  variables: { name: string; reference_value: number | null; earth_value: number | null; difference: number | null; units: string; score: number | null; reference_spatial_scale_m?: number | null; earth_spatial_scale_m?: number | null }[];
  dimension_scores?: DiscoveryDimensionScore[];
  dimensions?: DiscoveryDimensionScore[];
  missing_dimensions?: string[];
  missing_evidence_dimensions?: string[];
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetName: string;
  targetLocation?: { body?: string; latitude_deg?: number | null; longitude_east_deg?: number | null };
  targetImageUrl?: string | null;
  earthImageUrl?: string | null;
  row: DiscoveryScorecardRow | null;
  rankedRows?: { context: DiscoveryScorecardRow["context"]; rank: number; score?: number | null; prototype_similarity?: number | null; similarity_score?: number | null }[];
  dimensionLabels: Record<string, { label: string }>;
  limitations: string[];
};

export function DiscoveryScorecardModal({ open, onOpenChange, targetName, targetLocation, targetImageUrl, earthImageUrl, row, rankedRows = [], dimensionLabels, limitations }: Props) {
  if (!row) return null;
  const dimensions = row.dimension_scores ?? row.dimensions ?? [];
  const score = row.prototype_similarity ?? row.score ?? row.similarity_score ?? 0;
  const evidenceCoverage = row.evidence_coverage ?? row.data_completeness ?? 0;
  const orderedDimensions = [...dimensions].sort((a, b) => b.score - a.score);
  const closestDimensions = orderedDimensions.slice(0, 3);
  const lowestDimensions = orderedDimensions.slice(-3).reverse();

  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Backdrop className="dialog-backdrop fixed inset-0 z-50 bg-black/75 backdrop-blur-xs" />
      <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6 scroll-contain">
        <Dialog.Popup className="dialog-popup relative my-auto w-full max-w-3xl overflow-hidden rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] text-[var(--text-primary)] shadow-2xl">
          <header className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-5 py-4">
            <div className="min-w-0">
              <p className="text-xs text-[var(--text-muted)]">Prototype comparison · Rank #{row.rank}</p>
              <Dialog.Title className="mt-1 truncate text-lg font-medium">{targetName} ↔ {row.context.name ?? row.context.observation_id}</Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-[var(--text-secondary)]">
                {Math.round(evidenceCoverage * 100)}% source evidence · {row.matched_variable_count}/5 terrain measurements
              </Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close scorecard" className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-2 text-[var(--text-secondary)] hover-surface">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>
          <div className="max-h-[70vh] space-y-5 overflow-y-auto p-5">
            <section className="space-y-3" aria-label="Overview">
              <div><p className="text-[11.7px] uppercase tracking-[0.12em] text-[var(--text-muted)]">Overview</p><h3 className="text-sm font-medium">The comparison</h3></div>
              <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
                <PlaceCard title={targetLocation?.body === "moon" ? "Moon" : targetLocation?.body === "mars" ? "Mars" : "Target"} name={targetName} latitude={targetLocation?.latitude_deg} longitude={targetLocation?.longitude_east_deg} imageUrl={targetImageUrl} />
                <div className="flex flex-col items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] px-4 py-3 text-center"><span className="font-mono-tabular text-2xl text-[var(--text-primary)]">{score.toFixed(3)}</span><span className="text-[11.7px] text-[var(--text-muted)]">prototype similarity</span><span className="mt-2 font-mono-tabular text-sm text-[var(--text-secondary)]">{Math.round(evidenceCoverage * 100)}%</span><span className="text-[11.7px] text-[var(--text-muted)]">source-backed evidence</span></div>
                <PlaceCard title="Earth" name={row.context.name ?? row.context.observation_id} latitude={row.context.index_center?.latitude_deg} longitude={row.context.index_center?.longitude_east_deg} imageUrl={earthImageUrl} />
              </div>
              {rankedRows.length > 0 && <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-3"><p className="mb-2 text-[13px] font-medium text-[var(--text-primary)]">Ranked Earth analogues</p><ol className="grid gap-1 sm:grid-cols-2">{rankedRows.slice(0, 6).map((candidate) => <li key={candidate.context.observation_id} className="flex min-w-0 items-center justify-between gap-3 text-[13px]"><span className="truncate text-[var(--text-secondary)]">#{candidate.rank} {candidate.context.name ?? candidate.context.observation_id}</span><span className="shrink-0 font-mono-tabular text-[var(--text-primary)]">{(candidate.prototype_similarity ?? candidate.score ?? candidate.similarity_score ?? 0).toFixed(3)}</span></li>)}</ol></div>}
              {dimensions.length > 0 && <div className="space-y-2" aria-label="Similarities and differences">
                <div><p className="text-[11.7px] uppercase tracking-[0.12em] text-[var(--text-muted)]">Comparison readout</p><p className="text-[11.7px] text-[var(--text-secondary)]">These summarize higher and lower dimension scores in this prototype. Estimated and simulated scores are not validated physical matches or differences.</p></div>
                <div className="grid gap-2 sm:grid-cols-2"><DimensionReadout title="Similarities · higher prototype scores" items={closestDimensions} dimensionLabels={dimensionLabels} /><DimensionReadout title="Differences · lower prototype scores" items={lowestDimensions} dimensionLabels={dimensionLabels} /></div>
              </div>}
            </section>
            <section className="space-y-2" aria-label="Eight-dimensional breakdown">
              <div><p className="text-[11.7px] uppercase tracking-[0.12em] text-[var(--text-muted)]">Eight-dimensional breakdown</p><h3 className="text-sm font-medium">Scores, weights & contributions</h3></div>
              {dimensions.length ? dimensions.map((dimension) => <DimensionLine
                key={dimension.dimension_id ?? dimension.id}
                dimension={dimension}
                label={dimensionLabels[dimension.dimension_id ?? dimension.id]?.label ?? dimension.label ?? dimension.id}
              />) : <p className="text-xs text-amber-200">No dimension-level evidence was returned for this comparison.</p>}
            </section>
            <details className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)]" aria-label="Scientific details">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Scientific details · measurements, context, imagery & methods</summary>
              <div className="space-y-3 px-3 pb-3 text-[13px]">
                <div><p className="mb-1 font-medium text-[var(--text-primary)]">NASA terrain scorecard · five measurements nested under Terrain</p><div className="grid gap-2 sm:grid-cols-2">{row.variables.map((variable) => <div key={variable.name} className="rounded border border-[var(--border-subtle)] p-2"><p className="font-medium capitalize">{variable.name.replaceAll("_", " ")}</p><p className="mt-1 text-[var(--text-secondary)]">Target {variable.reference_value ?? "unavailable"} → Earth {variable.earth_value ?? "unavailable"} {variable.units}</p><p className="mt-1 text-[var(--text-muted)]">Component {variable.score?.toFixed(3) ?? "not scored"}{variable.reference_spatial_scale_m != null && variable.earth_spatial_scale_m != null ? ` · scales ${Math.round(variable.reference_spatial_scale_m)} / ${Math.round(variable.earth_spatial_scale_m)} m` : ""}</p></div>)}</div></div>
                {targetImageUrl || earthImageUrl ? <div className="grid gap-2 sm:grid-cols-2"><ImageDetail title={`${targetName} source imagery`} src={targetImageUrl} /><ImageDetail title={`${row.context.name ?? "Earth analogue"} source imagery`} src={earthImageUrl} /></div> : <p className="text-[var(--text-muted)]">No image is linked to this indexed terrain comparison; available visual retrieval remains separate.</p>}
                {row.context.land_cover && <p>Earth environmental context · ESA WorldCover {row.context.land_cover.status ?? "status unavailable"}{row.context.land_cover.group_fractions ? ` · ${Object.entries(row.context.land_cover.group_fractions).map(([name, fraction]) => `${name.replaceAll("_", " ")} ${(fraction * 100).toFixed(0)}%`).join(" · ")}` : ""}{row.context.land_cover.source_url ? <> · <a href={row.context.land_cover.source_url} target="_blank" rel="noreferrer" className="text-sky-300 underline">source</a></> : null}</p>}
                <p className="text-[var(--text-secondary)]">Measured weight {Math.round((row.measured_weight_coverage ?? 0) * 100)}% · estimated weight {Math.round((row.estimated_weight_coverage ?? 0) * 100)}% · simulated weight {Math.round((row.simulated_weight_coverage ?? 0) * 100)}%. Evidence coverage excludes prototype assumptions.</p>
                {row.missing_evidence_dimensions?.length ? <p>Dimensions without paired source-backed comparisons: {row.missing_evidence_dimensions.join(", ").replaceAll("_", " ")}.</p> : null}
                {row.context.uncertainty_note && <p>{row.context.uncertainty_note}</p>}
                {(row.context.source_url ?? row.context.source_catalog_url) && <a className="text-sky-300 underline" href={row.context.source_url ?? row.context.source_catalog_url ?? undefined} target="_blank" rel="noreferrer">Open Earth terrain source</a>}
              </div>
            </details>
            {limitations.length > 0 && <section className="space-y-1 text-xs text-[var(--text-muted)]" aria-label="Comparison limitations">
              <h3 className="font-medium text-[var(--text-secondary)]">Limitations</h3>
              {limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
            </section>}
            {(row.context.source_url ?? row.context.source_catalog_url) && <a className="inline-block text-xs text-sky-300 underline" href={row.context.source_url ?? row.context.source_catalog_url ?? undefined} target="_blank" rel="noreferrer">Open Earth terrain source</a>}
          </div>
        </Dialog.Popup>
      </div>
    </Dialog.Portal>
  </Dialog.Root>;
}

function PlaceCard({ title, name, latitude, longitude, imageUrl }: {
  title: string;
  name: string;
  latitude?: number | null;
  longitude?: number | null;
  imageUrl?: string | null;
}) {
  return <div className="min-w-0 overflow-hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-3">
    <p className="text-[11.7px] uppercase tracking-[0.1em] text-[var(--text-muted)]">{title}</p>
    <p className="mt-1 truncate text-xs font-medium text-[var(--text-primary)]" title={name}>{name}</p>
    {latitude != null && longitude != null && <p className="mt-1 font-mono-tabular text-[11.7px] text-[var(--text-muted)]">{latitude.toFixed(3)}°, {longitude.toFixed(3)}°E</p>}
    {imageUrl ? <img src={imageUrl} alt={`${name} source imagery`} loading="lazy" className="mt-2 aspect-[16/7] w-full rounded object-cover bg-black" /> : <div className="mt-2 flex aspect-[16/7] items-center justify-center rounded border border-dashed border-[var(--border-subtle)] text-[11.7px] text-[var(--text-muted)]">No linked source image</div>}
  </div>;
}

function ImageDetail({ title, src }: { title: string; src?: string | null }) {
  return <div className="min-w-0 rounded border border-[var(--border-subtle)] p-2">
    <p className="mb-1 truncate text-[11.7px] text-[var(--text-secondary)]">{title}</p>
    {src ? <img src={src} alt={title} loading="lazy" className="aspect-[16/7] w-full rounded object-contain bg-black" /> : <p className="py-3 text-[11.7px] text-[var(--text-muted)]">No source imagery linked.</p>}
  </div>;
}

function DimensionReadout({ title, items, dimensionLabels }: {
  title: string;
  items: DiscoveryDimensionScore[];
  dimensionLabels: Record<string, { label: string }>;
}) {
  return <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-3">
    <p className="mb-2 text-[13px] font-medium text-[var(--text-primary)]">{title}</p>
    <ul className="space-y-2">{items.map((dimension) => <li key={dimension.id} className="text-[11.7px]"><div className="flex items-center justify-between gap-3"><span className="truncate text-[var(--text-secondary)]">{dimensionLabels[dimension.id]?.label ?? dimension.label ?? dimension.id} · {dimension.score_origin ?? "unknown"}</span><span className="shrink-0 font-mono-tabular text-[var(--text-primary)]">{dimension.score.toFixed(3)}</span></div><span className="mt-1 block h-1 overflow-hidden rounded bg-white/10"><span className="block h-full rounded bg-sky-300" style={{ width: `${Math.max(0, Math.min(100, dimension.score * 100))}%` }} /></span></li>)}</ul>
  </div>;
}
