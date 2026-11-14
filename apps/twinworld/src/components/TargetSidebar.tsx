import { useMemo, useState } from "react";
import { ChevronDown, RotateCcw, Search, SlidersHorizontal, X } from "lucide-react";
import type {
  EquipmentId,
  PlanetaryBody,
  PlanetaryTarget,
  ScoreConfig,
} from "../types";
import { formatCoords, getEquipmentProfile } from "../lib/missions";

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
  scorecard_imagery: { label: "DEM + Imagery", dotClass: "bg-emerald-400" },
  scorecard_only: { label: "DEM Scorecard", dotClass: "bg-sky-400" },
  imagery_only: { label: "DINOv2 Imagery", dotClass: "bg-amber-400" },
  catalogue_only: { label: "NASA Reference", dotClass: "border border-slate-400 bg-transparent" },
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

  const accentColor = body === "mars" ? "var(--mars)" : "var(--moon)";

  return (
    <aside className={"flex flex-col rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] overflow-hidden " + className}>
      <div className="px-4 pt-3.5 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center justify-between gap-2">
          <div>
            <span className="text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-slate-400">
              {body === "mars" ? "Mars" : "Lunar"} regions
            </span>
            <h2 className="font-display text-sm font-semibold text-slate-100">Target Locations</h2>
          </div>
          <span className="font-mono-tabular text-xs text-slate-400">{filteredTargets.length}/{targets.length}</span>
        </div>

        <div className="relative mt-2.5">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          <input
            type="search"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            placeholder={"Search " + (body === "mars" ? "Mars" : "Moon") + " sites…"}
            aria-label={"Search " + (body === "mars" ? "Mars" : "Moon") + " target locations"}
            className="desktop-compact w-full rounded-lg border border-[var(--border-subtle)] bg-[#0a0e15] pl-8 pr-7 py-1.5 text-slate-100 placeholder:text-slate-500 focus:border-[var(--border-strong)] focus:outline-none"
          />
          {queryText && (
            <button
              type="button"
              onClick={() => setQueryText("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-200"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1">
          {(
            [
              { id: "all", label: "All" },
              { id: "equipment", label: equipmentLabel },
              { id: "scorecard", label: "Scorecard" },
              ...(body === "mars" ? [{ id: "imagery" as const, label: "Imagery" }] : []),
              { id: "catalogue", label: "Catalogue" },
            ] as { id: FilterMode; label: string }[]
          ).map((f) => {
            const active = filterMode === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilterMode(f.id)}
                className={"pressable px-2 py-0.5 rounded-md text-[11px] font-medium border " + (active ? "bg-white/10 border-[var(--border-strong)] text-slate-100" : "bg-transparent border-transparent text-slate-400 hover-surface")}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="scroll-contain flex-1 min-h-0 overflow-y-auto divide-y divide-[var(--border-subtle)]">
        {filteredTargets.length === 0 ? (
          <div className="p-5 text-center text-xs text-slate-400">
            No {body === "mars" ? "Mars" : "Moon"} targets match this filter.
          </div>
        ) : (
          filteredTargets.map((target) => {
            const isSelected = target.id === selectedTargetId;
            const tier = TIER_META[target.tier];
            const matchesEquip = target.equipmentTags.includes(equipmentId);
            return (
              <button
                key={target.id}
                type="button"
                onClick={() => onSelectTarget(target)}
                className={"pressable w-full text-left px-4 py-2.5 flex items-start gap-2.5 transition-colors " + (isSelected ? "bg-[#17202e]" : "hover-surface")}
                style={isSelected ? { boxShadow: "inset 2px 0 0 " + accentColor } : undefined}
              >
                {target.pilotRegion ? (
                  <img
                    src={target.pilotRegion.image_url}
                    alt=""
                    loading="lazy"
                    className="w-10 h-10 rounded-md object-cover bg-[#0a0e15] border border-white/10 shrink-0 mt-0.5"
                  />
                ) : (
                  <div className="w-10 h-10 rounded-md bg-[#0a0e15] border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
                    <span className={"w-2 h-2 rounded-full " + tier.dotClass} />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-1.5">
                    <span className="text-[13px] font-medium text-slate-100 truncate">{target.name}</span>
                    {matchesEquip && (
                      <span
                        className="shrink-0 w-1.5 h-1.5 rounded-full"
                        style={{ backgroundColor: accentColor }}
                        title={"Relevant to " + equipmentLabel}
                      />
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 truncate mt-0.5">{target.subtitle}</p>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[10px]">
                    <span className="font-mono-tabular text-slate-500">
                      {formatCoords(target.latitude_deg, target.longitude_east_deg, body)}
                    </span>
                    <span className="inline-flex items-center gap-1 text-slate-400 shrink-0">
                      <span className={"w-1.5 h-1.5 rounded-full " + tier.dotClass} />
                      {tier.label}
                    </span>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div className="border-t border-[var(--border-subtle)] bg-[#0c1118]">
        <button
          type="button"
          onClick={() => setWeightsOpen((v) => !v)}
          aria-expanded={weightsOpen}
          className="w-full px-4 py-2.5 flex items-center justify-between gap-2 text-left text-xs text-slate-300 hover-surface"
        >
          <span className="inline-flex items-center gap-2 font-medium">
            <SlidersHorizontal className="w-3.5 h-3.5 text-slate-400" />
            Scoring weights & retrieval
          </span>
          <ChevronDown className={"w-3.5 h-3.5 text-slate-400 transition-transform duration-150 " + (weightsOpen ? "rotate-180" : "")} />
        </button>
        {weightsOpen && (
          <div className="px-4 pb-3.5 pt-1 space-y-3 border-t border-[var(--border-subtle)] max-h-[260px] overflow-y-auto scroll-contain">
            {body === "mars" && (
              <div>
                <span className="block text-[10px] font-mono-tabular uppercase tracking-[0.06em] text-slate-400 mb-1.5">
                  Pilot-100 retrieval mode
                </span>
                <div className="grid grid-cols-3 gap-1 p-0.5 rounded-lg bg-[#080b10] border border-[var(--border-subtle)]">
                  {([
                    { id: "combined", label: "Combined" },
                    { id: "terrain", label: "Terrain" },
                    { id: "visual", label: "DINOv2" },
                  ] as const).map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => onSearchMethodChange(mode.id)}
                      className={"py-1 rounded-md text-[11px] font-medium transition-colors " + (searchMethod === mode.id ? "bg-[#1b2432] text-slate-100" : "text-slate-400 hover:text-slate-200")}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] font-mono-tabular uppercase tracking-[0.06em] text-slate-400">
                  Terrain variable weights
                </span>
                <button
                  type="button"
                  onClick={onResetWeights}
                  className="inline-flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300"
                >
                  <RotateCcw className="w-2.5 h-2.5" />
                  Reset preset
                </button>
              </div>
              <div className="space-y-2">
                {Object.entries(scoreConfig?.variables ?? {}).map(([id, variable]) => (
                  <label key={id} className="block">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-300 truncate pr-2">{variable.label}</span>
                      <span className="font-mono-tabular text-slate-200 shrink-0">{(weights[id] ?? 0).toFixed(2)}</span>
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
