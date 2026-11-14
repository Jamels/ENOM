import { Dialog } from "@base-ui/react/dialog";
import { ArrowUpRight, Database, X } from "lucide-react";
import type { DatasetInfo } from "../types";

export function DatasetsDialog({
  open,
  onOpenChange,
  datasets,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  datasets: DatasetInfo[];
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop fixed inset-0 z-50 bg-black/75 backdrop-blur-xs" />
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-3 sm:p-6 scroll-contain">
          <Dialog.Popup className="dialog-popup relative w-full max-w-4xl rounded-2xl border border-[var(--border-strong)] bg-[#0d121a] text-slate-100 shadow-2xl overflow-hidden my-auto">
            <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[#0f1621] px-5 py-4">
              <div>
                <div className="inline-flex items-center gap-1.5 text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-sky-400">
                  <Database className="w-3.5 h-3.5" />
                  ENOM provenance registry
                </div>
                <Dialog.Title className="font-display text-lg font-semibold text-slate-50 mt-0.5">
                  Registered NASA, ESA & USGS datasets
                </Dialog.Title>
              </div>
              <Dialog.Close
                aria-label="Close datasets dialog"
                className="pressable shrink-0 rounded-lg border border-[var(--border-subtle)] bg-[#141d2b] p-2 text-slate-300 hover-surface"
              >
                <X className="w-4 h-4" />
              </Dialog.Close>
            </div>

            <div className="p-5 space-y-3 max-h-[75dvh] overflow-y-auto scroll-contain">
              <p className="text-xs text-slate-400 leading-relaxed">
                Coordinates follow east-positive longitude [0, 360) and planetocentric latitude. Visual cosine retrieval and terrain ranking are exploratory research leads, not validated site suitability.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {datasets.map((d) => (
                  <article key={d.id} className="rounded-xl border border-[var(--border-subtle)] bg-[#0a0e15] p-3.5 space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono-tabular text-[10px] uppercase text-slate-400">
                        {d.bodies.join(" · ")} · {d.status}
                      </span>
                      {d.coverage_count !== undefined && (
                        <span className="font-mono-tabular text-[10px] text-sky-300">
                          {d.coverage_count} indexed
                        </span>
                      )}
                    </div>
                    <h3 className="text-sm font-medium text-slate-100">{d.name}</h3>
                    <p className="text-[11px] text-slate-400">{d.provider} · {d.variable}</p>
                    {(d.uncertainty || d.missing_data_semantics) && (
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        {d.uncertainty ?? d.missing_data_semantics}
                      </p>
                    )}
                    {d.source_url.startsWith("http") && (
                      <a
                        href={d.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] text-sky-400 hover:text-sky-300 pt-1"
                      >
                        Dataset reference <ArrowUpRight className="w-3 h-3" />
                      </a>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </Dialog.Popup>
        </div>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
