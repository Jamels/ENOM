import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Compass, Minus, Plus, RotateCcw } from "lucide-react";
import type { AnyBody } from "../types";
import { formatCoords } from "../lib/missions";
import { GlobeTileOverlay, imageryAttribution } from "../lib/globeImagery";
import { planetaryColor } from "../planetaryTokens";

const MIN_CAMERA_DISTANCE = 1.15;
const MAX_CAMERA_DISTANCE_RATIO = 1.65;

function clampCameraDistance(distance: number, baseDistance: number): number {
  return Math.max(MIN_CAMERA_DISTANCE, Math.min(baseDistance * MAX_CAMERA_DISTANCE_RATIO, distance));
}

export type GlobeMarker = {
  id: string;
  label: string;
  sublabel?: string;
  lat: number;
  lon: number;
  kind: "selected" | "ranked" | "indexed" | "catalogue";
  rank?: number | null;
  score?: number | null;
};

type PlanetaryGlobeProps = {
  body: AnyBody;
  title: string;
  subtitle: string;
  markers: GlobeMarker[];
  selectedId: string | null;
  focusCoords: { lat: number; lon: number; token: number } | null;
  onSelectMarker: (id: string) => void;
  defaultCoords?: { lat: number; lon: number };
  className?: string;
};

function latLonToVec3(latDeg: number, lonDeg: number, radius = 1): THREE.Vector3 {
  const latRad = (latDeg * Math.PI) / 180;
  const lonRad = (lonDeg * Math.PI) / 180;
  const cosLat = Math.cos(latRad);
  return new THREE.Vector3(
    radius * cosLat * Math.cos(lonRad),
    radius * Math.sin(latRad),
    -radius * cosLat * Math.sin(lonRad),
  );
}

function normalizeLonSigned(lonDeg: number): number {
  const wrapped = ((lonDeg % 360) + 360) % 360;
  return wrapped > 180 ? wrapped - 360 : wrapped;
}

function shortestAngleDelta(fromDeg: number, toDeg: number): number {
  let diff = (((toDeg - fromDeg + 180) % 360) + 360) % 360 - 180;
  if (diff < -180) diff += 360;
  return diff;
}

