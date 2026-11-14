import { AlertTriangle, ArrowUpRight, CheckCircle2, Info, Layers, Sparkles } from "lucide-react";
import type {
  CatalogueEntry,
  EarthCandidate,
  EquipmentId,
  PlanetaryTarget,
  ScorecardResult,
  SearchResponse,
} from "../types";
import { formatCoords, getEquipmentProfile, humanizeGroup } from "../lib/missions";

type EarthAnalogueSidebarProps = {
  selectedTarget: PlanetaryTarget | null;
  equipmentId: EquipmentId;
  scorecard: ScorecardResult | null;
  searchResponse: SearchResponse | null;
  earthCandidates: EarthCandidate[];
  earthCatalogue: CatalogueEntry[];
  selectedEarthId: string | null;
  busy: boolean;
  error: string;
  onSelectEarthCandidate: (candidate: EarthCandidate, openComparison: boolean) => void;
  onSelectCatalogueEarth: (entry: CatalogueEntry) => void;
  onJumpToIngested: () => void;
  className?: string;
};

export function EarthAnalogueSidebar({
  selectedTarget,
  equipmentId,
  scorecard,
  searchResponse,
  earthCandidates,
  earthCatalogue,
  selectedEarthId,
  busy,
  error,
  onSelectEarthCandidate,
  onSelectCatalogueEarth,
  onJumpToIngested,
  className = "",
}: EarthAnalogueSidebarProps) {
  const equipment = getEquipmentProfile(equipmentId);
  const activeSite = scorecard?.site;
  const siteScreening = activeSite?.mission_suitability;
  const envEvidence = activeSite?.environmental_evidence ?? selectedTarget?.scorecardSite?.environmental_evidence;
  const geoEvidence = activeSite?.geology_evidence ?? selectedTarget?.scorecardSite?.geology_evidence;

  const screeningBadge =
    siteScreening?.status === "provisional_pass"
      ? { label: "Provisional pass", cls: "text-emerald-300 bg-emerald-500/12 border-emerald-500/30" }
      : siteScreening?.status === "provisional_concern"
        ? { label: "Provisional concern", cls: "text-rose-300 bg-rose-500/12 border-rose-500/30" }
        : { label: "Insufficient DEM data", cls: "text-amber-300 bg-amber-500/12 border-amber-500/30" };

  return (
    <aside className={"flex flex-col rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] overflow-hidden " + className}>
      <div className="px-4 pt-3.5 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-sky-400">
              Earth analogue matches
            </span>
            <h2 className="font-display text-sm font-semibold text-slate-100 truncate">
              {selectedTarget ? selectedTarget.name : "Select a planetary target"}
            </h2>
          </div>
          {earthCandidates.length > 0 && (
            <span className="font-mono-tabular text-xs text-sky-400 shrink-0">{earthCandidates.length} ranked</span>
          )}
        </div>

        {selectedTarget && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="font-mono-tabular text-slate-400">
              {formatCoords(selectedTarget.latitude_deg, selectedTarget.longitude_east_deg, selectedTarget.body)}
            </span>
            {siteScreening && (
              <span className={"inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-medium " + screeningBadge.cls}>
                {siteScreening.status === "provisional_pass" ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                {screeningBadge.label}
              </span>
            )}
          </div>
        )}

        {(envEvidence || geoEvidence) && (
          <div className="mt-2 grid gap-1.5 text-[11px]">
            {envEvidence && (
              <div className="rounded-lg border border-white/10 bg-[#0b1017] px-2.5 py-1.5 flex items-center justify-between gap-2">
                <span className="text-slate-400 truncate">
                  {envEvidence.body === "moon" ? "Diviner nightside temp" : "TES thermal inertia"}
                </span>
                <span className="font-mono-tabular text-slate-100 font-medium shrink-0">
                  {envEvidence.summary.median.toFixed(1)} {(envEvidence.measurement?.units ?? envEvidence.units).split(";")[0]}
                </span>
              </div>
            )}
            {geoEvidence && (
              <div className="rounded-lg border border-white/10 bg-[#0b1017] px-2.5 py-1.5 flex items-center justify-between gap-2">
                <span className="text-slate-400 truncate">USGS geologic unit</span>
                <span className="font-mono-tabular text-slate-100 font-medium truncate">
                  {geoEvidence.classification_status === "mapped"
                    ? [geoEvidence.map_unit_code, geoEvidence.map_unit_name].filter(Boolean).join(" · ")
                    : geoEvidence.classification_status.replaceAll("_", " ")}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="scroll-contain flex-1 min-h-0 overflow-y-auto">
        {error && (
          <div className="m-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">{error}</div>
        )}

        {busy && (
          <div className="p-6 flex items-center justify-center gap-2 text-xs text-slate-400">
            <span className="w-4 h-4 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
            Computing ENOM ranking…
          </div>
        )}

        {!busy && selectedTarget?.tier === "catalogue_only" && (
          <div className="p-4 space-y-3">
            <div className="rounded-xl border border-amber-500/25 bg-amber-500/8 p-3.5 space-y-2">
              <div className="flex items-start gap-2">
                <Info className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" />
                <div className="text-xs text-slate-200 space-y-1">
                  <p className="font-medium text-amber-200">Reference target · DEM & imagery not yet ingested</p>
                  <p className="text-slate-300 leading-relaxed">{selectedTarget.catalogueEntry?.basis}</p>
                </div>
              </div>
              {selectedTarget.catalogueEntry?.dataset_refs.length ? (
                <div className="pt-1 text-[11px] text-slate-400">
                  Required products: {selectedTarget.catalogueEntry.dataset_refs.join(", ")}
                </div>
              ) : null}
              <div className="pt-1 flex flex-wrap items-center gap-2">
                {selectedTarget.catalogueEntry?.source_url && (
                  <a
                    href={selectedTarget.catalogueEntry.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] font-medium text-sky-400 hover:text-sky-300"
                  >
                    NASA source reference
                    <ArrowUpRight className="w-3 h-3" />
                  </a>
                )}
                <button
                  type="button"
                  onClick={onJumpToIngested}
                  className="pressable ml-auto rounded-lg bg-white/10 hover:bg-white/15 px-2.5 py-1 text-[11px] font-medium text-slate-100"
                >
                  Open ingested {selectedTarget.body === "moon" ? "Moon" : "Mars"} site
                </button>
              </div>
            </div>
          </div>
        )}

        {!busy && earthCandidates.length > 0 && (
          <div className="divide-y divide-[var(--border-subtle)]">
            {earthCandidates.map((candidate, idx) => {
              const isSelected = candidate.id === selectedEarthId;
              const sc = candidate.scorecardCandidate;
              const sr = candidate.searchResult;
              const scoreVal = sc?.similarity_score ?? sr?.combined_score ?? sr?.terrain_similarity ?? null;
              const visualVal = sr?.cosine_similarity ?? null;
              const completeness = sc ? Math.round(sc.data_completeness * 100) : null;

              return (
                <div
                  key={candidate.id}
                  className={"p-3.5 transition-colors " + (isSelected ? "bg-[#142030]" : "hover-surface")}
                  style={isSelected ? { boxShadow: "inset 2px 0 0 var(--earth)" } : undefined}
                >
                  <div className="flex items-start gap-2.5">
                    {candidate.pilotRegion ? (
                      <img
                        src={candidate.pilotRegion.image_url}
                        alt=""
                        loading="lazy"
                        className="w-12 h-12 rounded-lg object-cover bg-[#0a0e15] border border-white/10 shrink-0"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-lg bg-[#0a0e15] border border-white/10 flex items-center justify-center shrink-0">
                        <Layers className="w-4 h-4 text-slate-500" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono-tabular text-[10px] uppercase tracking-[0.06em] text-slate-400">
                          #{candidate.rank ?? idx + 1} · {sc?.source.dataset_id === "nasadem-hgt" ? "NASADEM" : sc ? "Copernicus GLO-30" : "Sentinel-2"}
                        </span>
                        {scoreVal !== null ? (
                          <span className="font-mono-tabular text-xs font-semibold text-sky-300">{scoreVal.toFixed(3)}</span>
                        ) : visualVal !== null ? (
                          <span className="font-mono-tabular text-xs font-semibold text-amber-300">{visualVal.toFixed(3)} cos</span>
                        ) : null}
                      </div>
                      <h3 className="text-[13px] font-medium text-slate-100 truncate mt-0.5">{candidate.regionLabel}</h3>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-slate-400">
                        <span className="font-mono-tabular truncate">
                          {formatCoords(candidate.latitude_deg, candidate.longitude_east_deg, "earth")}
                        </span>
                        {completeness !== null && (
                          <span className="font-mono-tabular text-[10px] text-slate-400 shrink-0">{completeness}% vars</span>
                        )}
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                        {sc && (
                          <span className="rounded bg-sky-500/12 border border-sky-500/25 px-1.5 py-0.5 font-mono-tabular text-sky-300">
                            Terrain {sc.similarity_score !== null ? sc.similarity_score.toFixed(3) : "n/a"}
                          </span>
                        )}
                        {visualVal !== null && (
                          <span className="inline-flex items-center gap-1 rounded bg-white/6 border border-white/10 px-1.5 py-0.5 font-mono-tabular text-slate-300">
                            <Sparkles className="w-2.5 h-2.5 text-amber-300" />
                            DINOv2 {visualVal.toFixed(3)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="mt-2.5 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onSelectEarthCandidate(candidate, false)}
                      className="pressable flex-1 rounded-lg border border-[var(--border-subtle)] bg-[#0b1017] hover:bg-[#141c27] px-2.5 py-1.5 text-[11px] font-medium text-slate-200"
                    >
                      Focus Earth globe
                    </button>
                    <button
                      type="button"
                      onClick={() => onSelectEarthCandidate(candidate, true)}
                      className="pressable flex-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/35 px-2.5 py-1.5 text-[11px] font-medium text-sky-200 inline-flex items-center justify-center gap-1"
                    >
                      Compare & scorecard
                      <ArrowUpRight className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {earthCatalogue.length > 0 && (
          <div className="border-t border-[var(--border-subtle)] bg-[#0b1017]/60 p-3.5 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-slate-400">
                NASA/USGS Earth catalogue ({earthCatalogue.length})
              </span>
              <span className="text-[10px] text-slate-500">Unscored reference</span>
            </div>
            <div className="space-y-1.5">
              {earthCatalogue.map((entry) => {
                const isSelected = selectedEarthId === entry.id;
                return (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => onSelectCatalogueEarth(entry)}
                    className={"pressable w-full text-left rounded-lg border px-2.5 py-2 transition-colors " + (isSelected ? "border-sky-400/40 bg-[#142030]" : "border-[var(--border-subtle)] bg-[#0f141c] hover-surface")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-200 truncate">{entry.name}</span>
                      <span className="font-mono-tabular text-[10px] text-slate-400 shrink-0">
                        {formatCoords(entry.latitude_deg, entry.longitude_east_deg, "earth")}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">
                      {humanizeGroup(entry.candidate_type)} · {entry.dataset_refs[0] ?? "Sourced reference"}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-[var(--border-subtle)] bg-[#0c1118] px-4 py-2.5 text-[11px] text-slate-400">
        <div className="flex items-center justify-between gap-2 text-slate-300 font-medium">
          <span>{equipment.name} focus</span>
          <span className="text-[10px] font-mono-tabular text-slate-500">
            {searchResponse ? "Pilot-100 + DEM" : "Copernicus GLO-30"}
          </span>
        </div>
        <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">{equipment.objectiveNote}</p>
      </div>
    </aside>
  );
}
