import type { AnyBody } from "../types";
import {
  globeSourceDescriptor,
  globeTileUrl,
  type OfflineTileMatrix,
} from "./globeImagery";

export type OfflinePackageStatus = "idle" | "preparing" | "downloading" | "paused" | "cancelled" | "complete" | "error" | "stale";

export type OfflinePackageSnapshot = {
  status: OfflinePackageStatus;
  completed: number;
  total: number;
  bytes: number;
  required_bytes: number;
  available_bytes: number | null;
  persistent: boolean | null;
  has_saved_tiles: boolean;
  error: string | null;
};

export type TileLookup = { blob: Blob | null; unavailable: boolean };

const INITIAL: OfflinePackageSnapshot = {
  status: "idle", completed: 0, total: 0, bytes: 0, required_bytes: 600 * 1024 * 1024,
  available_bytes: null, persistent: null, has_saved_tiles: false, error: null,
};
const listeners = new Set<(state: OfflinePackageSnapshot) => void>();
let pollTimer: number | null = null;
let currentState = INITIAL;

function emit(state: OfflinePackageSnapshot) {
  currentState = state;
  for (const listener of listeners) listener({ ...state });
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = String(payload.detail ?? detail);
    } catch { /* Use the status text. */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function refreshOfflinePackage(): Promise<OfflinePackageSnapshot> {
  try {
    const next = await requestJson<OfflinePackageSnapshot>("/api/imagery/offline/status");
    emit(next);
  } catch (error) {
    emit({
      ...currentState,
      status: currentState.status === "preparing" ? "idle" : currentState.status,
      error: error instanceof Error ? error.message : "Local ENOM backend is unavailable.",
    });
  }
  return { ...currentState };
}

export function subscribeOfflinePackage(listener: (state: OfflinePackageSnapshot) => void): () => void {
  listeners.add(listener);
  listener({ ...currentState });
  void refreshOfflinePackage();
  if (pollTimer === null) pollTimer = window.setInterval(() => void refreshOfflinePackage(), 1200);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };
}

export async function prepareOfflinePackage(): Promise<OfflinePackageSnapshot> {
  emit({ ...currentState, status: currentState.status === "idle" ? "preparing" : currentState.status, error: null });
  return refreshOfflinePackage();
}

export async function getStorageAvailability(): Promise<{ availableBytes: number | null; persistent: boolean | null }> {
  const state = await refreshOfflinePackage();
  return { availableBytes: state.available_bytes, persistent: null };
}

async function postAction(action: "start" | "pause" | "cancel"): Promise<void> {
  try {
    const state = await requestJson<OfflinePackageSnapshot>(`/api/imagery/offline/${action}`, { method: "POST" });
    emit(state);
  } catch (error) {
    emit({ ...currentState, status: "error", error: error instanceof Error ? error.message : "Repository map action failed." });
  }
}

export function startOrResumeOfflinePackage(): Promise<void> {
  return postAction("start");
}

export function pauseOfflinePackage(): Promise<void> {
  return postAction("pause");
}

export function cancelOfflinePackage(): Promise<void> {
  return postAction("cancel");
}

export async function clearOfflinePackage(): Promise<void> {
  try {
    const response = await fetch("/api/imagery/offline", { method: "DELETE" });
    if (!response.ok) throw new Error("Could not clear repository map tiles");
    emit(await response.json() as OfflinePackageSnapshot);
  } catch (error) {
    emit({ ...currentState, status: "error", error: error instanceof Error ? error.message : "Could not clear repository map tiles." });
  }
}

function localTileUrl(body: AnyBody, matrix: OfflineTileMatrix, row: number, col: number): string {
  const { version, matrixSet } = globeSourceDescriptor(body);
  return `/api/imagery/offline/tiles/${encodeURIComponent(body)}/${encodeURIComponent(version)}/${encodeURIComponent(matrixSet)}/${encodeURIComponent(matrix.id)}/${row}/${col}`;
}

export async function saveViewedGlobeTile(body: AnyBody, matrix: OfflineTileMatrix, row: number, col: number, blob: Blob): Promise<void> {
  try {
    const response = await fetch(localTileUrl(body, matrix, row, col), {
      method: "PUT",
      body: blob,
      headers: { "content-type": blob.type || "image/jpeg" },
    });
    if (!response.ok) throw new Error(`Tile save failed (${response.status})`);
  } catch { /* Keep the online globe functional if the local backend is unavailable. */ }
}

export async function loadCachedOrNetworkTile(
  body: AnyBody,
  tile: { matrix: OfflineTileMatrix; row: number; col: number },
  signal: AbortSignal,
): Promise<TileLookup> {
  try {
    const local = await fetch(localTileUrl(body, tile.matrix, tile.row, tile.col), { signal, cache: "no-store" });
    if (local.ok) return { blob: await local.blob(), unavailable: false };
    if (local.status === 410) return { blob: null, unavailable: true };
  } catch (error) {
    if (signal.aborted) throw error;
  }
  const response = await fetch(globeTileUrl(body, tile.matrix, tile.row, tile.col), { signal, mode: "cors" });
  if (response.status === 404 || response.status === 204) return { blob: null, unavailable: true };
  if (!response.ok) throw new Error(`Tile request failed (${response.status})`);
  const blob = await response.blob();
  if (!blob.type.startsWith("image/") || blob.size === 0) throw new Error("Tile response was not an image");
  void saveViewedGlobeTile(body, tile.matrix, tile.row, tile.col, blob);
  return { blob, unavailable: false };
}
