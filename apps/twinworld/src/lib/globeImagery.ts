import * as THREE from "three";
import type { AnyBody } from "../types";
import { loadCachedOrNetworkTile } from "./globeTileStore";

type TileMatrix = {
  id: string;
  width: number;
  height: number;
  tileWidth: number;
  tileHeight: number;
};

type Source = {
  service: string;
  layer: string;
  capabilities: string;
  tileTemplate: string;
  projection: "EPSG:4326";
  tileFormat: "image/jpeg";
  matrixSet: string;
  version: string;
  attribution: string;
};

export type GlobeImageryMetadata = {
  matrices: TileMatrix[];
  defaultDate: string | null;
};

const SOURCES: Record<AnyBody, Source> = {
  earth: {
    service: "NASA GIBS WMTS",
    layer: "BlueMarble_NextGeneration",
    capabilities: "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml",
    tileTemplate:
      "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/BlueMarble_NextGeneration/default/500m/{z}/{y}/{x}.jpeg",
    projection: "EPSG:4326",
    tileFormat: "image/jpeg",
    matrixSet: "500m",
    version: "blue-marble-next-generation-2004-v1",
    attribution: "NASA GIBS · Blue Marble Next Generation (August 2004, cloud-free global composite, 500 m/pixel)",
  },
  mars: {
    service: "NASA Trek WMTS",
    layer: "Mars_Viking_MDIM21_ClrMosaic_global_232m",
    capabilities:
      "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml",
    tileTemplate:
      "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg",
    projection: "EPSG:4326",
    tileFormat: "image/jpeg",
    matrixSet: "default028mm",
    version: "mars-viking-mdim21-global-1.0.0-v1",
    attribution: "NASA Trek · Viking MDIM 2.1",
  },
  moon: {
    service: "NASA Trek WMTS",
    layer: "LRO_WAC_Mosaic_Global_303ppd_v02",
    capabilities:
      "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml",
    tileTemplate:
      "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg",
    projection: "EPSG:4326",
    tileFormat: "image/jpeg",
    matrixSet: "default028mm",
    version: "moon-lro-wac-global-v02-1.0.0-v1",
    attribution: "NASA Trek · LRO WAC global mosaic",
  },
};

export function imageryAttribution(body: AnyBody): string {
  return SOURCES[body].attribution;
}

export const OFFLINE_PACKAGE_MAX_LEVEL = 6;

export function globeTileCacheKey(body: AnyBody, matrix: TileMatrix, row: number, col: number): string {
  const source = SOURCES[body];
  return [body, source.version, source.matrixSet, matrix.id, row, col].join("|");
}

export function globeTileUrl(body: AnyBody, matrix: TileMatrix, row: number, col: number): string {
  return SOURCES[body].tileTemplate
    .replace("{z}", encodeURIComponent(matrix.id))
    .replace("{y}", String(row))
    .replace("{x}", String(col));
}

export type OfflineTileMatrix = TileMatrix;

export function globeSourceDescriptor(body: AnyBody) {
  const source = SOURCES[body];
  return {
    version: source.version,
    layer: source.layer,
    matrixSet: source.matrixSet,
    attribution: source.attribution,
  };
}

const metadataPromises = new Map<AnyBody, Promise<GlobeImageryMetadata>>();

const OFFLINE_MATRIX_DIMENSIONS: Record<AnyBody, Array<[number, number]>> = {
  earth: [[2, 1], [3, 2], [5, 3], [10, 5], [20, 10], [40, 20], [80, 40], [160, 80]],
  mars: [[2, 1], [4, 2], [8, 4], [16, 8], [32, 16], [64, 32], [128, 64], [256, 128]],
  moon: [[2, 1], [4, 2], [8, 4], [16, 8], [32, 16], [64, 32], [128, 64], [256, 128], [512, 256]],
};

function offlineMetadata(body: AnyBody): GlobeImageryMetadata {
  return {
    matrices: OFFLINE_MATRIX_DIMENSIONS[body].map(([width, height], level) => ({
      id: String(level), width, height, tileWidth: 256, tileHeight: 256,
    })),
    defaultDate: null,
  };
}

