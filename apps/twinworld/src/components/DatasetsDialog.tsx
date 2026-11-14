import { Dialog } from "@base-ui/react/dialog";
import { ArrowUpRight, Database, X } from "lucide-react";
import type { DatasetInfo } from "../types";
import type { AnyBody } from "../types";
import { planetaryColor, planetarySourceStyle } from "../planetaryTokens";

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
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6 scroll-contain">
          <Dialog.Popup className="dialog-popup relative w-full max-w-4xl rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] text-[var(--text-primary)] shadow-2xl overflow-hidden my-auto">
            <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-6 py-4">
              <div>
                <div className="inline-flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                  <Database className="w-4 h-4" strokeWidth={1.5} />
                  Provenance registry
                </div>
                <Dialog.Title className="font-display text-lg font-medium text-[var(--text-primary)] mt-1">
                  Registered datasets
                </Dialog.Title>
              </div>
              <Dialog.Close
                aria-label="Close datasets dialog"
                className="pressable shrink-0 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-2 text-[var(--text-secondary)] hover-surface"
              >
                <X className="w-4 h-4" strokeWidth={1.5} />
              </Dialog.Close>
            </div>

            <div className="p-6 space-y-4 max-h-[75dvh] overflow-y-auto scroll-contain">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {datasets.map((d) => (
                  <article key={d.id} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-2">
                    {(() => {
                      const bodies = d.bodies.map((body) => body.toLowerCase()).filter((body): body is AnyBody => body === "earth" || body === "mars" || body === "moon");
                      const sourceBody = bodies.length === 1 ? bodies[0] : null;
                      return (
                        <>
                    <div className="flex items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
                      <span className="capitalize">
                        {bodies.length ? bodies.map((body, index) => <span key={body} style={{ color: planetaryColor(body) }}>{index ? ", " : ""}{body}</span>) : d.bodies.join(", ")} · {d.status}
                      </span>
                      {d.coverage_count !== undefined && (
                        <span className="font-mono-tabular text-[var(--text-secondary)]">{d.coverage_count} indexed</span>
                      )}
                    </div>
                    <h3 className="text-sm font-medium text-[var(--text-primary)]">{d.name}</h3>
                    <p className="text-xs text-[var(--text-secondary)]">{d.provider} · {d.variable}</p>
                    {d.source_url.startsWith("http") && (
                      <a
                        href={d.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className={sourceBody ? "planetary-source inline-flex items-center gap-1 text-xs" : "inline-flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}
                        style={sourceBody ? planetarySourceStyle(sourceBody) : undefined}
                      >
                        Reference <ArrowUpRight className="w-4 h-4" strokeWidth={1.5} />
                      </a>
                    )}
                        </>
                      );
                    })()}
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
