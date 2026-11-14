import { useState } from "react";
import { ChevronUp, Scale } from "lucide-react";
import type { PlanetaryBody } from "../types";
import { PLANETARY_BASELINE } from "../lib/missions";
import { planetaryColor, planetarySourceStyle } from "../planetaryTokens";

export function PlanetBaselineBar({ body }: { body: PlanetaryBody }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] px-4 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-2 font-medium text-[var(--text-primary)]">
            <Scale className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
            {body === "mars" ? "Mars" : "Moon"} vs. Earth
          </span>
          <span className="text-[var(--text-secondary)] font-mono-tabular">
            {body === "mars" ? "38% g" : "17% g"}
          </span>
          <span className="text-[var(--text-secondary)] font-mono-tabular hidden sm:inline">
            {body === "mars" ? "≈ 6 hPa" : "Vacuum"}
          </span>
          <span className="text-[var(--text-secondary)] font-mono-tabular hidden md:inline">
            {body === "mars" ? "−63 °C avg" : "−173 to +127 °C"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="pressable planetary-source inline-flex items-center gap-1 text-xs font-medium shrink-0"
          style={planetarySourceStyle(body)}
        >
          {expanded ? "Hide" : "Baseline"}
          <ChevronUp className={"w-4 h-4 transition-transform duration-150 " + (expanded ? "" : "rotate-180")} strokeWidth={1.5} />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {PLANETARY_BASELINE.map((row) => (
            <div key={row.label} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] px-3 py-2">
              <div className="text-xs text-[var(--text-muted)]">{row.label}</div>
              <div className="mt-1 text-xs font-mono-tabular" style={{ color: planetaryColor(body) }}>
                {body === "mars" ? row.mars : row.moon}
              </div>
              <div className="text-xs font-mono-tabular" style={{ color: planetaryColor("earth") }}>Earth {row.earth}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
