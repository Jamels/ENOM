import { useMemo, useState } from "react";
import { ChevronDown, RotateCcw, Search, SlidersHorizontal, X } from "lucide-react";
import type {
  EquipmentId,
  PlanetaryBody,
  PlanetaryTarget,
  ScoreConfig,
} from "../types";
import { formatCoords, getEquipmentProfile } from "../lib/missions";
import { planetarySourceStyle } from "../planetaryTokens";

type FilterMode = "all" | "equipment" | "scorecard" | "imagery" | "catalogue";

type TargetSidebarProps = {
  body: PlanetaryBody;
  targets: PlanetaryTarget[];
  selectedTargetId: string | null;
  equipmentId: EquipmentId;
  searchMethod: "combined" | "terrain" | "visual";
  scoreConfig: ScoreConfig | null;
  weights: Record<string, number>;
  onSelectTarget: (target: PlanetaryTarget) => void;
  onSearchMethodChange: (method: "combined" | "terrain" | "visual") => void;
  onWeightChange: (name: string, value: number) => void;
  onResetWeights: () => void;
  className?: string;
};

const TIER_META: Record<PlanetaryTarget["tier"], { label: string; dotClass: string }> = {
  scorecard_imagery: { label: "DEM + image", dotClass: "bg-emerald-400" },
  scorecard_only: { label: "DEM", dotClass: "bg-sky-400" },
  imagery_only: { label: "Imagery", dotClass: "bg-amber-400" },
  catalogue_only: { label: "Reference", dotClass: "border border-slate-400 bg-transparent" },
};

