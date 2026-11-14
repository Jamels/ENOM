import { Dialog } from "@base-ui/react/dialog";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ImageOff,
  Info,
  Sparkles,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  Comparison,
  EarthCandidate,
  EquipmentId,
  PlanetaryTarget,
  ScorecardResult,
} from "../types";
import { formatCoords, getEquipmentProfile } from "../lib/missions";

type ComparisonModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: PlanetaryTarget | null;
  earthCandidate: EarthCandidate | null;
  scorecard: ScorecardResult | null;
  comparison: Comparison | null;
  comparisonBusy: boolean;
  equipmentId: EquipmentId;
};

const SHORT_VARIABLE_LABELS: Record<string, string> = {
  elevation_range: "10 km relief",
  mean_slope: "Mean slope",
  slope_p90: "Slope P90",
  median_local_relief_3x3: "Local relief",
  median_roughness_3x3: "Roughness",
};

export function ComparisonModal({
  open,
  onOpenChange,
  target,
  earthCandidate,
  scorecard,
  comparison,
  comparisonBusy,
  equipmentId,
}: ComparisonModalProps) {
  if (!target || !earthCandidate) return null;

  const equipment = getEquipmentProfile(equipmentId);
  const equipTitle =
    target.body === "moon" && equipment.moonName ? equipment.moonName : equipment.name;
  const sc = earthCandidate.scorecardCandidate;
  const sr = earthCandidate.searchResult;
  const site = scorecard?.site;
  const envEvidence = site?.environmental_evidence ?? target.scorecardSite?.environmental_evidence;
  const geoEvidence = site?.geology_evidence ?? target.scorecardSite?.geology_evidence;

  const chartData =
    sc?.variables
      .filter((v) => v.weight > 0)
      .map((v) => ({
        name: SHORT_VARIABLE_LABELS[v.name] ?? v.label,
        scorePct: v.score !== null ? Math.round(v.score * 100) : 0,
        available: v.availability === "available" && v.score !== null,
        rawScore: v.score,
        refVal: v.reference_value,
        earthVal: v.earth_value,
        units: v.units,
      })) ?? [];

  const targetImageUrl = target.pilotRegion?.image_url ?? null;
  const earthImageUrl = earthCandidate.pilotRegion?.image_url ?? sr?.image_url ?? null;
  const bodyAccent = target.body === "mars" ? "#e07246" : "#cbd5e1";
  const bodyLabel = target.body === "mars" ? "Mars" : "Moon";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop fixed inset-0 z-50 bg-black/75 backdrop-blur-xs" />
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-3 sm:p-6 scroll-contain">
          <Dialog.Popup className="dialog-popup relative w-full max-w-5xl rounded-2xl border border-[var(--border-strong)] bg-[#0d121a] text-slate-100 shadow-2xl overflow-hidden my-auto">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[#0f1621] px-5 py-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono-tabular uppercase tracking-[0.07em] text-slate-400">
                  <span style={{ color: bodyAccent }}>{bodyLabel}</span>
                  <span>↔</span>
                  <span className="text-sky-400">Earth</span>
                  <span>·</span>
                  <span>{equipTitle}</span>
                  {sc && <span>· Rank #{sc.rank}</span>}
                </div>
                <Dialog.Title className="font-display text-lg sm:text-xl font-semibold tracking-[-0.02em] text-slate-50 mt-1">
                  {target.name} ↔ {earthCandidate.regionLabel}
                </Dialog.Title>
              </div>
              <Dialog.Close
                aria-label="Close comparison"
                className="pressable shrink-0 rounded-lg border border-[var(--border-subtle)] bg-[#141d2b] p-2 text-slate-300 hover-surface"
              >
                <X className="w-4 h-4" />
              </Dialog.Close>
            </div>

            <div className="p-5 space-y-6">
              {/* Side-by-Side Planetary & Earth Imagery + Coordinates */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <section className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] overflow-hidden">
                  <div className="px-3.5 py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-mono-tabular uppercase tracking-[0.08em]" style={{ color: bodyAccent }}>
                        {bodyLabel} target
                      </div>
                      <div className="text-sm font-medium text-slate-100">{target.name}</div>
                    </div>
                    <span className="font-mono-tabular text-[11px] text-slate-400">
                      {formatCoords(target.latitude_deg, target.longitude_east_deg, target.body)}
                    </span>
                  </div>
                  {targetImageUrl ? (
                    <div className="relative aspect-[16/10] bg-black">
                      <img
                        src={targetImageUrl}
                        alt={target.name + " orbital surface observation"}
                        className="w-full h-full object-cover"
                      />
                      <span className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 text-[10px] font-mono-tabular text-slate-200 border border-white/10">
                        {target.pilotRegion?.provider} · {Number(target.pilotRegion?.native_resolution_m ?? 0).toFixed(1)} m/px
                      </span>
                    </div>
                  ) : (
                    <div className="aspect-[16/10] bg-[#080b10] flex flex-col items-center justify-center p-5 text-center border-b border-[var(--border-subtle)]">
                      <ImageOff className="w-6 h-6 text-slate-500 mb-2" />
                      <p className="text-xs font-medium text-slate-300">Optical surface crop not indexed</p>
                      <p className="text-[11px] text-slate-400 mt-1 max-w-xs">
                        {target.body === "moon"
                          ? "This Moon site provides LRO LOLA LDEM_64 terrain derivatives and Diviner thermal data; LROC NAC imagery is not indexed in Pilot-100."
                          : "Orbital imagery asset unavailable for this catalogue site."}
                      </p>
                    </div>
                  )}
                  <div className="px-3.5 py-2.5 text-[11px] text-slate-400 flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {site ? site.source.dataset_id + " · " + site.source.product_id : target.subtitle}
                    </span>
                    {(site?.source.url || target.pilotRegion?.source_url) && (
                      <a
                        href={site?.source.url ?? target.pilotRegion?.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300"
                      >
                        NASA PDS source <ArrowUpRight className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </section>

                <section className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] overflow-hidden">
                  <div className="px-3.5 py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-sky-400">
                        Earth analogue
                      </div>
                      <div className="text-sm font-medium text-slate-100">{earthCandidate.regionLabel}</div>
                    </div>
                    <span className="font-mono-tabular text-[11px] text-slate-400">
                      {formatCoords(earthCandidate.latitude_deg, earthCandidate.longitude_east_deg, "earth")}
                    </span>
                  </div>
                  {earthImageUrl ? (
                    <div className="relative aspect-[16/10] bg-black">
                      <img
                        src={earthImageUrl}
                        alt={earthCandidate.regionLabel + " Sentinel-2 imagery"}
                        className="w-full h-full object-cover"
                      />
                      <span className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 text-[10px] font-mono-tabular text-slate-200 border border-white/10">
                        {earthCandidate.pilotRegion?.provider ?? "ESA Sentinel-2"} · {Number(earthCandidate.pilotRegion?.native_resolution_m ?? 10).toFixed(1)} m/px
                      </span>
                    </div>
                  ) : (
                    <div className="aspect-[16/10] bg-[#080b10] flex flex-col items-center justify-center p-5 text-center border-b border-[var(--border-subtle)]">
                      <ImageOff className="w-6 h-6 text-slate-500 mb-2" />
                      <p className="text-xs font-medium text-slate-300">Catalogue site · imagery not indexed</p>
                      <p className="text-[11px] text-slate-400 mt-1 max-w-xs">
                        {earthCandidate.catalogueEntry?.basis ?? "Earth Sentinel-2 crop is outside the local pilot-100 index."}
                      </p>
                    </div>
                  )}
                  <div className="px-3.5 py-2.5 text-[11px] text-slate-400 flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {sc ? sc.source.dataset_id + " · " + sc.source.product_id : earthCandidate.catalogueEntry?.dataset_refs.join(", ") ?? "Sentinel-2 L2A"}
                    </span>
                    {(sc?.source.documentation_url || sc?.source.url || earthCandidate.pilotRegion?.source_url || earthCandidate.catalogueEntry?.source_url) && (
                      <a
                        href={sc?.source.documentation_url ?? sc?.source.url ?? earthCandidate.pilotRegion?.source_url ?? earthCandidate.catalogueEntry?.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300"
                      >
                        Source record <ArrowUpRight className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </section>
              </div>

              {/* Calculated Similarity & Retrieval Metrics */}
              {(sc || sr) && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-3.5">
                    <div className="text-[10px] font-mono-tabular uppercase tracking-[0.07em] text-slate-400">
                      Terrain similarity index
                    </div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="font-display text-2xl font-semibold font-mono-tabular text-sky-300">
                        {sc?.similarity_score !== null && sc?.similarity_score !== undefined
                          ? sc.similarity_score.toFixed(3)
                          : sr?.terrain_similarity !== null && sr?.terrain_similarity !== undefined
                            ? sr.terrain_similarity.toFixed(3)
                            : "Unavailable"}
                      </span>
                      <span className="text-[11px] text-slate-400">0–1 ranking index</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">
                      {sc ? sc.matched_variable_count + " of " + sc.requested_variable_count + " weighted variables matched (" + Math.round(sc.data_completeness * 100) + "% completeness)" : "Scale-matched terrain feature score"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-3.5">
                    <div className="text-[10px] font-mono-tabular uppercase tracking-[0.07em] text-slate-400">
                      DINOv2 visual retrieval
                    </div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="font-display text-2xl font-semibold font-mono-tabular text-amber-300">
                        {sr ? sr.cosine_similarity.toFixed(4) : "Not indexed"}
                      </span>
                      {sr && <span className="text-[11px] text-slate-400">cosine</span>}
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">
                      {sr
                        ? "Visual rank #" + (sr.visual_rank ?? sr.rank) + " in Pilot-100; retrieval lead, not physical similarity."
                        : target.body === "moon"
                          ? "Moon optical imagery is outside Pilot-100 DINOv2 index."
                          : "Select a Pilot-100 Mars target for DINOv2 retrieval comparison."}
                    </p>
                  </div>

                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-3.5">
                    <div className="text-[10px] font-mono-tabular uppercase tracking-[0.07em] text-slate-400">
                      Provisional mission screen
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="font-display text-lg font-semibold capitalize text-slate-100">
                        {site ? site.mission_suitability.status.replaceAll("_", " ") : "Not assessed"}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">
                      {sc?.why_ranked.length ? sc.why_ranked[0] : "Terrain screening applies provisional engineering assumptions."}
                    </p>
                  </div>
                </div>
              )}

              {/* Terrain Variable Comparison Chart + Table */}
              {sc && (
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                  <section className="lg:col-span-2 rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h3 className="font-display text-sm font-medium text-slate-100">Variable similarity profile</h3>
                      <span className="text-[10px] font-mono-tabular text-slate-400">exp(-|Δ| / tol)</span>
                    </div>
                    <div className="h-[210px] w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
                          <CartesianGrid stroke="rgba(226,232,240,0.08)" horizontal={false} />
                          <XAxis type="number" domain={[0, 100]} tick={{ fill: "#94a3b8", fontSize: 10 }} unit="%" />
                          <YAxis type="category" dataKey="name" width={96} tick={{ fill: "#cbd5e1", fontSize: 11 }} />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "#0f141c",
                              border: "1px solid rgba(226,232,240,0.18)",
                              borderRadius: "8px",
                              fontSize: "11px",
                              color: "#f1f5f9",
                            }}
                            formatter={(_value, _name, props) => {
                              const item = props.payload;
                              if (!item.available) return ["Unavailable / scale unmatched", "Status"];
                              return [item.rawScore.toFixed(3) + " (" + item.scorePct + "%)", "Score"];
                            }}
                          />
                          <Bar dataKey="scorePct" radius={[0, 4, 4, 0]} barSize={16}>
                            {chartData.map((entry, index) => (
                              <Cell
                                key={index}
                                fill={entry.available ? (entry.scorePct >= 75 ? "#4cc38a" : entry.scorePct >= 45 ? "#56b4e9" : "#e8b04a") : "#334155"}
                              />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </section>

                  <section className="lg:col-span-3 rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] overflow-hidden">
                    <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
                      <h3 className="font-display text-sm font-medium text-slate-100">Scale-matched terrain measurements</h3>
                      <span className="text-[10px] font-mono-tabular text-slate-400">Units & scale ≤5%</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-[#0f1621] text-[10px] font-mono-tabular uppercase tracking-[0.06em] text-slate-400">
                          <tr>
                            <th className="px-3.5 py-2">Variable</th>
                            <th className="px-3 py-2 text-right">{bodyLabel}</th>
                            <th className="px-3 py-2 text-right">Earth</th>
                            <th className="px-3 py-2 text-right">Δ (E − T)</th>
                            <th className="px-3 py-2 text-right">Score</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border-subtle)]">
                          {sc.variables.map((v) => (
                            <tr key={v.name}>
                              <td className="px-3.5 py-2.5">
                                <div className="font-medium text-slate-200">{v.label}</div>
                                <div className="text-[10px] text-slate-500 font-mono-tabular">
                                  w={v.weight.toFixed(2)} · tol ±{v.tolerance} {v.units}
                                  {v.reference_spatial_scale_m ? " · " + Math.round(v.reference_spatial_scale_m) + " m" : ""}
                                </div>
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono-tabular text-slate-200">
                                {v.reference_value !== null ? v.reference_value.toFixed(2) + " " + v.units : "Unavailable"}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono-tabular text-slate-200">
                                {v.earth_value !== null ? v.earth_value.toFixed(2) + " " + v.units : "Unavailable"}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono-tabular text-slate-300">
                                {v.difference !== null ? (v.difference >= 0 ? "+" : "") + v.difference.toFixed(2) : "—"}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono-tabular font-semibold text-sky-300">
                                {v.score !== null ? v.score.toFixed(3) : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </div>
              )}

              {/* Live Pair Comparison Deltas from /api/comparisons when indexed */}
              {(comparisonBusy || comparison) && (
                <section className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-4 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="font-display text-sm font-medium text-slate-100 inline-flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-amber-300" />
                      Pair comparison & explicit data gaps
                    </h3>
                    {comparisonBusy && <span className="text-[11px] text-slate-400">Loading comparison…</span>}
                  </div>
                  {comparison && (
                    <>
                      {comparison.terrain_measurement_differences.length > 0 && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                          {comparison.terrain_measurement_differences.map((d) => (
                            <div key={d.name} className="rounded-lg border border-white/8 bg-[#0f1621] p-3 text-xs">
                              <div className="font-medium text-slate-200 capitalize">{d.name.replaceAll("_", " ")}</div>
                              <div className="mt-1 font-mono-tabular text-slate-300">
                                {bodyLabel}: {d.query_value.toFixed(2)} {d.units} · Earth: {d.candidate_value.toFixed(2)} {d.units}
                              </div>
                              <div className="mt-0.5 text-[11px] text-slate-400">
                                Δ (Earth − Query): {(d.difference_candidate_minus_query >= 0 ? "+" : "") + d.difference_candidate_minus_query.toFixed(2)} {d.units} · scale {Math.round(d.query_scale_m)} m
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="text-[11px] text-slate-400">
                        <span className="font-medium text-slate-300">Unobserved / missing layers: </span>
                        {comparison.data_gaps.join(", ")}.
                      </div>
                    </>
                  )}
                </section>
              )}

              {/* Environmental & Geological Context + Provisional Mission Checks */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(envEvidence || geoEvidence) && (
                  <section className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-4 space-y-3">
                    <h3 className="font-display text-sm font-medium text-slate-100">Environmental & geological context</h3>
                    {envEvidence && (
                      <div className="rounded-lg border border-white/8 bg-[#0f1621] p-3 space-y-1 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-mono-tabular uppercase text-slate-400">
                            {envEvidence.body === "moon" ? "LRO Diviner nighttime temperature" : "MGS TES thermal inertia"}
                          </span>
                          <a href={envEvidence.label_url} target="_blank" rel="noreferrer" className="text-[10px] text-sky-400 inline-flex items-center gap-0.5">
                            {envEvidence.product_id} <ArrowUpRight className="w-3 h-3" />
                          </a>
                        </div>
                        <div className="font-mono-tabular text-sm font-semibold text-slate-100">
                          Median {envEvidence.summary.median.toFixed(1)} {envEvidence.units} (P10–P90: {envEvidence.summary.p10.toFixed(1)}–{envEvidence.summary.p90.toFixed(1)})
                        </div>
                        <p className="text-[11px] text-slate-400">
                          {envEvidence.source_description} Valid cells: {(envEvidence.valid_sample_fraction * 100).toFixed(1)}%. Excluded from terrain score.
                        </p>
                      </div>
                    )}
                    {geoEvidence && (
                      <div className="rounded-lg border border-white/8 bg-[#0f1621] p-3 space-y-1 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-mono-tabular uppercase text-slate-400">USGS regional map unit</span>
                          <a href={geoEvidence.dataset_reference_url} target="_blank" rel="noreferrer" className="text-[10px] text-sky-400 inline-flex items-center gap-0.5">
                            {geoEvidence.product_id} <ArrowUpRight className="w-3 h-3" />
                          </a>
                        </div>
                        <div className="font-medium text-slate-100">
                          {geoEvidence.classification_status === "mapped"
                            ? [geoEvidence.map_unit_code, geoEvidence.map_unit_name, geoEvidence.map_unit_age].filter(Boolean).join(" · ")
                            : geoEvidence.classification_status.replaceAll("_", " ")}
                        </div>
                        <p className="text-[11px] text-slate-400">
                          {geoEvidence.map_unit_description ?? geoEvidence.source_description} Scale: {geoEvidence.nominal_cartographic_scale}.
                        </p>
                      </div>
                    )}
                  </section>
                )}

                <section className={"rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-4 space-y-3 " + (!envEvidence && !geoEvidence ? "md:col-span-2" : "")}>
                  <h3 className="font-display text-sm font-medium text-slate-100">Mission suitability & physical limits ({equipTitle})</h3>
                  {site?.mission_suitability.checks.map((check) => (
                    <div key={check.name} className="rounded-lg border border-white/8 bg-[#0f1621] p-3 text-xs space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium capitalize text-slate-200">{check.name.replaceAll("_", " ")}</span>
                        <span className={"inline-flex items-center gap-1 font-mono-tabular text-[11px] " + (check.status === "within_screen" ? "text-emerald-300" : check.status === "outside_screen" ? "text-rose-300" : "text-amber-300")}>
                          {check.status === "within_screen" ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                          {check.value !== null ? check.value.toFixed(2) + " " + check.units : "Unavailable"} (limit {check.maximum} {check.units})
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400">{check.basis}</p>
                      {check.basis_source_url && (
                        <a href={check.basis_source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[10px] text-sky-400">
                          Engineering reference <ArrowUpRight className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  ))}

                  <div className="rounded-lg border-l-2 border-amber-400/70 bg-amber-500/8 p-3 text-xs space-y-1.5">
                    <div className="font-medium text-amber-200 flex items-center gap-1.5">
                      <Info className="w-3.5 h-3.5 shrink-0" />
                      Where Earth analogues break down
                    </div>
                    <p className="text-[11px] text-slate-300 leading-relaxed">
                      {target.body === "mars" ? equipment.earthAnalogueLimits.mars : equipment.earthAnalogueLimits.moon}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      Unscored factors for {equipTitle.toLowerCase()}: {equipment.unscoredGaps.join("; ")}.
                    </p>
                  </div>
                </section>
              </div>

              {/* Provenance, Coverage & Limitations */}
              <section className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-4 space-y-2 text-[11px] text-slate-400">
                <div className="font-medium text-slate-200">Evidence completeness, uncertainty & citations</div>
                {site && (
                  <p>
                    Observation support: {site.data_coverage.status === "partial"
                      ? site.data_coverage.observed_cell_count + "/" + site.data_coverage.grid_cell_count + " bins (" + ((site.data_coverage.observed_cell_fraction ?? 0) * 100).toFixed(1) + "%)"
                      : site.data_coverage.note}{" "}
                    {site.data_quality}
                  </p>
                )}
                {sc?.source.direct_srtm_source_fraction !== null && sc?.source.direct_srtm_source_fraction !== undefined && (
                  <p>Earth NASADEM direct SRTM-class fraction: {(sc.source.direct_srtm_source_fraction * 100).toFixed(1)}%.</p>
                )}
                {(scorecard?.limitations ?? comparison?.limitations ?? []).map((item) => (
                  <p key={item}>• {item}</p>
                ))}
                <div className="pt-1 flex flex-wrap gap-4">
                  {site?.source.label_url && (
                    <a href={site.source.label_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300">
                      NASA PDS product label <ArrowUpRight className="w-3 h-3" />
                    </a>
                  )}
                  {site?.source.support_url && (
                    <a href={site.source.support_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300">
                      MOLA count product <ArrowUpRight className="w-3 h-3" />
                    </a>
                  )}
                  <a href="/api/docs" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-slate-300 hover:text-white">
                    FastAPI schema (/api/docs) <ArrowUpRight className="w-3 h-3" />
                  </a>
                </div>
              </section>
            </div>
          </Dialog.Popup>
        </div>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