export function loadGlobeImageryMetadata(body: AnyBody): Promise<GlobeImageryMetadata> {
  const existing = metadataPromises.get(body);
  if (existing) return existing;
  const source = SOURCES[body];
  const promise = fetch(source.capabilities)
    .then((response) => {
      if (!response.ok) throw new Error(`Capabilities request failed (${response.status})`);
      return response.text();
    })
    .then((xml) => {
      const doc = new DOMParser().parseFromString(xml, "application/xml");
      if (doc.querySelector("parsererror")) throw new Error("Invalid WMTS capabilities XML");
      const identifier = (node: Element | null) =>
        node?.getElementsByTagNameNS("http://www.opengis.net/ows/1.1", "Identifier")[0]
          ?.textContent?.trim() ?? "";
      const layers = Array.from(doc.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "Layer"));
      const layer = layers.find((candidate) => identifier(candidate) === source.layer);
      if (!layer) throw new Error(`WMTS layer ${source.layer} is missing`);

      let defaultDate: string | null = null;
      if (body === "earth") {
        const dimensions = Array.from(
          layer.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "Dimension"),
        );
        for (const dimension of dimensions) {
          if (identifier(dimension) !== "Time") continue;
          defaultDate =
            dimension.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "Default")[0]
              ?.textContent?.trim() ?? null;
        }
      }

      const matrixSets = Array.from(
        doc.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "TileMatrixSet"),
      );
      const matrixSet = matrixSets.find((candidate) => identifier(candidate) === source.matrixSet);
      if (!matrixSet) throw new Error(`WMTS matrix set ${source.matrixSet} is missing`);
      const matrices = Array.from(
        matrixSet.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "TileMatrix"),
      ).map((matrix) => ({
        id: identifier(matrix),
        width: Number(matrix.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "MatrixWidth")[0]?.textContent),
        height: Number(matrix.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "MatrixHeight")[0]?.textContent),
        tileWidth: Number(matrix.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "TileWidth")[0]?.textContent),
        tileHeight: Number(matrix.getElementsByTagNameNS("http://www.opengis.net/wmts/1.0", "TileHeight")[0]?.textContent),
      }));
      if (!matrices.length || matrices.some((matrix) =>
        !matrix.id || !Number.isFinite(matrix.width) || !Number.isFinite(matrix.height) ||
        matrix.width < 1 || matrix.height < 1
      )) throw new Error("WMTS capabilities contain invalid tile matrices");
      return { matrices, defaultDate };
    })
    .catch(() => offlineMetadata(body));
  metadataPromises.set(body, promise);
  return promise;
}

type TileRecord = {
  texture: THREE.Texture;
  lastUsed: number;
};

type PendingTile = {
  controller: AbortController;
  promise: Promise<void>;
};

type VisibleTile = {
  key: string;
  matrix: TileMatrix;
  row: number;
  col: number;
};

type GlobeView = {
  lat: number;
  lon: number;
  zoom: number;
  viewportWidth: number;
  viewportHeight: number;
  cameraDistance: number;
};

const CACHE_LIMIT = 96;
const MAX_CONCURRENT = 6;
const TILE_RADIUS = 1.0025;

function latLonToVec3(lat: number, lon: number, radius: number): THREE.Vector3 {
  const latRad = (lat * Math.PI) / 180;
  const lonRad = (lon * Math.PI) / 180;
  const cosLat = Math.cos(latRad);
  return new THREE.Vector3(
    radius * cosLat * Math.cos(lonRad),
    radius * Math.sin(latRad),
    -radius * cosLat * Math.sin(lonRad),
  );
}

