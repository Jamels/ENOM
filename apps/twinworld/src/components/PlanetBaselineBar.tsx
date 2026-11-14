import { useState } from "react";
import { ChevronUp, Scale } from "lucide-react";
import type { PlanetaryBody } from "../types";
import { PLANETARY_BASELINE } from "../lib/missions";

export function PlanetBaselineBar({ body }: { body: PlanetaryBody }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0c1118]/90 px-3.5 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
          <span className="inline-flex items-center gap-1.5 font-medium text-slate-200">
            <Scale className="w-3.5 h-3.5 text-slate-400" />
            Physical gap: {body === "mars" ? "Mars" : "Moon"} vs. Earth
          </span>
          <span className="text-slate-400 font-mono-tabular">
            Gravity {body === "mars" ? "38% (3.71 m/s²)" : "17% (1.62 m/s²)"}
          </span>
          <span className="text-slate-400 font-mono-tabular hidden sm:inline">
            Pressure {body === "mars" ? "≈ 6 hPa (<1%)" : "Near vacuum"}
          </span>
          <span className="text-slate-400 font-mono-tabular hidden md:inline">
            Temp {body === "mars" ? "−63 °C avg" : "−173 to +127 °C"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="pressable inline-flex items-center gap-1 text-[11px] font-medium text-sky-400 hover:text-sky-300 shrink-0"
        >
          {expanded ? "Hide table" : "Full baseline"}
          <ChevronUp className={"w-3.5 h-3.5 transition-transform duration-150 " + (expanded ? "" : "rotate-180")} />
        </button>
      </div>

      {expanded && (
        <div className="mt-2.5 pt-2.5 border-t border-[var(--border-subtle)] grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          {PLANETARY_BASELINE.map((row) => (
            <div key={row.label} className="rounded-lg border border-white/6 bg-[#080b10]/70 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-[0.06em] text-slate-500">{row.label}</div>
              <div className="mt-1 text-[11px] font-mono-tabular text-slate-200">
                {body === "mars" ? row.mars : row.moon}
              </div>
              <div className="text-[10px] font-mono-tabular text-sky-400/90">Earth: {row.earth}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
