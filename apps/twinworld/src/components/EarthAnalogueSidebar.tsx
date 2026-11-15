import { ArrowUpRight, Info, Layers } from "lucide-react";
import type {
  CatalogueEntry,
  EarthCandidate,
  EquipmentId,
  PlanetaryTarget,
  ScorecardResult,
  SearchResponse,
} from "../types";
import { formatCoords } from "../lib/missions";
import { CoordinateDiscoveryPanel } from "./CoordinateDiscoveryPanel";
import type { AnalogueProfile, DiscoveryRank, DiscoveryRankRow } from "../lib/api";
import { planetaryColor, planetarySourceStyle } from "../planetaryTokens";

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
  discoveryProfiles: AnalogueProfile[];
  discoveryProfileId: string;
  discoveryWeights: Record<string, number>;
  discoveryResult: DiscoveryRank | null;
  discoveryBusy: boolean;
  discoveryError: string;
  onDiscoveryProfileChange: (id: string) => void;
  onDiscoveryWeightChange: (id: string, value: number) => void;
  onResetDiscoveryWeights: () => void;
  onSelectDiscoveredPlace: (row: DiscoveryRankRow) => void;
  className?: string;
};

export function EarthAnalogueSidebar({
  selectedTarget,
  scorecard,
  searchResponse,
  earthCandidates,
  earthCatalogue,
  selectedEarthId,
  busy,
  error,
  onSelectEarthCandidate,
  onSelectCatalogueEarth,
  discoveryProfiles,
  discoveryProfileId,
  discoveryWeights,
  discoveryResult,
  discoveryBusy,
  discoveryError,
  onDiscoveryProfileChange,
  onDiscoveryWeightChange,
  onResetDiscoveryWeights,
  onSelectDiscoveredPlace,
  className = "",
}: EarthAnalogueSidebarProps) {
  const activeSite = scorecard?.site;
  const siteScreening = activeSite?.mission_suitability;
  const envEvidence = activeSite?.environmental_evidence ?? selectedTarget?.scorecardSite?.environmental_evidence;
  const geoEvidence = activeSite?.geology_evidence ?? selectedTarget?.scorecardSite?.geology_evidence;

  const screeningLabel =
    siteScreening?.status === "provisional_pass"
      ? { text: "Provisional pass", cls: "text-emerald-400" }
      : siteScreening?.status === "provisional_concern"
        ? { text: "Provisional concern", cls: "text-rose-400" }
        : { text: "Insufficient DEM", cls: "text-amber-300" };

  return (
    <aside className={"flex flex-col rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] overflow-hidden " + className}>
      <div className="p-4 border-b border-[var(--border-subtle)] space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="inline-flex items-center gap-2 font-display text-sm font-medium truncate" style={{ color: planetaryColor("earth") }}>
            <span aria-hidden="true" className="h-2 w-2 rounded-sm shrink-0" style={{ backgroundColor: planetaryColor("earth") }} />
            Earth analogues
          </h2>
        </div>

        {selectedTarget && (
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="text-[var(--text-secondary)] truncate">{selectedTarget.name}</span>
            {siteScreening && (
              <span className={"shrink-0 font-medium " + screeningLabel.cls}>{screeningLabel.text}</span>
            )}
          </div>
        )}

        {(envEvidence || geoEvidence) && (
          <div className="pt-1 space-y-1 text-xs">
            {envEvidence && (
              <div className="flex items-center justify-between gap-2 text-[var(--text-muted)]">
                <span>{envEvidence.body === "moon" ? "Diviner night temp" : "TES thermal inertia"}</span>
                <span className="font-mono-tabular text-[var(--text-primary)]">
                  {envEvidence.summary.median.toFixed(1)} {(envEvidence.measurement?.units ?? envEvidence.units).split(";")[0]}
                </span>
              </div>
            )}
            {geoEvidence && (
              <div className="flex items-center justify-between gap-2 text-[var(--text-muted)]">
                <span>USGS geology</span>
                <span className="font-mono-tabular text-[var(--text-primary)] truncate">
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
        <CoordinateDiscoveryPanel
          targetName={selectedTarget?.name ?? null}
          targetBody={selectedTarget?.body ?? null}
          profiles={discoveryProfiles}
          profileId={discoveryProfileId}
          weights={discoveryWeights}
          result={discoveryResult}
          busy={discoveryBusy}
          error={discoveryError}
          onProfileChange={onDiscoveryProfileChange}
          onWeightChange={onDiscoveryWeightChange}
          onResetWeights={onResetDiscoveryWeights}
          onSelectPlace={onSelectDiscoveredPlace}
        />
        {error && (
          <div className="m-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">{error}</div>
        )}

        {busy && (
          <div className="p-6 flex items-center justify-center gap-2 text-xs text-[var(--text-muted)]">
            <span className="w-4 h-4 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
            Ranking Earth sites
          </div>
        )}

        {!busy && selectedTarget?.tier === "catalogue_only" && (
          <div className="p-4">
            <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3">
              <div className="flex items-start gap-2">
                <Info className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" strokeWidth={1.5} />
                <div className="text-xs space-y-1">
                  <p className="font-medium text-[var(--text-primary)]">Candidate place context</p>
                  <p className="text-[var(--text-secondary)] leading-relaxed">{selectedTarget.catalogueEntry?.basis}</p>
                  <p className="text-[var(--text-secondary)] leading-relaxed">Measurement details are in Analogue discovery.</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                {selectedTarget.catalogueEntry?.source_url && (
                  <a
                    href={selectedTarget.catalogueEntry.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="planetary-source inline-flex items-center gap-1 text-xs font-medium"
                    style={selectedTarget ? planetarySourceStyle(selectedTarget.body) : undefined}
                  >
                    Place reference
                    <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {!busy && earthCandidates.length > 0 && (
          <details className="mx-3 mb-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
            <summary className="cursor-pointer px-3 py-2 text-[10px] text-[var(--text-muted)]">Indexed results</summary>
            <div className="divide-y divide-[var(--border-subtle)]">
            {earthCandidates.map((candidate, idx) => {
              const isSelected = candidate.id === selectedEarthId;
              const sc = candidate.scorecardCandidate;
              const sr = candidate.searchResult;
              const scoreVal = sr
                ? searchResponse?.method === "visual"
                  ? sr.cosine_similarity
                  : searchResponse?.method === "terrain"
                    ? sr.terrain_similarity
                    : sr.combined_score ?? sr.cosine_similarity
                : sc?.similarity_score ?? null;
              const visualVal = sr?.cosine_similarity ?? null;
              const completeness = sc ? Math.round(sc.data_completeness * 100) : null;
              const metaParts: string[] = [];
              if (visualVal !== null) metaParts.push("Visual " + visualVal.toFixed(3));
              if (completeness !== null) metaParts.push(completeness + "% vars");
              if (!metaParts.length && sc) metaParts.push(sc.source.dataset_id === "nasadem-hgt" ? "NASADEM" : "Copernicus");

              return (
                <div
                  key={candidate.id}
                  onClick={() => onSelectEarthCandidate(candidate, false)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelectEarthCandidate(candidate, false);
                    }
                  }}
                  className={"p-4 cursor-pointer transition-colors " + (isSelected ? "bg-[var(--bg-elevated)]" : "hover-surface")}
                  style={isSelected ? { boxShadow: "inset 2px 0 0 var(--planet-earth-deep)" } : undefined}
                >
                  <div className="flex items-start gap-3">
                    {candidate.pilotRegion ? (
                      <img
                        src={candidate.pilotRegion.image_url}
                        alt=""
                        loading="lazy"
                        className="w-11 h-11 rounded-lg object-cover bg-[var(--bg-void)] border border-[var(--border-subtle)] shrink-0"
                      />
                    ) : (
                      <div className="w-11 h-11 rounded-lg bg-[var(--bg-void)] border border-[var(--border-subtle)] flex items-center justify-center shrink-0">
                        <Layers className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-medium truncate" style={{ color: planetaryColor("earth") }}>
                          #{candidate.rank ?? idx + 1} {candidate.regionLabel}
                        </span>
                        {scoreVal !== null && (
                          <span className="font-mono-tabular text-xs font-medium text-[var(--text-secondary)] shrink-0">
                            {scoreVal.toFixed(3)}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 font-mono-tabular text-xs text-[var(--text-muted)] truncate">
                        {formatCoords(candidate.latitude_deg, candidate.longitude_east_deg, "earth")}
                      </div>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <span className="font-mono-tabular text-xs text-[var(--text-secondary)] truncate">
                          {metaParts.join(" · ")}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectEarthCandidate(candidate, true);
                          }}
                          className="pressable shrink-0 inline-flex items-center gap-1 rounded-md border border-[var(--border-strong)] bg-[var(--bg-void)] hover:bg-[var(--bg-hover)] px-2 py-1 text-xs font-medium text-[var(--text-primary)]"
                        >
                          Compare
                          <ArrowUpRight className="w-3.5 h-3.5" strokeWidth={1.5} />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            </div>
          </details>
        )}

        {earthCatalogue.length > 0 && (
          <div className="border-t border-[var(--border-subtle)] p-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
              <span>Catalogue reference sites</span>
              <span className="font-mono-tabular">{earthCatalogue.length}</span>
            </div>
            <div className="space-y-1">
              {earthCatalogue.map((entry) => {
                const isSelected = selectedEarthId === entry.id;
                return (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => onSelectCatalogueEarth(entry)}
                    className={"pressable w-full text-left rounded-lg border px-3 py-2 flex items-center justify-between gap-2 transition-colors " + (isSelected ? "border-[var(--border-strong)] bg-[var(--bg-elevated)]" : "border-transparent hover-surface")}
                  >
                    <span className="text-xs font-medium truncate" style={{ color: planetaryColor("earth") }}>{entry.name}</span>
                    <span className="font-mono-tabular text-xs text-[var(--text-muted)] shrink-0">
                      {formatCoords(entry.latitude_deg, entry.longitude_east_deg, "earth")}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