function buildGraticule(): THREE.LineSegments {
  const positions: number[] = [];
  const r = 1.003;
  for (let lat = -60; lat <= 60; lat += 30) {
    const segments = 96;
    for (let i = 0; i < segments; i++) {
      const a = latLonToVec3(lat, (i / segments) * 360 - 180, r);
      const b = latLonToVec3(lat, ((i + 1) / segments) * 360 - 180, r);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  for (let lon = -180; lon < 180; lon += 30) {
    const segments = 72;
    for (let i = 0; i < segments; i++) {
      const latA = -90 + (i / segments) * 180;
      const latB = -90 + ((i + 1) / segments) * 180;
      const a = latLonToVec3(latA, lon, r);
      const b = latLonToVec3(latB, lon, r);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color: 0xe2e8f0,
    transparent: true,
    opacity: 0.14,
  });
  return new THREE.LineSegments(geometry, material);
}

const ATMOS_VERT = [
  "varying vec3 vNormal;",
  "varying vec3 vViewPos;",
  "void main() {",
  "  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);",
  "  vNormal = normalize(normalMatrix * normal);",
  "  vViewPos = -mvPosition.xyz;",
  "  gl_Position = projectionMatrix * mvPosition;",
  "}",
].join("\n");

const ATMOS_FRAG = [
  "uniform vec3 uColor;",
  "uniform float uStrength;",
  "varying vec3 vNormal;",
  "varying vec3 vViewPos;",
  "void main() {",
  "  float rim = 1.0 - max(0.0, dot(normalize(vNormal), normalize(vViewPos)));",
  "  float alpha = pow(rim, 3.2) * uStrength;",
  "  gl_FragColor = vec4(uColor, alpha);",
  "}",
].join("\n");

export function PlanetaryGlobe({
  body,
  title,
  subtitle,
  markers,
  selectedId,
  focusCoords,
  onSelectMarker,
  defaultCoords = { lat: 12, lon: 25 },
  className = "",
}: PlanetaryGlobeProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [showGrid, setShowGrid] = useState(true);
  const [textureReady, setTextureReady] = useState(false);
  const [webglError, setWebglError] = useState<string | null>(null);
  const [imageryStatus, setImageryStatus] = useState<"base" | "loading" | "active" | "unavailable">("base");
  const [imageryDate, setImageryDate] = useState<string | null>(null);
  const [viewHud, setViewHud] = useState({ lat: defaultCoords.lat, lon: defaultCoords.lon, zoom: 1 });

  const palette = {
    accent: planetaryColor(body),
    light: planetaryColor(body, "light"),
    deep: planetaryColor(body, "deep"),
    fallback: body === "earth" ? "#13314c" : body === "mars" ? "#5c2716" : "#3a3e47",
  };

  const camStateRef = useRef({
    lat: defaultCoords.lat,
    lon: normalizeLonSigned(defaultCoords.lon),
    dist: 4.1,
    baseDist: 4.1,
    targetLat: null as number | null,
    targetLon: null as number | null,
    targetDist: null as number | null,
    velLat: 0,
    velLon: 0,
    dragging: false,
    lastX: 0,
    lastY: 0,
    pointers: new Map<number, { x: number; y: number }>(),
    pinchDist: null as number | null,
  });

  const markerElsRef = useRef<Map<string, HTMLButtonElement>>(new Map());
  const gridRef = useRef<THREE.LineSegments | null>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const atmosRef = useRef<THREE.Mesh | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const tileOverlayRef = useRef<GlobeTileOverlay | null>(null);

  const markerVectors = useMemo(
    () =>
      markers.map((m) => ({
        id: m.id,
        vec: latLonToVec3(m.lat, m.lon, 1.006),
        normal: latLonToVec3(m.lat, m.lon, 1).normalize(),
      })),
    [markers],
  );
  const markerVectorsRef = useRef(markerVectors);
  markerVectorsRef.current = markerVectors;

  useEffect(() => {
    if (!focusCoords) return;
    const st = camStateRef.current;
    const clampedLat = Math.max(-86, Math.min(86, focusCoords.lat));
    const targetLon = normalizeLonSigned(focusCoords.lon);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      st.lat = clampedLat;
      st.lon = targetLon;
      st.targetLat = null;
      st.targetLon = null;
      st.velLat = 0;
      st.velLon = 0;
    } else {
      st.targetLat = clampedLat;
      st.targetLon = targetLon;
      st.velLat = 0;
      st.velLon = 0;
    }
  }, [focusCoords]);

  useEffect(() => {
    if (gridRef.current) {
      gridRef.current.visible = showGrid;
    }
  }, [showGrid]);

  useEffect(() => {
    const mat = materialRef.current;
    const atmos = atmosRef.current;
    if (!mat) return;
    tileOverlayRef.current?.dispose();
    tileOverlayRef.current = null;
    setImageryStatus("base");
    setImageryDate(null);
    if (sceneRef.current && rendererRef.current) {
      tileOverlayRef.current = new GlobeTileOverlay(
        body,
        sceneRef.current,
        setImageryStatus,
        setImageryDate,
        rendererRef.current,
      );
    }
    let cancelled = false;
    setTextureReady(false);
    const loader = new THREE.TextureLoader();
    loader.load(
      "/textures/" + body + ".jpg?v=20261114-globe-sources",
      (tex) => {
        if (cancelled) {
          tex.dispose();
          return;
        }
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 8;
        if (mat.map) mat.map.dispose();
        mat.map = tex;
        mat.bumpMap = tex;
        mat.bumpScale = body === "moon" ? 0.012 : body === "mars" ? 0.01 : 0.006;
        mat.roughness = body === "moon" ? 0.92 : body === "mars" ? 0.88 : 0.78;
        mat.color.set("#ffffff");
        mat.needsUpdate = true;
        setTextureReady(true);
      },
      undefined,
      () => {
        if (!cancelled) {
          mat.color.set(palette.fallback);
          mat.needsUpdate = true;
          setTextureReady(true);
        }
      },
    );
    if (atmos && atmos.material instanceof THREE.ShaderMaterial) {
      atmos.material.uniforms.uColor.value.set(palette.light);
      atmos.material.uniforms.uStrength.value =
        body === "earth" ? 0.55 : body === "mars" ? 0.35 : 0.14;
    }
    return () => {
      cancelled = true;
    };
  }, [body]);

  useEffect(() => {
    const container = stageRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch (err) {
      setWebglError(err instanceof Error ? err.message : "WebGL unavailable");
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    sceneRef.current = scene;
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 20);

    const sun = new THREE.DirectionalLight(0xfff8ee, 2.2);
    sun.position.set(4, 2.2, 4.5);
    scene.add(sun);

    const fill = new THREE.DirectionalLight(0x8bb8e8, 0.65);
    fill.position.set(-4, -1.5, -3);
    scene.add(fill);

    const ambient = new THREE.AmbientLight(0xdbe4f0, 0.85);
    scene.add(ambient);

    const geometry = new THREE.SphereGeometry(1, 72, 48);
    const material = new THREE.MeshStandardMaterial({
      color: body === "earth" ? "#13314c" : body === "mars" ? "#5c2716" : "#3a3e47",
      roughness: 0.85,
      metalness: 0.02,
    });
    materialRef.current = material;
    const globeMesh = new THREE.Mesh(geometry, material);
    scene.add(globeMesh);

    const tileOverlay = new GlobeTileOverlay(
      body,
      scene,
      setImageryStatus,
      setImageryDate,
      renderer,
    );
    tileOverlayRef.current = tileOverlay;
    rendererRef.current = renderer;

    const atmosGeo = new THREE.SphereGeometry(1.045, 64, 40);
    const atmosMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      side: THREE.BackSide,
      uniforms: {
        uColor: { value: new THREE.Color(planetaryColor(body, "light")) },
        uStrength: { value: body === "earth" ? 0.55 : body === "mars" ? 0.35 : 0.14 },
      },
      vertexShader: ATMOS_VERT,
      fragmentShader: ATMOS_FRAG,
    });
    const atmosMesh = new THREE.Mesh(atmosGeo, atmosMat);
    atmosRef.current = atmosMesh;
    scene.add(atmosMesh);

    const graticule = buildGraticule();
    graticule.visible = showGrid;
    gridRef.current = graticule;
    scene.add(graticule);

    const loader = new THREE.TextureLoader();
    loader.load(
      "/textures/" + body + ".jpg?v=20261114-globe-sources",
      (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
        if (material.map) material.map.dispose();
        material.map = tex;
        material.bumpMap = tex;
        material.bumpScale = body === "moon" ? 0.012 : body === "mars" ? 0.01 : 0.006;
        material.roughness = body === "moon" ? 0.92 : body === "mars" ? 0.88 : 0.78;
        material.color.set("#ffffff");
        material.needsUpdate = true;
        setTextureReady(true);
      },
      undefined,
      () => {
        setTextureReady(true);
      },
    );

    let width = container.clientWidth || 360;
    let height = container.clientHeight || 360;
    const computeBaseDistance = (w: number, h: number) => {
      const aspect = w / h;
      const vFovHalf = (36 * Math.PI) / 360;
      const hFovHalf = Math.atan(aspect * Math.tan(vFovHalf));
      const fill = 0.82;
      const distV = 1 / (fill * Math.sin(vFovHalf));
      const distH = 1 / (fill * Math.sin(hFovHalf));
      return Math.max(3.6, Math.min(8.2, Math.max(distV, distH)));
    };
    const updateSize = () => {
      if (!container) return;
      width = Math.max(200, container.clientWidth);
      height = Math.max(200, container.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      const st = camStateRef.current;
      const nextBase = computeBaseDistance(width, height);
      const ratio = st.baseDist > 0 ? st.dist / st.baseDist : 1;
      st.baseDist = nextBase;
      st.dist = clampCameraDistance(nextBase * ratio, nextBase);
      if (st.targetDist !== null) {
        st.targetDist = clampCameraDistance(st.targetDist, nextBase);
      }
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(container);

    let rafId = 0;
    let lastTime = performance.now();
    let hudTimer = 0;
    let tileUpdateTimer = 0;
    let previousTileView = "";
    let previousTileOverlay: GlobeTileOverlay | null = null;
    const camDir = new THREE.Vector3();
    const projected = new THREE.Vector3();

    const animate = (now: number) => {
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;
      const st = camStateRef.current;

      if (!st.dragging) {
        if (st.targetLat !== null && st.targetLon !== null) {
          const alpha = 1 - Math.exp(-dt * 6.5);
          const dLat = st.targetLat - st.lat;
          const dLon = shortestAngleDelta(st.lon, st.targetLon);
          st.lat += dLat * alpha;
          st.lon = normalizeLonSigned(st.lon + dLon * alpha);
          if (Math.abs(dLat) < 0.05 && Math.abs(dLon) < 0.05) {
            st.lat = st.targetLat;
            st.lon = st.targetLon;
            st.targetLat = null;
            st.targetLon = null;
          }
        } else if (Math.abs(st.velLat) > 0.001 || Math.abs(st.velLon) > 0.001) {
          st.lat = Math.max(-86, Math.min(86, st.lat + st.velLat * dt * 60));
          st.lon = normalizeLonSigned(st.lon + st.velLon * dt * 60);
          const friction = Math.pow(0.92, dt * 60);
          st.velLat *= friction;
          st.velLon *= friction;
          if (Math.abs(st.velLat) < 0.005) st.velLat = 0;
          if (Math.abs(st.velLon) < 0.005) st.velLon = 0;
        }
      }

      if (st.targetDist !== null) {
        const alpha = 1 - Math.exp(-dt * 8);
        st.dist += (st.targetDist - st.dist) * alpha;
        if (Math.abs(st.targetDist - st.dist) < 0.003) {
          st.dist = st.targetDist;
          st.targetDist = null;
        }
      }

      const pos = latLonToVec3(st.lat, st.lon, st.dist);
      camera.position.copy(pos);
      camera.lookAt(0, 0, 0);
      camera.updateMatrixWorld();

      const camNorm = pos.clone().normalize();
      const rightVec = new THREE.Vector3(0, 1, 0).cross(camNorm).normalize();
      const upVec = camNorm.clone().cross(rightVec).normalize();
      sun.position
        .copy(camNorm)
        .multiplyScalar(4.0)
        .addScaledVector(rightVec, 1.8)
        .addScaledVector(upVec, 1.5);

      renderer.render(scene, camera);

      if (now - tileUpdateTimer > 110) {
        tileUpdateTimer = now;
        const zoom = st.baseDist / st.dist;
        const tileView = [
          Math.round(st.lat * 2) / 2,
          Math.round(st.lon * 2) / 2,
          Math.round(zoom * 20) / 20,
          Math.round(width),
          Math.round(height),
        ].join(":");
        const tileOverlay = tileOverlayRef.current;
        if (tileOverlay && (tileOverlay !== previousTileOverlay || tileView !== previousTileView)) {
          previousTileView = tileView;
          previousTileOverlay = tileOverlay;
          const pixelRatio = renderer.getPixelRatio();
          tileOverlay.update(
            st.lat,
            st.lon,
            zoom,
            width * pixelRatio,
            height * pixelRatio,
            st.dist,
          );
        }
      }

      camDir.copy(camera.position).normalize();
      const list = markerVectorsRef.current;
      for (let i = 0; i < list.length; i++) {
        const item = list[i];
        const el = markerElsRef.current.get(item.id);
        if (!el) continue;
        const dot = item.normal.dot(camDir);
        if (dot <= 0.08) {
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          continue;
        }
        projected.copy(item.vec).project(camera);
        const px = (projected.x * 0.5 + 0.5) * width;
        const py = (-projected.y * 0.5 + 0.5) * height;
        const horizonFade = dot < 0.28 ? (dot - 0.08) / 0.2 : 1;
        el.style.opacity = String(horizonFade.toFixed(2));
        el.style.pointerEvents = "auto";
        el.style.transform =
          "translate3d(" + px.toFixed(1) + "px, " + py.toFixed(1) + "px, 0) translate(-50%, -50%)";
      }

      if (now - hudTimer > 120) {
        hudTimer = now;
        const zoomFactor = Number((st.baseDist / st.dist).toFixed(2));
        setViewHud((prev) =>
          Math.abs(prev.lat - st.lat) < 0.2 &&
          Math.abs(prev.lon - st.lon) < 0.2 &&
          prev.zoom === zoomFactor
            ? prev
            : { lat: st.lat, lon: st.lon, zoom: zoomFactor },
        );
      }

      rafId = requestAnimationFrame(animate);
    };
    rafId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafId);
      observer.disconnect();
      tileOverlay.dispose();
      geometry.dispose();
      if (material.map) material.map.dispose();
      material.dispose();
      atmosGeo.dispose();
      atmosMat.dispose();
      graticule.geometry.dispose();
      (graticule.material as THREE.Material).dispose();
      renderer.dispose();
      if (tileOverlayRef.current === tileOverlay) tileOverlayRef.current = null;
      sceneRef.current = null;
      rendererRef.current = null;
      materialRef.current = null;
      atmosRef.current = null;
      gridRef.current = null;
    };
  }, []);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button[data-marker='true']")) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const st = camStateRef.current;
    st.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    st.targetLat = null;
    st.targetLon = null;
    st.velLat = 0;
    st.velLon = 0;
    if (st.pointers.size === 1) {
      st.dragging = true;
      st.lastX = e.clientX;
      st.lastY = e.clientY;
      st.pinchDist = null;
    } else if (st.pointers.size === 2) {
      const pts = Array.from(st.pointers.values());
      st.pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const st = camStateRef.current;
    if (!st.pointers.has(e.pointerId)) return;
    st.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (st.pointers.size === 2) {
      const pts = Array.from(st.pointers.values());
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (st.pinchDist !== null && dist > 0) {
        const ratio = st.pinchDist / dist;
        st.dist = clampCameraDistance(st.dist * ratio, st.baseDist);
        st.targetDist = null;
      }
      st.pinchDist = dist;
      return;
    }
    if (!st.dragging) return;
    const dx = e.clientX - st.lastX;
    const dy = e.clientY - st.lastY;
    st.lastX = e.clientX;
    st.lastY = e.clientY;
    const sensitivity = 0.22 * (st.dist / st.baseDist);
    const dLon = -dx * sensitivity;
    const dLat = dy * sensitivity;
    st.lon = normalizeLonSigned(st.lon + dLon);
    st.lat = Math.max(-86, Math.min(86, st.lat + dLat));
    st.velLon = dLon * 0.65;
    st.velLat = dLat * 0.65;
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const st = camStateRef.current;
    st.pointers.delete(e.pointerId);
    if (st.pointers.size < 2) st.pinchDist = null;
    if (st.pointers.size === 0) st.dragging = false;
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const st = camStateRef.current;
    const delta = e.deltaY * 0.0022 * (st.baseDist / 3.6);
    st.dist = clampCameraDistance(st.dist + delta, st.baseDist);
    st.targetDist = null;
  };

  const zoomBy = (factor: number) => {
    const st = camStateRef.current;
    const base = st.targetDist ?? st.dist;
    st.targetDist = clampCameraDistance(base * factor, st.baseDist);
  };

  const resetView = () => {
    const st = camStateRef.current;
    st.targetLat = defaultCoords.lat;
    st.targetLon = normalizeLonSigned(defaultCoords.lon);
    st.targetDist = st.baseDist;
  };

  const hoveredMarker = hoveredId ? markers.find((m) => m.id === hoveredId) ?? null : null;

  return (
    <div
      className={
        "relative flex flex-col rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] overflow-hidden " +
        className
      }
    >
      <div className="relative z-10 flex items-center justify-between gap-2 px-4 pt-3 pb-1">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="inline-block w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: palette.accent }}
          />
          <div className="min-w-0">
            <h2 className="font-display text-sm font-medium truncate" style={{ color: palette.accent }}>
              {title}
            </h2>
            <p className="text-[10px] leading-4 text-[var(--text-muted)] truncate" title={subtitle}>
              {subtitle}
              {body === "earth" && imageryDate ? ` · ${imageryDate}` : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => setShowGrid((v) => !v)}
            title={showGrid ? "Hide 30° coordinate grid" : "Show 30° coordinate grid"}
            aria-pressed={showGrid}
            className={
              "pressable inline-flex items-center justify-center w-7 h-7 rounded-lg border text-xs " +
              (showGrid
                ? "border-[var(--border-strong)] bg-white/8 text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-muted)] hover-surface")
            }
          >
            <Compass className="w-4 h-4" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={() => zoomBy(0.84)}
            aria-label={"Zoom in on " + title}
            className="pressable inline-flex items-center justify-center w-7 h-7 rounded-lg border border-transparent text-[var(--text-secondary)] hover-surface"
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={() => zoomBy(1.18)}
            aria-label={"Zoom out on " + title}
            className="pressable inline-flex items-center justify-center w-7 h-7 rounded-lg border border-transparent text-[var(--text-secondary)] hover-surface"
          >
            <Minus className="w-4 h-4" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={resetView}
            aria-label={"Reset " + title + " view"}
            title="Reset globe view"
            className="pressable inline-flex items-center justify-center w-7 h-7 rounded-lg border border-transparent text-[var(--text-secondary)] hover-surface"
          >
            <RotateCcw className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      <div
        ref={stageRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
        className="relative flex-1 min-h-[260px] cursor-grab active:cursor-grabbing select-none"
        style={{ touchAction: "none" }}
      >
        <canvas ref={canvasRef} className="block w-full h-full" />

        {!textureReady && !webglError && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-mono-tabular text-slate-400 bg-black/50 px-2.5 py-1 rounded-md border border-white/10">
              Loading {title} imagery…
            </span>
          </div>
        )}

        {webglError && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
            <div className="max-w-xs rounded-xl border border-white/10 bg-[#121822] p-4 text-xs text-slate-300">
              WebGL globe rendering unavailable ({webglError}). Locations remain browsable in the side panels.
            </div>
          </div>
        )}

        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          {markers.map((m) => {
            const isSelected = m.id === selectedId;
            const isHovered = m.id === hoveredId;
            const isRanked = m.kind === "ranked" && m.rank != null;
            const isTopThree = isRanked && (m.rank ?? 99) <= 3;
            return (
              <button
                key={m.id}
                type="button"
                data-marker="true"
                ref={(el) => {
                  if (el) markerElsRef.current.set(m.id, el);
                  else markerElsRef.current.delete(m.id);
                }}
                onClick={(ev) => {
                  ev.stopPropagation();
                  onSelectMarker(m.id);
                }}
                onMouseEnter={() => setHoveredId(m.id)}
                onMouseLeave={() => setHoveredId((prev) => (prev === m.id ? null : prev))}
                onFocus={() => setHoveredId(m.id)}
                onBlur={() => setHoveredId((prev) => (prev === m.id ? null : prev))}
                aria-label={m.label + " (" + formatCoords(m.lat, m.lon, body) + ")"}
                style={{
                  left: 0,
                  top: 0,
                  zIndex: isSelected ? 30 : isHovered ? 25 : isTopThree ? 20 : 10,
                }}
                className="group absolute focus:outline-none"
              >
                <span className="relative flex items-center justify-center">
                  {isSelected && (
                    <span
                      className="absolute -inset-2 rounded-full border-2"
                      style={{ borderColor: palette.light }}
                    />
                  )}
                  {isTopThree ? (
                    <span
                      className="flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-full text-[10px] font-mono-tabular font-semibold shadow-sm transition-transform"
                      style={{
                        backgroundColor: isSelected ? palette.light : palette.accent,
                        color: "#080b10",
                        border: `1.5px solid ${palette.deep}`,
                      }}
                    >
                      {m.rank}
                    </span>
                  ) : m.kind === "catalogue" ? (
                    <span
                      className="block w-14 h-14 rounded-full border-[8px] bg-[#080b10]/80 transition-transform group-hover:scale-105"
                      style={{
                        borderColor: isSelected ? palette.light : palette.deep,
                      }}
                    />
                  ) : (
                    <span
                      className="block rounded-full border-[4px] border-[#080b10] transition-transform group-hover:scale-105"
                      style={{
                        backgroundColor: isSelected ? palette.light : palette.accent,
                        width: isSelected ? "48px" : "42px",
                        height: isSelected ? "48px" : "42px",
                      }}
                    />
                  )}
                  {(isSelected || isHovered) && (
                    <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md border border-white/15 bg-[#0c1118]/92 px-2 py-0.5 text-[11px] font-medium text-slate-100 backdrop-blur-sm shadow-md">
                      {m.label}
                      {m.score != null && (
                        <span className="ml-1.5 font-mono-tabular text-[10px] text-[var(--text-secondary)]">
                          {(m.score * 100).toFixed(0)}%
                        </span>
                      )}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>

      </div>

      <div className="relative z-10 flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-void)]/60 px-4 py-2 text-xs text-[var(--text-muted)]">
        <span className="font-mono-tabular truncate">
          {hoveredMarker
            ? hoveredMarker.label + " · " + formatCoords(hoveredMarker.lat, hoveredMarker.lon, body)
            : formatCoords(viewHud.lat, viewHud.lon, body) + " · " + viewHud.zoom.toFixed(1) + "×"}
        </span>
        <span className="font-mono-tabular shrink-0" title={`${imageryAttribution(body)}${body === "earth" && imageryDate ? ` · ${imageryDate}` : ""}`}>
          {imageryStatus === "active"
            ? `${body === "earth" ? "NASA GIBS" : "NASA Trek"} detail active`
            : imageryStatus === "loading"
              ? "NASA detail loading"
              : imageryStatus === "unavailable"
                ? "NASA detail unavailable · base map"
                : `${markers.length} ${markers.length === 1 ? "site" : "sites"}`}
        </span>
      </div>
    </div>
  );
}