export function TargetSidebar({
  body,
  targets,
  selectedTargetId,
  equipmentId,
  searchMethod,
  scoreConfig,
  weights,
  onSelectTarget,
  onSearchMethodChange,
  onWeightChange,
  onResetWeights,
  className = "",
}: TargetSidebarProps) {
  const [queryText, setQueryText] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [weightsOpen, setWeightsOpen] = useState(false);

  const equipment = getEquipmentProfile(equipmentId);
  const equipmentLabel = body === "moon" && equipment.moonName ? equipment.moonName : equipment.name;

  const filteredTargets = useMemo(() => {
    const q = queryText.trim().toLowerCase();
    return targets.filter((t) => {
      if (filterMode === "equipment" && !t.equipmentTags.includes(equipmentId)) return false;
      if (filterMode === "scorecard" && t.tier !== "scorecard_imagery" && t.tier !== "scorecard_only") return false;
      if (filterMode === "imagery" && t.tier !== "scorecard_imagery" && t.tier !== "imagery_only") return false;
      if (filterMode === "catalogue" && t.tier !== "catalogue_only") return false;
      if (!q) return true;
      return t.name.toLowerCase().includes(q) || t.subtitle.toLowerCase().includes(q) || t.id.toLowerCase().includes(q);
    });
  }, [targets, queryText, filterMode, equipmentId]);

  const accentColor = body === "mars" ? "var(--planet-mars-primary)" : "var(--planet-moon-primary)";

  return (
    <aside className={"flex flex-col rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] overflow-hidden " + className}>
      <div className="p-4 border-b border-[var(--border-subtle)] space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="inline-flex items-center gap-2 font-display text-sm font-medium" style={{ color: accentColor }}>
            <span aria-hidden="true" className="h-2 w-2 rounded-sm" style={{ backgroundColor: accentColor }} />
            {body === "mars" ? "Mars targets" : "Lunar targets"}
          </h2>
          <span className="font-mono-tabular text-xs text-[var(--text-muted)]">{filteredTargets.length}/{targets.length}</span>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} aria-hidden="true" />
          <input
            type="search"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            placeholder="Search"
            aria-label={"Search " + (body === "mars" ? "Mars" : "Moon") + " targets"}
            className="desktop-compact w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] pl-9 pr-8 py-2 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--border-strong)] focus:outline-none"
          />
          {queryText && (
            <button
              type="button"
              onClick={() => setQueryText("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-4 h-4" strokeWidth={1.5} />
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-1">
          {(
            [
              { id: "all", label: "All" },
              { id: "equipment", label: equipmentLabel },
              { id: "scorecard", label: "Scorecard" },
              ...(body === "mars" ? [{ id: "imagery" as const, label: "Imagery" }] : []),
              { id: "catalogue", label: "Reference" },
            ] as { id: FilterMode; label: string }[]
          ).map((f) => {
            const active = filterMode === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilterMode(f.id)}
                className={"pressable px-2 py-1 rounded-md text-xs font-medium border " + (active ? "bg-[var(--bg-hover)] border-[var(--border-strong)] text-[var(--text-primary)]" : "bg-transparent border-transparent text-[var(--text-muted)] hover-surface")}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="scroll-contain flex-1 min-h-0 overflow-y-auto divide-y divide-[var(--border-subtle)]">
        {filteredTargets.length === 0 ? (
          <div className="p-6 text-center text-xs text-[var(--text-muted)]">No matching targets</div>
        ) : (
          filteredTargets.map((target) => {
            const isSelected = target.id === selectedTargetId;
            const tier = TIER_META[target.tier];
            const provisionalImage = Boolean(target.pilotRegion && target.pilotRegion.label_status !== "verified");
            const tierLabel = provisionalImage
              ? target.tier === "scorecard_imagery" ? "DEM + provisional image" : "Provisional image"
              : tier.label;
            const matchesEquip = target.equipmentTags.includes(equipmentId);
            return (
              <button
                key={target.id}
                type="button"
                onClick={() => onSelectTarget(target)}
                className={"pressable w-full text-left px-4 py-3 flex items-center gap-3 transition-colors " + (isSelected ? "bg-[var(--bg-elevated)]" : "hover-surface")}
                style={isSelected ? { boxShadow: `inset 2px 0 0 ${body === "mars" ? "var(--planet-mars-deep)" : "var(--planet-moon-deep)"}` } : undefined}
              >
                {target.pilotRegion ? (
                  <img
                    src={target.pilotRegion.image_url}
                    alt=""
                    loading="lazy"
                    className="w-9 h-9 rounded-md object-cover bg-[var(--bg-void)] border border-[var(--border-subtle)] shrink-0"
                  />
                ) : (
                  <div className="w-9 h-9 rounded-md bg-[var(--bg-void)] border border-[var(--border-subtle)] flex items-center justify-center shrink-0">
                    <span className={"w-2 h-2 rounded-full " + tier.dotClass} />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[16.9px] font-medium truncate" style={{ color: accentColor }}>
                      {target.name}
                    </span>
                    {matchesEquip && (
                      <span
                        className="shrink-0 w-1.5 h-1.5 rounded-full"
                        style={{ backgroundColor: accentColor }}
                        title={"Relevant to " + equipmentLabel}
                      />
                    )}
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-xs">
                    <span className="font-mono-tabular text-[var(--text-muted)] truncate">
                      {formatCoords(target.latitude_deg, target.longitude_east_deg, body)}
                    </span>
                    <span className="inline-flex items-center gap-1.5 text-[var(--text-secondary)] shrink-0">
                      <span className={"w-1.5 h-1.5 rounded-full " + tier.dotClass} />
                      {tierLabel}
                    </span>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-panel)]">
        <button
          type="button"
          onClick={() => setWeightsOpen((v) => !v)}
          aria-expanded={weightsOpen}
          className="w-full px-4 py-3 flex items-center justify-between gap-2 text-left text-xs text-[var(--text-secondary)] hover-surface"
        >
          <span className="inline-flex items-center gap-2 font-medium">
            <SlidersHorizontal className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
            Weights & retrieval
          </span>
          <ChevronDown className={"w-4 h-4 text-[var(--text-muted)] transition-transform duration-150 " + (weightsOpen ? "rotate-180" : "")} strokeWidth={1.5} />
        </button>
        {weightsOpen && (
          <div className="px-4 pb-4 pt-2 space-y-3 border-t border-[var(--border-subtle)] max-h-[260px] overflow-y-auto scroll-contain">
            {body === "mars" && (
              <div className="space-y-2">
                <span className="block text-xs text-[var(--text-muted)]">Retrieval mode</span>
                <div className="grid grid-cols-3 gap-1 p-1 rounded-lg bg-[var(--bg-void)] border border-[var(--border-subtle)]">
                  {([
                    { id: "combined", label: "Combined" },
                    { id: "terrain", label: "Terrain" },
                    { id: "visual", label: "DINOv2" },
                  ] as const).map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => onSearchMethodChange(mode.id)}
                      className={"py-1 rounded-md text-xs font-medium transition-colors " + (searchMethod === mode.id ? "bg-[var(--bg-hover)] text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]")}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-muted)]">Terrain weights</span>
                <button
                  type="button"
                  onClick={onResetWeights}
                  className="planetary-source inline-flex items-center gap-1 text-xs"
                  style={planetarySourceStyle(body)}
                >
                  <RotateCcw className="w-3.5 h-3.5" strokeWidth={1.5} />
                  Reset
                </button>
              </div>
              <div className="space-y-2">
                {Object.entries(scoreConfig?.variables ?? {}).map(([id, variable]) => (
                  <label key={id} className="block">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)] truncate pr-2">{variable.label}</span>
                      <span className="font-mono-tabular text-[var(--text-primary)] shrink-0">{(weights[id] ?? 0).toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.04"
                      aria-label={variable.label + " weight"}
                      value={weights[id] ?? 0}
                      onChange={(e) => onWeightChange(id, Number(e.target.value))}
                      className="w-full accent-sky-400 h-1.5 mt-1 cursor-pointer"
                    />
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