function tileGeometry(tile: VisibleTile): THREE.BufferGeometry {
  const { matrix, row, col } = tile;
  const lonStep = 360 / matrix.width;
  const latStep = 180 / matrix.height;
  const west = -180 + col * lonStep;
  const east = west + lonStep;
  const north = 90 - row * latStep;
  const south = north - latStep;
  const segments = 12;
  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];
  for (let y = 0; y <= segments; y++) {
    const v = y / segments;
    const lat = north + (south - north) * v;
    for (let x = 0; x <= segments; x++) {
      const u = x / segments;
      const lon = west + (east - west) * u;
      const point = latLonToVec3(lat, lon, TILE_RADIUS);
      positions.push(point.x, point.y, point.z);
      uvs.push(u, 1 - v);
    }
  }
  for (let y = 0; y < segments; y++) {
    for (let x = 0; x < segments; x++) {
      const a = y * (segments + 1) + x;
      const b = a + segments + 1;
      indices.push(a, b, a + 1, a + 1, b, b + 1);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function tileImageForTexture(bitmap: ImageBitmap, body: AnyBody): CanvasImageSource | null {
  // Blue Marble is a complete global composite; dark ocean pixels are valid data,
  // so Earth tiles must stay opaque instead of using MODIS no-data transparency.
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return bitmap;
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  if (body !== "mars") return canvas;

  const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
  let hasData = false;
  for (let i = 0; i < pixels.data.length; i += 4) {
    const noData = pixels.data[i] >= 246 && pixels.data[i + 1] >= 246 && pixels.data[i + 2] >= 246;
    if (noData) {
      pixels.data[i + 3] = 0;
    } else {
      hasData = true;
    }
  }
  if (!hasData) {
    return null;
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

function visibleTiles(
  matrices: TileMatrix[],
  body: AnyBody,
  lat: number,
  lon: number,
  zoom: number,
  viewportWidth: number,
  viewportHeight: number,
  cameraDistance: number,
): VisibleTile[] {
  if (zoom < 1.13) return [];
  const surfacePixels = viewportWidth * zoom;
  const view = latLonToVec3(lat, lon, 1).normalize();
  const right = new THREE.Vector3(0, 1, 0).cross(view).normalize();
  const up = view.clone().cross(right).normalize();
  const verticalFovTangent = Math.tan((36 * Math.PI) / 360);
  const horizontalFovTangent = verticalFovTangent * (viewportWidth / viewportHeight);
  const enumerate = (matrix: TileMatrix): VisibleTile[] => {
    const latStep = 180 / matrix.height;
    const lonStep = 360 / matrix.width;
    const tiles: VisibleTile[] = [];
    for (let row = 0; row < matrix.height; row++) {
      const north = 90 - row * latStep;
      const south = north - latStep;
      for (let col = 0; col < matrix.width; col++) {
        const west = -180 + col * lonStep;
        const east = west + lonStep;
        let isVisible = false;
        for (let sy = 0; sy <= 2; sy++) {
          for (let sx = 0; sx <= 2; sx++) {
            const point = latLonToVec3(
              north + (south - north) * (sy / 2),
              west + (east - west) * (sx / 2),
              1,
            );
            const facing = point.dot(view);
            const depth = cameraDistance - facing;
            if (
              facing >= 1 / cameraDistance &&
              Math.abs(point.dot(right)) <= depth * horizontalFovTangent * 1.15 &&
              Math.abs(point.dot(up)) <= depth * verticalFovTangent * 1.15
            ) {
              isVisible = true;
            }
          }
        }
        // Select only front-facing tiles inside the camera frustum. This keeps
        // high-resolution Earth matrices within the fixed texture cache budget.
        if (!isVisible) continue;
        tiles.push({ key: globeTileCacheKey(body, matrix, row, col), matrix, row, col });
      }
    }
    return tiles;
  };

  let selectedTiles = enumerate(matrices[0]);
  for (const matrix of matrices) {
    const tilePixels = (surfacePixels * 2) / matrix.width;
    if (tilePixels < (body === "earth" ? 14 : 96)) break;
    const candidate = enumerate(matrix);
    if (candidate.length > CACHE_LIMIT) break;
    selectedTiles = candidate;
  }
  return selectedTiles;
}

export class GlobeTileOverlay {
  private readonly group = new THREE.Group();
  private readonly cache = new Map<string, TileRecord>();
  private readonly pending = new Map<string, PendingTile>();
  private readonly failed = new Set<string>();
  private readonly meshes = new Map<string, THREE.Mesh>();
  private desired = new Map<string, VisibleTile>();
  private metadata: GlobeImageryMetadata | null = null;
  private latestView: GlobeView | null = null;
  private disposed = false;
  private activeCount = 0;
  private lastStatus: "base" | "loading" | "active" | "unavailable" = "base";

  constructor(
    private readonly body: AnyBody,
    private readonly scene: THREE.Scene,
    private readonly onStatus: (status: "base" | "loading" | "active" | "unavailable") => void,
    private readonly onDate: (date: string | null) => void,
    private readonly renderer: THREE.WebGLRenderer,
  ) {
    this.scene.add(this.group);
    loadGlobeImageryMetadata(body).then((metadata) => {
      if (this.disposed) return;
      this.metadata = metadata;
      this.onDate(metadata.defaultDate);
      if (this.latestView) {
        this.update(
          this.latestView.lat,
          this.latestView.lon,
          this.latestView.zoom,
          this.latestView.viewportWidth,
          this.latestView.viewportHeight,
          this.latestView.cameraDistance,
        );
      } else {
        this.refresh();
      }
    }).catch(() => this.setStatus("unavailable"));
  }

  update(
    lat: number,
    lon: number,
    zoom: number,
    viewportWidth: number,
    viewportHeight: number,
    cameraDistance: number,
  ) {
    if (this.disposed) return;
    this.latestView = { lat, lon, zoom, viewportWidth, viewportHeight, cameraDistance };
    if (!this.metadata) return;
    const tiles = visibleTiles(
      this.metadata.matrices,
      this.body,
      lat,
      lon,
      zoom,
      viewportWidth,
      viewportHeight,
      cameraDistance,
    );
    this.desired = new Map(tiles.map((tile) => [tile.key, tile]));
    for (const [key, pending] of this.pending) {
      if (!this.desired.has(key)) {
        pending.controller.abort();
        this.pending.delete(key);
      }
    }
    for (const [key, mesh] of this.meshes) {
      if (!this.desired.has(key)) {
        this.group.remove(mesh);
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
        this.meshes.delete(key);
      }
    }
    for (const key of this.desired.keys()) {
      const record = this.cache.get(key);
      if (record) {
        record.lastUsed = performance.now();
        this.attachMesh(key, this.desired.get(key)!, record.texture);
      }
    }
    this.refresh();
    this.pump();
  }

  private refresh() {
    if (this.disposed || !this.metadata) return;
    if (this.desired.size === 0 && this.pending.size === 0) {
      this.setStatus("base");
    } else if (this.meshes.size > 0) {
      this.setStatus("active");
    } else if (this.pending.size > 0 || this.activeCount > 0) {
      this.setStatus("loading");
    } else if (this.desired.size > 0) {
      this.setStatus("unavailable");
    }
  }

  private setStatus(status: "base" | "loading" | "active" | "unavailable") {
    if (status === this.lastStatus) return;
    this.lastStatus = status;
    this.onStatus(status);
  }

  private attachMesh(key: string, tile: VisibleTile, texture: THREE.Texture) {
    if (this.meshes.has(key) || !this.desired.has(key)) return;
    const material = new THREE.MeshBasicMaterial({
      map: texture,
      side: THREE.FrontSide,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    });
    const mesh = new THREE.Mesh(tileGeometry(tile), material);
    mesh.frustumCulled = false;
    this.group.add(mesh);
    this.meshes.set(key, mesh);
  }

  private tileUrl(tile: VisibleTile): string {
    return globeTileUrl(this.body, tile.matrix, tile.row, tile.col);
  }

  private pump() {
    if (this.disposed || !this.metadata) return;
    for (const [key, tile] of this.desired) {
      if (this.cache.has(key) || this.pending.has(key) || this.failed.has(key) || this.activeCount >= MAX_CONCURRENT) continue;
      const controller = new AbortController();
      let timedOut = false;
      let timeout = 0;
      const timeoutPromise = new Promise<never>((_resolve, reject) => {
        timeout = window.setTimeout(() => {
          timedOut = true;
          controller.abort();
          reject(new Error("Tile request timed out"));
        }, 12000);
      });
      const requestPromise = loadCachedOrNetworkTile(this.body, tile, controller.signal)
        .then((result) => {
          if (result.unavailable || !result.blob) throw new Error("Tile is unavailable");
          return createImageBitmap(result.blob);
        });
      const promise = Promise.race([requestPromise, timeoutPromise])
        .then((bitmap) => {
          if (this.disposed) {
            bitmap.close();
            return;
          }
          const image = tileImageForTexture(bitmap, this.body);
          if (!image) {
            this.failed.add(key);
            return;
          }
          const texture = new THREE.Texture(image);
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.anisotropy = Math.min(4, this.renderer.capabilities.getMaxAnisotropy());
          texture.needsUpdate = true;
          this.cache.set(key, { texture, lastUsed: performance.now() });
          this.attachMesh(key, tile, texture);
          this.evictIfNeeded();
        })
        .catch(() => {
          if (!controller.signal.aborted || timedOut) this.failed.add(key);
        })
        .finally(() => {
          window.clearTimeout(timeout);
          this.activeCount -= 1;
          if (this.pending.get(key)?.controller === controller) this.pending.delete(key);
          this.refresh();
          this.pump();
        });
      this.activeCount += 1;
      this.pending.set(key, { controller, promise });
      this.setStatus("loading");
    }
  }

  private evictIfNeeded() {
    while (this.cache.size > CACHE_LIMIT) {
      let oldestKey: string | null = null;
      let oldest = Number.POSITIVE_INFINITY;
      for (const [key, record] of this.cache) {
        if (record.lastUsed < oldest) {
          oldest = record.lastUsed;
          oldestKey = key;
        }
      }
      if (oldestKey === null) break;
      const mesh = this.meshes.get(oldestKey);
      if (mesh) {
        this.group.remove(mesh);
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
        this.meshes.delete(oldestKey);
      }
      this.disposeTexture(this.cache.get(oldestKey)?.texture);
      this.cache.delete(oldestKey);
    }
  }

  private disposeTexture(texture: THREE.Texture | undefined) {
    if (!texture) return;
    const image = texture.image as { close?: () => void } | undefined;
    image?.close?.();
    texture.dispose();
  }

  dispose() {
    this.disposed = true;
    for (const pending of this.pending.values()) pending.controller.abort();
    this.pending.clear();
    this.failed.clear();
    for (const mesh of this.meshes.values()) {
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    }
    this.meshes.clear();
    for (const record of this.cache.values()) this.disposeTexture(record.texture);
    this.cache.clear();
    this.scene.remove(this.group);
  }
}
