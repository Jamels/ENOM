import { Dialog } from "@base-ui/react/dialog";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ImageOff,
  Info,
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
import { planetaryColor, planetarySourceStyle } from "../planetaryTokens";

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

const VARIABLE_EXPLANATIONS: Record<string, string> = {
  elevation_range: "Highest minus lowest measured elevation across the ~10 km context; a broad relief measure.",
  mean_slope: "Average steepness across the DEM context; useful as a broad terrain descriptor.",
  slope_p90: "Steepness below which 90% of sampled cells fall; highlights steeper terrain without using only the maximum.",
  median_local_relief_3x3: "Median height range in 3×3-cell windows; describes nearby height changes at the grid’s scale.",
  median_roughness_3x3: "Median absolute deviation from each 3×3-cell mean; a project-specific roughness descriptor.",
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
      })) ?? [];

  const targetImageUrl = target.pilotRegion?.image_url ?? null;
  const earthImageUrl = earthCandidate.pilotRegion?.image_url ?? sr?.image_url ?? null;
  const bodyAccent = planetaryColor(target.body);
  const earthAccent = planetaryColor("earth");
  const bodySourceStyle = planetarySourceStyle(target.body);
  const earthSourceStyle = planetarySourceStyle("earth");
  const bodyLabel = target.body === "mars" ? "Mars" : "Moon";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop fixed inset-0 z-50 bg-black/75 backdrop-blur-xs" />
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6 scroll-contain">
          <Dialog.Popup className="dialog-popup relative w-full max-w-5xl rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] text-[var(--text-primary)] shadow-2xl overflow-hidden my-auto">
            <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-6 py-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
                  <span style={{ color: bodyAccent }}>{bodyLabel}</span>
                  <span>↔</span>
                  <span className="planetary-source" style={earthSourceStyle}>Earth</span>
                  <span>·</span>
                  <span>{equipTitle}</span>
                  {sc && <span className="font-mono-tabular">· Rank #{sc.rank}</span>}
                </div>
                <Dialog.Title className="font-display text-lg sm:text-xl font-medium tracking-[-0.02em] text-[var(--text-primary)] mt-1">
                  {target.name} ↔ {earthCandidate.regionLabel}
                </Dialog.Title>
              </div>
              <Dialog.Close
                aria-label="Close comparison"
                className="pressable shrink-0 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-2 text-[var(--text-secondary)] hover-surface"
              >
                <X className="w-4 h-4" strokeWidth={1.5} />
              </Dialog.Close>
            </div>

            <div className="p-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] overflow-hidden">
                  <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs" style={{ color: bodyAccent }}>{bodyLabel}</div>
                      <div className="text-sm font-medium text-[var(--text-primary)] truncate">{target.name}</div>
                    </div>
                    <span className="font-mono-tabular text-xs text-[var(--text-muted)] shrink-0">
                      {formatCoords(target.latitude_deg, target.longitude_east_deg, target.body)}
                    </span>
                  </div>
                  {targetImageUrl ? (
                    <div className="relative aspect-[16/10] bg-black">
                      <img
                        src={targetImageUrl}
                        alt={target.name + " surface image"}
                        className="w-full h-full object-cover"
                      />
                      <span className="absolute bottom-2 left-2 rounded-md bg-black/75 px-2 py-1 text-xs font-mono-tabular text-[var(--text-primary)] border border-white/10">
                        MRO CTX · {Number(target.pilotRegion?.native_resolution_m ?? 0).toFixed(1)} m/px
                      </span>
                    </div>
                  ) : (
                    <div className="aspect-[16/10] bg-[var(--bg-void)] flex flex-col items-center justify-center p-6 text-center border-b border-[var(--border-subtle)]">
                      <ImageOff className="w-5 h-5 text-[var(--text-muted)] mb-2" strokeWidth={1.5} />
                      <p className="text-xs font-medium text-[var(--text-secondary)]">Optical crop not indexed</p>
                      <p className="text-xs text-[var(--text-muted)] mt-1 max-w-xs">
                        {target.body === "moon" ? "LRO LOLA DEM and Diviner thermal data indexed" : "Outside Pilot-100 imagery"}
                      </p>
                    </div>
                  )}
                  <div className="px-4 py-3 text-xs text-[var(--text-muted)] flex items-center justify-between gap-2">
                    <span className="font-mono-tabular truncate">
                      {site ? site.source.dataset_id + " · " + site.source.product_id : target.id}
                    </span>
                    {(site?.source.url || target.pilotRegion?.source_url) && (
                      <a
                        href={site?.source.url ?? target.pilotRegion?.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="planetary-source inline-flex items-center gap-1 shrink-0"
                        style={bodySourceStyle}
                      >
                        Source <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                      </a>
                    )}
                  </div>
                </section>

                <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] overflow-hidden">
                  <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs planetary-source" style={earthSourceStyle}>Earth</div>
                      <div className="text-sm font-medium text-[var(--text-primary)] truncate">{earthCandidate.regionLabel}</div>
                    </div>
                    <span className="font-mono-tabular text-xs text-[var(--text-muted)] shrink-0">
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
                      <span className="absolute bottom-2 left-2 rounded-md bg-black/75 px-2 py-1 text-xs font-mono-tabular text-[var(--text-primary)] border border-white/10">
                        Sentinel-2 · {Number(earthCandidate.pilotRegion?.native_resolution_m ?? 10).toFixed(1)} m/px
                      </span>
                    </div>
                  ) : (
                    <div className="aspect-[16/10] bg-[var(--bg-void)] flex flex-col items-center justify-center p-6 text-center border-b border-[var(--border-subtle)]">
                      <ImageOff className="w-5 h-5 text-[var(--text-muted)] mb-2" strokeWidth={1.5} />
                      <p className="text-xs font-medium text-[var(--text-secondary)]">Reference site · imagery not indexed</p>
                    </div>
                  )}
                  <div className="px-4 py-3 text-xs text-[var(--text-muted)] flex items-center justify-between gap-2">
                    <span className="font-mono-tabular truncate">
                      {sc ? sc.source.dataset_id + " · " + sc.source.product_id : earthCandidate.catalogueEntry?.dataset_refs[0] ?? "Sentinel-2 L2A"}
                    </span>
                    {(sc?.source.documentation_url || sc?.source.url || earthCandidate.pilotRegion?.source_url || earthCandidate.catalogueEntry?.source_url) && (
                      <a
                        href={sc?.source.documentation_url ?? sc?.source.url ?? earthCandidate.pilotRegion?.source_url ?? earthCandidate.catalogueEntry?.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="planetary-source inline-flex items-center gap-1 shrink-0"
                        style={earthSourceStyle}
                      >
                        Source <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                      </a>
                    )}
                  </div>
                </section>
              </div>

              <section aria-label="How to read this comparison" className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-3">
                  <div>
                    <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">How to read these scores</h3>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3">
                      <div className="font-medium text-[var(--text-primary)]">Terrain similarity · 0–1</div>
                      <p className="mt-1 text-[var(--text-secondary)]">A weighted ranking index using measurements with matching units and similar spatial scales; not a probability.</p>
                    </div>
                    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3">
                      <div className="font-medium text-[var(--text-primary)]">Image comparison</div>
                      <p className="mt-1 text-[var(--text-secondary)]">Ranks image features; lighting and resolution differences can skew results.</p>
                    </div>
                    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3">
                      <div className="font-medium text-[var(--text-primary)]">Mission screen · separate check</div>
                      <p className="mt-1 text-[var(--text-secondary)]">Checks terrain against provisional limits; it does not establish mission safety.</p>
                    </div>
                  </div>
                  <p className="text-[14.3px] leading-relaxed text-[var(--text-muted)]">Missing or incompatible measurements are omitted, not treated as zero.</p>
              </section>

              {(sc || sr) && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4">
                    <div className="text-xs text-[var(--text-muted)]">Terrain similarity · ranking index</div>
                    <div className="mt-1 font-display text-2xl font-medium font-mono-tabular text-[var(--text-primary)]">
                      {sc?.similarity_score !== null && sc?.similarity_score !== undefined
                        ? sc.similarity_score.toFixed(3)
                        : sr?.terrain_similarity !== null && sr?.terrain_similarity !== undefined
                          ? sr.terrain_similarity.toFixed(3)
                          : "Unavailable"}
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-1 font-mono-tabular">
                      {sc ? sc.matched_variable_count + "/" + sc.requested_variable_count + " variables · " + Math.round(sc.data_completeness * 100) + "%" : "Scale-matched terrain"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4">
                    <div className="text-xs text-[var(--text-muted)]">Image similarity · DINOv2 cosine</div>
                    <div className="mt-1 font-display text-2xl font-medium font-mono-tabular text-[var(--text-primary)]">
                      {sr ? sr.cosine_similarity.toFixed(4) : "Not indexed"}
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-1 font-mono-tabular">
                      {sr ? "Visual rank #" + (sr.visual_rank ?? sr.rank) : target.body === "moon" ? "Moon outside Pilot-100" : "No Pilot-100 pair"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4">
                    <div className="text-xs text-[var(--text-muted)]">Target mission screen</div>
                    <div className="mt-1 font-display text-xl font-medium capitalize text-[var(--text-primary)]">
                      {site ? site.mission_suitability.status.replaceAll("_", " ") : "Not assessed"}
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-1 truncate">
                      {sc?.why_ranked[0] ?? "Provisional terrain screen"}
                    </p>
                  </div>
                </div>
              )}

              {sc && (
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                  <section className="lg:col-span-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">Variable similarity</h3>
                      <span className="text-xs font-mono-tabular text-[var(--text-muted)]">0–100%</span>
                    </div>
                    <div className="h-[220px] w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
                          <CartesianGrid stroke="rgba(238,240,245,0.08)" horizontal={false} />
                          <XAxis type="number" domain={[0, 100]} tick={{ fill: "#7a8296", fontSize: 14.3 }} unit="%" />
                          <YAxis type="category" dataKey="name" width={96} tick={{ fill: "#a3a9b8", fontSize: 15.6 }} />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "#11141c",
                              border: "1px solid rgba(238,240,245,0.16)",
                              borderRadius: "8px",
                              fontSize: "15.6px",
                              color: "#eef0f5",
                            }}
                            formatter={(_value, _name, props) => {
                              const item = props.payload;
                              if (!item.available) return ["Unavailable", "Status"];
                              return [item.rawScore.toFixed(3) + " (" + item.scorePct + "%)", "Score"];
                            }}
                          />
                          <Bar dataKey="scorePct" radius={[0, 4, 4, 0]} barSize={16}>
                            {chartData.map((entry, index) => (
                              <Cell key={index} fill={entry.available ? "#a3a9b8" : "#242936"} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </section>

                  <section className="lg:col-span-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] overflow-hidden">
                    <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
                      <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">Terrain measurements</h3>
                      <span className="text-xs font-mono-tabular text-[var(--text-muted)]">Scale ≤5%</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-[var(--bg-elevated)] text-[var(--text-muted)]">
                          <tr>
                            <th className="px-4 py-2 font-medium">Variable</th>
                            <th className="px-3 py-2 font-medium text-right" style={{ color: bodyAccent }}>{bodyLabel}</th>
                            <th className="px-3 py-2 font-medium text-right" style={{ color: earthAccent }}>Earth</th>
                            <th className="px-3 py-2 font-medium text-right">Delta</th>
                            <th className="px-4 py-2 font-medium text-right">Score</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border-subtle)]">
                          {sc.variables.map((v) => (
                            <tr key={v.name}>
                              <td className="px-4 py-3">
                                <div className="font-medium text-[var(--text-primary)]">{SHORT_VARIABLE_LABELS[v.name] ?? v.label}</div>
                                <div className="mt-1 max-w-48 leading-relaxed text-[var(--text-muted)]">{VARIABLE_EXPLANATIONS[v.name] ?? "A derived terrain descriptor from the available elevation data."}</div>
                                <div className="text-xs text-[var(--text-muted)] font-mono-tabular">
                                  w={v.weight.toFixed(2)} · ±{v.tolerance} {v.units}
                                </div>
                              </td>
                              <td className="px-3 py-3 text-right font-mono-tabular" style={{ color: bodyAccent }}>
                                {v.reference_value !== null ? v.reference_value.toFixed(2) + " " + v.units : "—"}
                              </td>
                              <td className="px-3 py-3 text-right font-mono-tabular" style={{ color: earthAccent }}>
                                {v.earth_value !== null ? v.earth_value.toFixed(2) + " " + v.units : "—"}
                              </td>
                              <td className="px-3 py-3 text-right font-mono-tabular text-[var(--text-muted)]">
                                {v.difference !== null ? (v.difference >= 0 ? "+" : "") + v.difference.toFixed(2) : "—"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono-tabular font-medium text-[var(--text-secondary)]">
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

              {(comparisonBusy || comparison) && (
                <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">Pair deltas & gaps</h3>
                    {comparisonBusy && <span className="text-xs text-[var(--text-muted)]">Loading</span>}
                  </div>
                  {comparison && (
                    <>
                      {comparison.terrain_measurement_differences.length > 0 && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {comparison.terrain_measurement_differences.map((d) => (
                            <div key={d.name} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-xs">
                              <div className="font-medium text-[var(--text-primary)] capitalize">{d.name.replaceAll("_", " ")}</div>
                              <div className="mt-1 font-mono-tabular text-[var(--text-secondary)]">
                                {bodyLabel} {d.query_value.toFixed(2)} {d.units} · Earth {d.candidate_value.toFixed(2)} {d.units} · Δ {(d.difference_candidate_minus_query >= 0 ? "+" : "") + d.difference_candidate_minus_query.toFixed(2)}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="text-xs text-[var(--text-muted)]">
                        Unobserved layers: {comparison.data_gaps.join(", ")}.
                      </div>
                    </>
                  )}
                </section>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(envEvidence || geoEvidence) && (
                  <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-3">
                    <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">Environmental & geology context</h3>
                    {envEvidence && (
                      <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-1 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[var(--text-muted)]">
                            {envEvidence.body === "moon" ? "LRO Diviner night temperature" : "MGS TES thermal inertia"}
                          </span>
                          <a href={envEvidence.label_url} target="_blank" rel="noreferrer" className="planetary-source inline-flex items-center gap-1" style={bodySourceStyle}>
                            {envEvidence.product_id} <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                          </a>
                        </div>
                        <div className="font-mono-tabular text-sm font-medium text-[var(--text-primary)]">
                          Median {envEvidence.summary.median.toFixed(1)} {(envEvidence.measurement?.units ?? envEvidence.units).split(";")[0]} · P10–P90 {envEvidence.summary.p10.toFixed(1)}–{envEvidence.summary.p90.toFixed(1)}
                        </div>
                      </div>
                    )}
                    {geoEvidence && (
                      <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-1 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[var(--text-muted)]">USGS regional unit</span>
                          <a href={geoEvidence.dataset_reference_url} target="_blank" rel="noreferrer" className="planetary-source inline-flex items-center gap-1" style={bodySourceStyle}>
                            {geoEvidence.product_id} <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                          </a>
                        </div>
                        <div className="font-medium text-[var(--text-primary)]">
                          {geoEvidence.classification_status === "mapped"
                            ? [geoEvidence.map_unit_code, geoEvidence.map_unit_name, geoEvidence.map_unit_age].filter(Boolean).join(" · ")
                            : geoEvidence.classification_status.replaceAll("_", " ")}
                        </div>
                      </div>
                    )}
                  </section>
                )}

                <section className={"rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-3 " + (!envEvidence && !geoEvidence ? "md:col-span-2" : "")}>
                  <h3 className="font-display text-sm font-medium text-[var(--text-primary)]">Mission suitability ({equipTitle})</h3>
                  {site?.mission_suitability.checks.map((check) => (
                    <div key={check.name} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-xs space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium capitalize text-[var(--text-primary)]">{check.name.replaceAll("_", " ")}</span>
                        <span className={"inline-flex items-center gap-1 font-mono-tabular " + (check.status === "within_screen" ? "text-emerald-400" : check.status === "outside_screen" ? "text-rose-400" : "text-amber-300")}>
                          {check.status === "within_screen" ? <CheckCircle2 className="w-4 h-4" strokeWidth={1.5} /> : <AlertTriangle className="w-4 h-4" strokeWidth={1.5} />}
                          {check.value !== null ? check.value.toFixed(2) + " " + check.units : "Unavailable"} / {check.maximum} {check.units}
                        </span>
                      </div>
                      {check.basis_source_url && (
                        <a href={check.basis_source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                          Engineering reference <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                        </a>
                      )}
                    </div>
                  ))}

                  <div className="rounded-lg border-l-2 border-amber-400/70 bg-[var(--bg-elevated)] p-3 text-xs space-y-1">
                    <div className="font-medium text-amber-300 flex items-center gap-2">
                      <Info className="w-4 h-4 shrink-0" strokeWidth={1.5} />
                      Physical limits on Earth
                    </div>
                    <p className="text-[var(--text-secondary)] leading-relaxed">
                      {target.body === "mars" ? equipment.earthAnalogueLimits.mars : equipment.earthAnalogueLimits.moon}
                    </p>
                  </div>
                </section>
              </div>

              <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-2 text-xs text-[var(--text-muted)]">
                <div className="font-medium text-[var(--text-secondary)]">Provenance & limits</div>
                {site && (
                  <p>
                    {site.data_coverage.status === "partial"
                      ? site.data_coverage.observed_cell_count + "/" + site.data_coverage.grid_cell_count + " MOLA bins (" + ((site.data_coverage.observed_cell_fraction ?? 0) * 100).toFixed(1) + "%). "
                      : ""}
                    {site.data_quality}
                  </p>
                )}
                {(scorecard?.limitations ?? comparison?.limitations ?? []).slice(0, 3).map((item) => (
                  <p key={item}>• {item}</p>
                ))}
                <div className="pt-1 flex flex-wrap gap-4">
                  {site?.source.label_url && (
                    <a href={site.source.label_url} target="_blank" rel="noreferrer" className="planetary-source inline-flex items-center gap-1" style={bodySourceStyle}>
                      PDS label <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                    </a>
                  )}
                  {site?.source.support_url && (
                    <a href={site.source.support_url} target="_blank" rel="noreferrer" className="planetary-source inline-flex items-center gap-1" style={bodySourceStyle}>
                      MOLA counts <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                    </a>
                  )}
                  <a href="/api/docs" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                    API schema <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
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
