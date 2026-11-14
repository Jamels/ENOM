import { useEffect, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Check, Download, HardDrive, Pause, Play, Trash2, X } from "lucide-react";
import {
  cancelOfflinePackage,
  clearOfflinePackage,
  getStorageAvailability,
  pauseOfflinePackage,
  prepareOfflinePackage,
  startOrResumeOfflinePackage,
  subscribeOfflinePackage,
  type OfflinePackageSnapshot,
} from "../lib/globeTileStore";

const INITIAL: OfflinePackageSnapshot = {
  status: "idle", completed: 0, total: 0, bytes: 0, required_bytes: 0,
  available_bytes: null, persistent: null, has_saved_tiles: false, error: null,
};

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "Unavailable";
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function OfflineMapsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [state, setState] = useState(INITIAL);
  const [storageRefreshing, setStorageRefreshing] = useState(false);

  useEffect(() => {
    if (open) return subscribeOfflinePackage(setState);
  }, [open]);

  useEffect(() => {
    if (open) void prepareOfflinePackage();
  }, [open]);

  const refreshStorage = async () => {
    setStorageRefreshing(true);
    const storage = await getStorageAvailability();
    setState((current) => ({ ...current, available_bytes: storage.availableBytes }));
    setStorageRefreshing(false);
  };

  const running = state.status === "downloading" || state.status === "preparing";
  const canStart = state.status === "idle" || state.status === "paused" || state.status === "cancelled" || state.status === "error" || state.status === "stale";
  const insufficientSpace = state.completed === 0 && state.available_bytes !== null && state.required_bytes > 0 && state.available_bytes < state.required_bytes;
  const progress = state.total > 0 ? Math.min(100, (state.completed / state.total) * 100) : 0;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop fixed inset-0 z-50 bg-black/75 backdrop-blur-xs" />
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6 scroll-contain">
          <Dialog.Popup className="dialog-popup relative w-full max-w-xl rounded-2xl border border-[var(--border-strong)] bg-[var(--bg-panel)] text-[var(--text-primary)] shadow-2xl overflow-hidden my-auto">
            <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-5 py-4">
              <div>
                <div className="inline-flex items-center gap-2 text-xs text-[var(--text-secondary)]"><HardDrive className="w-4 h-4" /> Repository storage</div>
                <Dialog.Title className="font-display text-lg font-medium mt-1">Save maps offline</Dialog.Title>
                <Dialog.Description className="mt-1 text-xs text-[var(--text-secondary)]">
                  Download Earth, Mars, and Moon tiles through zoom level 6 into the ENOM repository.
                </Dialog.Description>
              </div>
              <Dialog.Close aria-label="Close offline maps" className="pressable rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-2 text-[var(--text-secondary)] hover-surface"><X className="w-4 h-4" /></Dialog.Close>
            </div>

            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-3">
                  <div className="text-[11px] text-[var(--text-muted)]">Estimated package</div>
                  <div className="mt-1 text-sm font-medium">{formatBytes(state.required_bytes || 600 * 1024 * 1024)}</div>
                  <div className="mt-1 text-[11px] text-[var(--text-secondary)]">26,117 image tiles · approximate</div>
                </div>
                <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-3">
                  <div className="text-[11px] text-[var(--text-muted)]">Available disk space</div>
                  <div className="mt-1 text-sm font-medium">{formatBytes(state.available_bytes)}</div>
                  <button type="button" onClick={() => void refreshStorage()} disabled={storageRefreshing} className="mt-1 text-[11px] text-[var(--text-secondary)] underline underline-offset-2">{storageRefreshing ? "Checking…" : "Refresh estimate"}</button>
                </div>
              </div>

              {state.status !== "idle" && state.total > 0 && (
                <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-void)] p-4 space-y-2" aria-live="polite">
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="capitalize text-[var(--text-secondary)]">{state.status === "complete" ? "Offline maps ready" : state.status}</span>
                    <span className="font-mono-tabular">{state.completed.toLocaleString()} / {state.total.toLocaleString()}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-hover)]"><div className="h-full rounded-full bg-cyan-400 transition-[width]" style={{ width: `${progress}%` }} /></div>
                  <div className="text-[11px] text-[var(--text-muted)]">{formatBytes(state.bytes)} stored so far</div>
                </section>
              )}

              {insufficientSpace && <p className="text-xs text-amber-200">The current estimate is below the package size. Free repository disk space before downloading.</p>}
              {state.error && <p role="alert" className="text-xs text-rose-200">{state.error}</p>}
              <p className="text-[11px] leading-relaxed text-[var(--text-muted)]">Files are saved under <code className="font-mono-tabular">apps/twinworld/public/tiles/offline/</code> and served by ENOM’s local backend. Unavailable tiles and uncached higher zoom levels continue using the globe’s base texture. Earth’s Blue Marble is a historical global composite, not a live image; its source may contain some cloud affected pixels.</p>

              <div className="flex flex-wrap items-center gap-2 pt-1">
                {running ? (
                  <>
                    <button type="button" onClick={() => void pauseOfflinePackage()} className="pressable inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-3 py-2 text-xs font-medium text-slate-950"><Pause className="w-4 h-4" /> Pause</button>
                    <button type="button" onClick={() => void cancelOfflinePackage()} className="pressable rounded-lg border border-[var(--border-subtle)] px-3 py-2 text-xs text-[var(--text-secondary)]">Cancel</button>
                  </>
                ) : state.status === "complete" ? (
                  <span className="inline-flex items-center gap-2 rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"><Check className="w-4 h-4" /> Saved in repository</span>
                ) : (
                  <button type="button" onClick={() => void startOrResumeOfflinePackage()} disabled={!canStart || insufficientSpace || state.status === "preparing"} className="pressable inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-3 py-2 text-xs font-medium text-slate-950 disabled:opacity-50">
                    {state.completed > 0 ? <Play className="w-4 h-4" /> : <Download className="w-4 h-4" />}
                    {state.status === "stale" ? "Download updated maps" : state.completed > 0 ? "Resume download" : "Download maps"}
                  </button>
                )}
                {(state.completed > 0 || state.has_saved_tiles) && !running && <button type="button" onClick={() => void clearOfflinePackage()} className="pressable inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-3 py-2 text-xs text-[var(--text-secondary)]"><Trash2 className="w-4 h-4" /> Clear saved maps</button>}
                {state.status === "preparing" && <span className="text-xs text-[var(--text-muted)]">Reading NASA tile matrices…</span>}
              </div>
            </div>
          </Dialog.Popup>
        </div>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
