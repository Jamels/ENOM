import { ExternalLink } from "lucide-react";

export type CoverageMeasurement = {
  name: string;
  value: number | null;
  units: string;
  availability: string;
  spatial_scale_m?: number | null;
  uncertainty?: { description?: string | null } | null;
};

export type CoverageSupport = {
  label: string;
  count: number | null;
  total: number | null;
  fraction: number | null;
  note?: string | null;
};

export type CoverageSource = { label: string; url: string };

export function EvidenceCoveragePanel({
  title,
  subtitle,
  imagery,
  visual,
  measurements,
  support,
  availableContext,
  unavailableContext,
  limitations = [],
  sources = [],
}: {
  title: string;
  subtitle?: string;
  imagery: { label: string; available: boolean };
  visual: { label: string; available: boolean };
  measurements: CoverageMeasurement[];
  support?: CoverageSupport | null;
  availableContext: string[];
  unavailableContext: string[];
  limitations?: string[];
  sources?: CoverageSource[];
}) {
  const usableMeasurements = measurements.filter(
    (measurement) => measurement.availability === "available" && measurement.value !== null,
  );
  const sourceByUrl = new Map<string, CoverageSource>();
  for (const source of sources) {
    if (source.url) sourceByUrl.set(source.url, source);
  }
  const uniqueSources = [...sourceByUrl.values()];
  const supportPercent = support?.fraction == null ? null : Math.max(0, Math.min(100, support.fraction * 100));

  return (
    <section
      aria-label="Evidence coverage for selected location"
      className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] p-4 space-y-4"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-[var(--text-primary)]">Coverage at selected location</h2>
          <p className="mt-1 truncate text-xs text-[var(--text-secondary)]">{title}{subtitle ? ` · ${subtitle}` : ""}</p>
        </div>
        <span className="rounded-full border border-amber-400/25 bg-amber-400/5 px-2 py-1 text-[13px] text-amber-200">
          {usableMeasurements.length ? `${usableMeasurements.length}/${measurements.length} terrain measurements usable` : "No usable terrain measurements"}
        </span>
      </header>

      <div className="grid gap-2 sm:grid-cols-3">
        <CoverageTile label="Imagery" available={imagery.available} detail={imagery.label} />
        <CoverageTile label="Visual search" available={visual.available} detail={visual.label} />
        <CoverageTile
          label="Terrain"
          available={usableMeasurements.length > 0}
          detail={usableMeasurements.length ? `${usableMeasurements.length} measurements available` : "No comparable measurements"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-[minmax(0,1.3fr)_minmax(220px,0.7fr)]">
        <section aria-label="Terrain measurement availability" className="space-y-2">
          <h3 className="text-xs font-medium text-[var(--text-primary)]">Terrain measurements</h3>
          {measurements.length ? (
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {measurements.map((measurement) => {
                const available = measurement.availability === "available" && measurement.value !== null;
                return (
                  <li
                    key={measurement.name}
                    className={`rounded-lg border px-2.5 py-2 text-xs ${
                      available
                        ? "border-emerald-500/20 bg-emerald-500/5"
                        : "border-amber-500/20 bg-amber-500/5"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="capitalize text-[var(--text-primary)]">{measurement.name.replaceAll("_", " ")}</span>
                      <span className={available ? "shrink-0 text-emerald-200" : "shrink-0 text-amber-200"}>
                        {available ? "Available" : "Unavailable"}
                      </span>
                    </div>
                    <p className="mt-1 font-mono-tabular text-[var(--text-secondary)]">
                      {available
                        ? `${measurement.value} ${measurement.units}${measurement.spatial_scale_m ? ` · ${Math.round(measurement.spatial_scale_m)} m scale` : ""}`
                        : measurement.availability.replaceAll("_", " ")}
                    </p>
                    {measurement.uncertainty?.description && (
                      <p className="mt-1 text-[13px] leading-4 text-[var(--text-muted)]">{measurement.uncertainty.description}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100">
              ENOM has no terrain measurements indexed for this location.
            </p>
          )}
        </section>

        <section aria-label="Observation support and contextual evidence" className="space-y-3">
          {support && (
            <div className="space-y-1.5">
              <h3 className="text-xs font-medium text-[var(--text-primary)]">{support.label}</h3>
              <p className="font-mono-tabular text-xs text-[var(--text-secondary)]">
                {support.count != null && support.total != null
                  ? `${support.count.toLocaleString()} of ${support.total.toLocaleString()} cells`
                  : "Fraction not quantified"}
                {supportPercent != null ? ` · ${supportPercent.toFixed(1)}%` : ""}
              </p>
              {supportPercent != null && (
                <div
                  role="meter"
                  aria-label={support.label}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={supportPercent}
                  className="h-2 overflow-hidden rounded-full bg-[var(--bg-void)]"
                >
                  <div className="h-full rounded-full bg-amber-300" style={{ width: `${supportPercent}%` }} />
                </div>
              )}
              {support.note && <p className="text-[13px] leading-4 text-[var(--text-muted)]">{support.note}</p>}
            </div>
          )}

          <div className="space-y-1.5">
            <h3 className="text-xs font-medium text-[var(--text-primary)]">Other evidence</h3>
            {availableContext.length > 0 && <p className="text-xs text-emerald-200">Available: {availableContext.join(", ")}</p>}
            {unavailableContext.length > 0 && <p className="text-xs text-amber-200">Not indexed: {unavailableContext.join(", ")}</p>}
            {!availableContext.length && !unavailableContext.length && <p className="text-xs text-[var(--text-muted)]">No linked context evidence.</p>}
          </div>
        </section>
      </div>

      {(limitations.length > 0 || uniqueSources.length > 0) && (
        <footer className="flex flex-wrap items-end justify-between gap-3 border-t border-[var(--border-subtle)] pt-3">
          {limitations.length > 0 && (
            <ul className="min-w-0 flex-1 space-y-1 text-[13px] leading-4 text-[var(--text-muted)]">
              {limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
              <li>Coverage describes ENOM’s indexed evidence, not whether a feature exists on the surface.</li>
            </ul>
          )}
          {uniqueSources.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {uniqueSources.map((source) => (
                <a key={source.url} href={source.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                  {source.label} <ExternalLink className="inline h-3 w-3" aria-hidden="true" />
                </a>
              ))}
            </div>
          )}
        </footer>
      )}
      {limitations.length === 0 && uniqueSources.length === 0 && (
        <p className="border-t border-[var(--border-subtle)] pt-3 text-[13px] text-[var(--text-muted)]">
          Coverage describes ENOM’s indexed evidence, not whether a feature exists on the surface.
        </p>
      )}
    </section>
  );
}

function CoverageTile({ label, detail, available }: { label: string; detail: string; available: boolean }) {
  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] px-3 py-2">
      <p className="text-[13px] uppercase tracking-wide text-[var(--text-muted)]">{label}</p>
      <p className={`mt-1 text-xs font-medium ${available ? "text-emerald-200" : "text-amber-200"}`}>
        <span aria-hidden="true">{available ? "● " : "○ "}</span>{detail}
      </p>
    </div>
  );
}
