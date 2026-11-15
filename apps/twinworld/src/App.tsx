import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { motion } from "motion/react";
import { ArrowLeftRight, ArrowUpRight, Database, HardDrive, Info } from "lucide-react";
import enomLogo from "../../../ENOM.png";
import { api, type AnalogueProfile, type DiscoveryRank, type DiscoveryRankRow, type DiscoveryDimensionScore } from "./lib/api";
import { planetaryColor } from "./planetaryTokens";
import {
  EQUIPMENT_PROFILES,
  formatCoords,
  getEquipmentProfile,
  humanizeGroup,
  inferEquipmentTagsForTarget,
} from "./lib/missions";
import type {
  CatalogueEntry,
  Comparison,
  DatasetInfo,
  EarthCandidate,
  EquipmentId,
  PlanetaryBody,
  PlanetaryTarget,
  Region,
  ScoreConfig,
  ScorecardResult,
  ScorecardSite,
  SearchResponse,
} from "./types";
import { EquipmentIcon, PlanetBadgeDot } from "./components/EquipmentIcon";
import { PlanetaryGlobe, type GlobeMarker } from "./components/PlanetaryGlobe";
import { DimensionLine } from "./components/CoordinateDiscoveryPanel";
import { TargetSidebar } from "./components/TargetSidebar";
import { EvidenceCoveragePanel } from "./components/EvidenceCoveragePanel";
import { EarthAnalogueSidebar } from "./components/EarthAnalogueSidebar";
import { PlanetBaselineBar } from "./components/PlanetBaselineBar";
import { ComparisonModal } from "./components/ComparisonModal";
import { DatasetsDialog } from "./components/DatasetsDialog";
import { OfflineMapsDialog } from "./components/OfflineMapsDialog";

type IndexedContext = { observation_id: string; dataset_id?: string; name?: string; source_url?: string; source_catalog_url?: string; observed_cell_count?: number; grid_cell_count?: number; observed_cell_fraction?: number; valid_pixel_fraction?: number; measurements?: { name: string; value: number | null; units: string; availability: string; spatial_scale_m?: number | null; uncertainty?: { description?: string | null } | null }[]; land_cover?: { status?: string; valid_fraction?: number; group_fractions?: Record<string, number>; source_url?: string; sample_method?: string }; uncertainty_note?: string; missing_data_semantics?: string; eligible_for_ranking?: boolean; index_center: { latitude_deg: number; longitude_east_deg: number }; index_footprint?: number[][] };
type IndexedResult = { score?: number | null; evidence_coverage?: number; dimension_scores?: DiscoveryDimensionScore[]; context: IndexedContext; evidence_class: string; similarity_score: number; matched_variable_count: number; variables: { name: string; reference_value: number | null; earth_value: number | null; difference: number | null; units: string; score: number | null; reference_spatial_scale_m?: number; earth_spatial_scale_m?: number }[] };
const INITIAL_TERRAIN_WEIGHTS: Record<string, number> = { elevation_range: 0.2, mean_slope: 0.28, slope_p90: 0.24, median_local_relief_3x3: 0.16, median_roughness_3x3: 0.12 };

function targetCoverage(target: PlanetaryTarget) {
  const region = target.pilotRegion;
  const site = target.scorecardSite;
  const measurements = site?.measurements ?? region?.measurements ?? [];
  const terrainContext = region?.terrain_contexts.find(
    (context) => context.observed_cell_fraction != null || context.valid_pixel_fraction != null,
  );
  const supportFraction = site?.data_coverage.observed_cell_fraction ?? terrainContext?.observed_cell_fraction ?? terrainContext?.valid_pixel_fraction ?? null;
  const support = supportFraction == null ? null : {
    label: site?.dataset_id.includes("mola") || terrainContext?.dataset_id.includes("mola") ? "MOLA observed-bin support" : "Terrain grid support",
    count: site?.data_coverage.observed_cell_count ?? terrainContext?.observed_cell_count ?? terrainContext?.valid_pixel_count ?? null,
    total: site?.data_coverage.grid_cell_count ?? terrainContext?.grid_cell_count ?? null,
    fraction: supportFraction,
    note: site?.data_coverage.note ?? terrainContext?.missing_data_semantics ?? null,
  };
  const availableContext = [
    ...(site?.environmental_evidence ? [site.environmental_evidence.dataset_id] : []),
    ...(site?.geology_evidence ? ["Regional geology"] : []),
    ...(region?.available_evidence ?? [])
      .filter((item) => !["surface_imagery", "visual_embedding", "terrain_dem", "geology"].includes(item))
      .map((item) => item.replaceAll("_", " ")),
  ];
  const unavailableContext = (region?.unavailable_evidence ?? ["surface_imagery", "visual_embedding", "terrain_dem", "geology", "mineralogy", "thermal"])
    .filter((item) => !(item === "terrain_dem" && measurements.some((measurement) => measurement.availability === "available" && measurement.value !== null)))
    .filter((item) => !(item === "geology" && site?.geology_evidence))
    .filter((item) => !(item === "thermal" && site?.environmental_evidence))
    .map((item) => item.replaceAll("_", " "));
  const sources = [
    ...(region?.source_url ? [{ label: `${region.provider} image record`, url: region.source_url }] : []),
    ...(site?.source_url ? [{ label: `${site.dataset_id} terrain source`, url: site.source_url }] : []),
    ...(region?.terrain_contexts ?? []).flatMap((context) => context.source_url ? [{ label: `${context.dataset_id} terrain source`, url: context.source_url }] : []),
  ];
  return {
    imagery: {
      label: !region ? "No image linked to this place" : region.label_status === "verified"
        ? "Verified image observation indexed"
        : `Provisional image observation · ${region.label_status.replaceAll("_", " ")}`,
      available: Boolean(region),
    },
    visual: {
      label: region?.available_evidence.includes("visual_embedding") ? "Image features indexed" : "No visual features indexed",
      available: region?.available_evidence.includes("visual_embedding") ?? false,
    },
    measurements,
    support,
    availableContext,
    unavailableContext,
    limitations: [
      ...(site?.data_quality ? [site.data_quality] : []),
      ...(site?.data_coverage.note ? [site.data_coverage.note] : []),
    ],
    sources,
  };
}

export function App() {
  const [body, setBody] = useState<PlanetaryBody>("mars");
  const [surfacePoint, setSurfacePoint] = useState<{ lat: number; lon: number } | null>(null);
  const [surfaceContext, setSurfaceContext] = useState<IndexedContext | null>(null);
  const [surfaceResults, setSurfaceResults] = useState<IndexedResult[]>([]);
  const [surfaceEarthId, setSurfaceEarthId] = useState<string | null>(null);
  const [surfaceStatus, setSurfaceStatus] = useState("");
  const [coverageContexts, setCoverageContexts] = useState<IndexedContext[]>([]);
  const [outsideCoverage, setOutsideCoverage] = useState(false);
  const [terrainWeights, setTerrainWeights] = useState(INITIAL_TERRAIN_WEIGHTS);
  const [surfaceLandCoverFilters, setSurfaceLandCoverFilters] = useState<Record<string, number>>({});
  const surfaceRequest = useRef(0);
  const surfaceAbort = useRef<AbortController | null>(null);
  const weightTimer = useRef<number | null>(null);

  useEffect(() => {
    surfaceRequest.current++;
    surfaceAbort.current?.abort();
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    setSurfacePoint(null);
    setSurfaceContext(null);
    setSurfaceResults([]);
    setSurfaceEarthId(null);
    setSurfaceStatus("");
    setOutsideCoverage(false);
    setCoverageContexts([]);
    const controller = new AbortController();
    fetch(`/api/discovery/coverage?body=${body}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Coverage index unavailable");
        return response.json();
      })
      .then((data) => setCoverageContexts(data.contexts as IndexedContext[]))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSurfaceStatus(error instanceof Error ? error.message : "Coverage unavailable");
      });
    return () => { controller.abort(); surfaceAbort.current?.abort(); if (weightTimer.current !== null) window.clearTimeout(weightTimer.current); };
  }, [body]);

  const selectSurface = async (
    point: { lat: number; lon: number },
    selectedWeights = terrainWeights,
    selectedLandCoverFilters = surfaceLandCoverFilters,
    selectedDimensionWeights = discoveryWeights,
  ) => {
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    const sequence = ++surfaceRequest.current;
    surfaceAbort.current?.abort();
    const controller = new AbortController();
    surfaceAbort.current = controller;
    setSurfacePoint(point);
    setSurfaceContext(null);
    setSurfaceResults([]);
    setSurfaceEarthId(null);
    setSurfaceStatus("Checking indexed coverage…");
    setOutsideCoverage(false);
    const post = async (url: string, payload: object) => {
      const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal });
      if (!response.ok) throw new Error(`Discovery service: ${response.status}`);
      return response.json();
    };
    try {
      const resolved = await post("/api/discovery/resolve", { body, latitude_deg: point.lat, longitude_east_deg: point.lon });
      if (sequence !== surfaceRequest.current) return;
      if (!resolved.contexts.length) {
        setOutsideCoverage(true);
        const windowCount = coverageContexts.length;
        setSurfaceStatus(windowCount
          ? `No precomputed terrain window covers this point. The globe basemap is global, but ENOM currently indexes only ${windowCount} localized ${body === "mars" ? "Mars" : "Moon"} terrain windows. Choose a marked window below to compare its coverage.`
          : "No precomputed terrain window covers this point. The terrain coverage list has not loaded yet; try one of the indexed terrain markers when it appears.");
        return;
      }
      const context = resolved.contexts[0] as IndexedContext;
      setSurfaceContext(context);
      setSurfaceStatus("Comparing terrain measurements…");
      const land_cover_max_fractions = Object.fromEntries(
        Object.entries(selectedLandCoverFilters).map(([name, fraction]) => [name, fraction]),
      );
      const result = await post("/api/discovery/rank", { index_id: resolved.index_id, context_id: context.observation_id, weights: selectedWeights, dimension_weights: selectedDimensionWeights, land_cover_max_fractions, result_limit: 10 });
      if (sequence !== surfaceRequest.current) return;
      const rows = result.recommendations as IndexedResult[];
      setSurfaceResults(rows);
      if (!rows.length) {
        setSurfaceStatus(Object.keys(selectedLandCoverFilters).length
          ? `No eligible Earth contexts satisfy the selected land-cover limits and evidence requirements. ${Number(result.land_cover_missing_count ?? 0)} contexts lack complete land-cover evidence; ${Number(result.land_cover_unsuitable_count ?? 0)} fail the selected limits.`
          : result.target.dataset_id === "mola-meg128"
            ? "No eligible Earth context is available for this sparse MOLA range. The observed-bin range remains an exploratory, limited-evidence measurement."
            : "The indexed area has insufficient compatible evidence for a ranking.");
        return;
      }
      setSurfaceEarthId(rows[0].context.observation_id);
      const filteredCount = Number(result.land_cover_filter_excluded_count ?? 0);
      const nearEquivalentCount = Number(result.near_equivalent_count ?? 0);
      setSurfaceStatus(`${rows[0].evidence_class === "limited_evidence" ? "Exploratory comparison · limited evidence" : "Multi-feature terrain comparison · experimental"}${nearEquivalentCount > 1 ? ` · ${nearEquivalentCount} near-equivalent candidates` : ""}${filteredCount ? ` · ${filteredCount} Earth contexts excluded (${Number(result.land_cover_missing_count ?? 0)} missing land-cover evidence; ${Number(result.land_cover_unsuitable_count ?? 0)} outside selected limits)` : ""}`);
      setRightFocus({ lat: rows[0].context.index_center.latitude_deg, lon: rows[0].context.index_center.longitude_east_deg, token: Date.now() });
    } catch (err) {
      if (sequence === surfaceRequest.current && !controller.signal.aborted) setSurfaceStatus(err instanceof Error ? err.message : "Discovery failed");
    }
  };
  const updateTerrainWeights = (next: Record<string, number>) => {
    setTerrainWeights(next);
    surfaceRequest.current++;
    surfaceAbort.current?.abort();
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    if (!surfacePoint) return;
    setSurfaceResults([]);
    setSurfaceEarthId(null);
    if (!Object.values(next).some((weight) => weight > 0)) {
      setSurfaceStatus("Choose at least one terrain weight above zero.");
      return;
    }
    setSurfaceStatus("Updating terrain weights…");
    weightTimer.current = window.setTimeout(() => { void selectSurface(surfacePoint, next); }, 200);
  };
  const updateDimensionWeights = (next: Record<string, number>) => {
    setDiscoveryWeights(next);
    if (!surfacePoint) return;
    surfaceRequest.current++;
    surfaceAbort.current?.abort();
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    setSurfaceResults([]);
    if (!Object.values(next).some((weight) => weight > 0)) {
      setSurfaceStatus("Choose at least one dimension weight above zero.");
      return;
    }
    weightTimer.current = window.setTimeout(() => {
      void selectSurface(surfacePoint, terrainWeights, surfaceLandCoverFilters, next);
    }, 200);
  };
  const updateSurfaceLandCoverFilters = (next: Record<string, number>) => {
    setSurfaceLandCoverFilters(next);
    surfaceRequest.current++;
    surfaceAbort.current?.abort();
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    if (!surfacePoint) return;
    setSurfaceResults([]);
    setSurfaceEarthId(null);
    setSurfaceStatus("Updating land-cover eligibility…");
    weightTimer.current = window.setTimeout(() => {
      void selectSurface(surfacePoint, terrainWeights, next);
    }, 200);
  };
  const [equipmentId, setEquipmentId] = useState<EquipmentId>("rover");
  const [searchMethod, setSearchMethod] = useState<"combined" | "terrain" | "visual">("combined");

  const [regions, setRegions] = useState<Region[]>([]);
  const [scoreSites, setScoreSites] = useState<ScorecardSite[]>([]);
  const [scoreConfig, setScoreConfig] = useState<ScoreConfig | null>(null);
  const [catalogueEntries, setCatalogueEntries] = useState<CatalogueEntry[]>([]);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>(
    () => getEquipmentProfile("rover").defaultWeights,
  );

  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [selectedEarthId, setSelectedEarthId] = useState<string | null>(null);
  const [leftFocus, setLeftFocus] = useState<{ lat: number; lon: number; token: number } | null>(null);
  const [rightFocus, setRightFocus] = useState<{ lat: number; lon: number; token: number } | null>(null);

  const [scorecard, setScorecard] = useState<ScorecardResult | null>(null);
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [analogueDiscovery, setAnalogueDiscovery] = useState<DiscoveryRank | null>(null);
  const [discoveryProfiles, setDiscoveryProfiles] = useState<AnalogueProfile[]>([]);
  const [discoveryProfileId, setDiscoveryProfileId] = useState("dunes");
  const [discoveryWeights, setDiscoveryWeights] = useState<Record<string, number>>({});
  const [discoveryBusy, setDiscoveryBusy] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bootError, setBootError] = useState("");

  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [datasetsOpen, setDatasetsOpen] = useState(false);
  const [offlineMapsOpen, setOfflineMapsOpen] = useState(false);
  const [mobileGlobeMode, setMobileGlobeMode] = useState<"dual" | "target" | "earth">("dual");
  const [mobilePanelTab, setMobilePanelTab] = useState<"targets" | "analogues">("targets");

  // Initial data bootstrap
  useEffect(() => {
    Promise.all([
      api.getRegions(200),
      api.getScorecardSites(),
      api.getScorecardConfig(),
      api.getCatalogue(),
      api.getDatasets(),
    ])
      .then(([regData, siteData, cfgData, catData, dsData]) => {
        setRegions(regData);
        setScoreSites(siteData.sites);
        setScoreConfig(cfgData);
        setCatalogueEntries(catData.entries);
        setDatasets(dsData);
      })
      .catch((err) => {
        setBootError(err instanceof Error ? err.message : "Failed to connect to ENOM API");
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.getAnalogueProfiles().then((profiles) => {
      if (cancelled) return;
      setDiscoveryProfiles(profiles);
      const initial = profiles.find((profile) => profile.id === discoveryProfileId) ?? profiles[0];
      if (initial) {
        setDiscoveryProfileId(initial.id);
        setDiscoveryWeights(initial.weights);
      }
    }).catch((err) => {
      if (!cancelled) setDiscoveryError(err instanceof Error ? err.message : "Could not load profiles");
    });
    return () => { cancelled = true; };
  }, []);

  const regionById = useMemo(() => {
    const map = new Map<string, Region>();
    for (const r of regions) map.set(r.id, r);
    return map;
  }, [regions]);

  // Unified planetary targets per body
  const targets = useMemo<PlanetaryTarget[]>(() => {
    const list: PlanetaryTarget[] = [];
    const seenIds = new Set<string>();

    // 1. Ingested scorecard sites first
    for (const site of scoreSites) {
      if (site.body !== body) continue;
      const matchedRegion = regionById.get(site.id) ?? null;
      // Catalogue membership and imagery label status are separate; keep scorecard
      // locations selectable even when their linked imagery is provisional.
      const isMareTranquillitatisContext = site.body === "moon" && site.id.startsWith("moon_mare_tranquillitatis");
      const placeId = site.id;
      const pilot = matchedRegion;
      seenIds.add(site.id);
      seenIds.add(placeId);
      const hasDiviner = Boolean(site.environmental_evidence);
      const hasGeology = Boolean(site.geology_evidence);
      const subtitleParts: string[] = [];
      if (site.body === "moon") {
        subtitleParts.push("LRO LOLA LDEM_64");
        if (hasDiviner) subtitleParts.push("Diviner thermal");
        if (hasGeology) subtitleParts.push("USGS geology");
      } else {
        subtitleParts.push("MOLA MEG128");
        if (pilot) subtitleParts.push("MRO CTX");
        if (hasDiviner) subtitleParts.push("TES thermal");
        if (hasGeology) subtitleParts.push("USGS geology");
      }
      const displayName =
        isMareTranquillitatisContext
          ? "Mare Tranquillitatis context · " + (site.id.split("_").at(-1) ?? "site")
          : site.id.startsWith("mars-dune-")
              ? "Mars Dune " + site.id.replace(/^mars-dune-(barchan_crescent_dune-|linear-)?/, "")
              : humanizeGroup(site.name.replaceAll(" ", "_")) + " · " + (site.id.split("-").at(-1) ?? "01");
      list.push({
        id: placeId,
        name: displayName,
        subtitle: subtitleParts.join(" · "),
        body,
        latitude_deg: site.latitude_deg,
        longitude_east_deg: site.longitude_east_deg,
        tier: pilot ? "scorecard_imagery" : "scorecard_only",
        scorecardSite: site,
        pilotRegion: pilot,
        catalogueEntry: null,
        equipmentTags: inferEquipmentTagsForTarget(site.id, displayName, body),
      });
    }

    // 2. Remaining Mars Pilot-100 regions
    if (body === "mars") {
      for (const r of regions) {
        // Provisional imagery remains discoverable, with its label status shown in the UI.
        if (r.body !== "mars" || seenIds.has(r.id)) continue;
        seenIds.add(r.id);
        const displayName = humanizeGroup(r.geographic_group) + " · " + (r.id.split("-").at(-1) ?? r.id);
        list.push({
          id: r.id,
          name: displayName,
          subtitle: r.provider + " · " + r.native_resolution_m + " m/px",
          body: "mars",
          latitude_deg: r.latitude_deg,
          longitude_east_deg: r.longitude_east_deg,
          tier: "imagery_only",
          scorecardSite: null,
          pilotRegion: r,
          catalogueEntry: null,
          equipmentTags: inferEquipmentTagsForTarget(r.id, displayName, "mars"),
        });
      }
    }

    // 3. NASA/USGS candidate catalogue entries for the selected body
    for (const entry of catalogueEntries) {
      if (entry.body !== body) continue;
      list.push({
        id: entry.id,
        name: entry.name,
        subtitle: humanizeGroup(entry.candidate_type) + " · " + entry.dataset_refs.slice(0, 2).join(", "),
        body,
        latitude_deg: entry.latitude_deg,
        longitude_east_deg: entry.longitude_east_deg,
        tier: "catalogue_only",
        scorecardSite: null,
        pilotRegion: null,
        catalogueEntry: entry,
        equipmentTags: inferEquipmentTagsForTarget(entry.id, entry.name, body, entry.candidate_type),
      });
    }

    return list;
  }, [body, scoreSites, regions, regionById, catalogueEntries]);

  // Auto-select default target when switching body or after initial load
  useEffect(() => {
    if (!targets.length) return;
    const currentStillValid = targets.some((t) => t.id === selectedTargetId);
    if (currentStillValid) return;
    const preferred =
      targets.find((t) => t.tier === "scorecard_imagery") ??
      targets.find((t) => t.tier === "scorecard_only" && t.scorecardSite?.environmental_evidence) ??
      targets.find((t) => t.tier === "scorecard_only") ??
      targets[0];
    if (preferred) {
      setSelectedTargetId(preferred.id);
      setLeftFocus({
        lat: preferred.latitude_deg,
        lon: preferred.longitude_east_deg,
        token: Date.now(),
      });
    }
  }, [targets, selectedTargetId]);

  const selectedTarget = useMemo(
    () => targets.find((t) => t.id === selectedTargetId) ?? null,
    [targets, selectedTargetId],
  );

  useEffect(() => {
    if (!selectedTarget || !discoveryProfiles.length || !Object.keys(discoveryWeights).length) {
      setAnalogueDiscovery(null);
      setDiscoveryBusy(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setDiscoveryBusy(true);
      setDiscoveryError("");
      const request = async () => {
        const resolved = await api.resolveDiscovery({ body: selectedTarget.body, latitude_deg: selectedTarget.latitude_deg, longitude_east_deg: selectedTarget.longitude_east_deg, signal: controller.signal });
        if (cancelled) return;
        const targetContext = resolved.contexts[0];
        if (!targetContext) throw new Error("No indexed terrain context covers this selected location. Its scorecard and image retrieval results remain available where supported.");
        const dimensionIds = Object.keys(discoveryProfiles.find((item) => item.id === discoveryProfileId)?.dimensions ?? {});
        const dimensionWeights = Object.fromEntries(dimensionIds.map((id) => [id, discoveryWeights[id] ?? 0]));
        const result = await api.rankDiscovery({
          index_id: resolved.index_id,
          context_id: targetContext.observation_id,
          weights,
          dimension_weights: dimensionWeights,
          result_limit: 10,
          signal: controller.signal,
        });
        if (!cancelled) setAnalogueDiscovery(result);
      };
      request()
        .catch((err) => {
          if (!cancelled && !controller.signal.aborted) {
            setAnalogueDiscovery(null);
            setDiscoveryError(err instanceof Error ? err.message : "Analogue ranking failed");
          }
        })
        .finally(() => { if (!cancelled) setDiscoveryBusy(false); });
    }, 180);
    return () => { cancelled = true; controller.abort(); window.clearTimeout(timer); };
  }, [selectedTarget, discoveryProfiles, discoveryProfileId, discoveryWeights, weights]);

  useEffect(() => {
    if (surfacePoint) return;
    const top = analogueDiscovery?.recommendations[0];
    if (!top) return;
    setSelectedEarthId(top.context.observation_id);
    setRightFocus({ lat: top.context.index_center.latitude_deg, lon: top.context.index_center.longitude_east_deg, token: Date.now() });
  }, [analogueDiscovery, surfacePoint]);

  // Execute backend scorecard & pilot search whenever target, equipment, weights, or retrieval mode change
  useEffect(() => {
    if (!selectedTarget) return;
    const equipment = getEquipmentProfile(equipmentId);
    let cancelled = false;

    const runQueries = async () => {
      setBusy(true);
      setError("");
      setScorecard(null);
      setSearchResponse(null);
      try {
        const promises: Promise<void>[] = [];
        if (selectedTarget.scorecardSite) {
          promises.push(
            api
              .rankScorecard({
                site_id: selectedTarget.scorecardSite.id,
                mission_objective: equipment.missionObjective,
                weights,
                limit: 30,
              })
              .then((res) => {
                if (!cancelled) setScorecard(res);
              }),
          );
        }
        if (selectedTarget.pilotRegion && selectedTarget.body === "mars") {
          promises.push(
            api
              .searchPilot({
                observation_id: selectedTarget.pilotRegion.id,
                profile: "aeolian",
                method: searchMethod,
                limit: 30,
              })
              .then((res) => {
                if (!cancelled) setSearchResponse(res);
              }),
          );
        }
        await Promise.all(promises);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Ranking request failed");
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    };

    void runQueries();
    return () => {
      cancelled = true;
    };
  }, [selectedTarget, equipmentId, weights, searchMethod]);

  // Merge scorecard candidates and Pilot-100 search results cleanly
  const earthCandidates = useMemo<EarthCandidate[]>(() => {
    const searchById = new Map(
      (searchResponse?.results ?? []).map((sr) => [sr.observation_id, sr]),
    );

    if (searchResponse?.results.length) {
      const scorecards = new Map(
        (scorecard?.candidates ?? []).map((candidate) => [candidate.observation_id, candidate]),
      );
      return searchResponse.results.slice(0, 15).map((sr) => {
        const pilot = regionById.get(sr.observation_id) ?? null;
        return {
          id: sr.observation_id,
          name: sr.location.geographic_group,
          regionLabel: humanizeGroup(sr.location.geographic_group) + " · " + (sr.observation_id.split("-").at(-1) ?? ""),
          latitude_deg: sr.location.latitude_deg,
          longitude_east_deg: sr.location.longitude_east_deg,
          rank: sr.rank,
          scorecardCandidate: scorecards.get(sr.observation_id) ?? null,
          searchResult: sr,
          pilotRegion: pilot,
          catalogueEntry: null,
        };
      });
    }

    if (scorecard?.candidates.length) {
      return scorecard.candidates.map((cand) => {
        const baseId = cand.observation_id.replace(/^nasadem:/, "");
        const pilot = regionById.get(baseId) ?? null;
        const sr = searchById.get(baseId) ?? null;
        const cleanName = pilot
          ? humanizeGroup(pilot.geographic_group)
          : cand.name.split(" · ")[0];
        return {
          id: cand.observation_id,
          name: cand.name,
          regionLabel: cleanName,
          latitude_deg: cand.latitude_deg,
          longitude_east_deg: cand.longitude_east_deg,
          rank: cand.rank,
          scorecardCandidate: cand,
          searchResult: sr,
          pilotRegion: pilot,
          catalogueEntry: null,
        };
      });
    }

    return [];
  }, [scorecard, searchResponse, regionById]);

  const earthCatalogue = useMemo(
    () => catalogueEntries.filter((e) => e.body === "earth"),
    [catalogueEntries],
  );

  // Auto-focus top Earth candidate when results refresh
  useEffect(() => {
    if (surfacePoint) return;
    if (!earthCandidates.length) {
      setSelectedEarthId(null);
      return;
    }
    const top = earthCandidates[0];
    setSelectedEarthId(top.id);
    setRightFocus({
      lat: top.latitude_deg,
      lon: top.longitude_east_deg,
      token: Date.now(),
    });
  }, [earthCandidates, surfacePoint]);

  const selectedEarthCandidate = useMemo<EarthCandidate | null>(() => {
    if (!selectedEarthId) return null;
    const ranked = earthCandidates.find((c) => c.id === selectedEarthId);
    if (ranked) return ranked;
    const cat = earthCatalogue.find((e) => e.id === selectedEarthId);
    if (cat) {
      return {
        id: cat.id,
        name: cat.name,
        regionLabel: cat.name,
        latitude_deg: cat.latitude_deg,
        longitude_east_deg: cat.longitude_east_deg,
        rank: null,
        scorecardCandidate: null,
        searchResult: null,
        pilotRegion: null,
        catalogueEntry: cat,
      };
    }
    return null;
  }, [selectedEarthId, earthCandidates, earthCatalogue]);

  // Load /api/comparisons when opening comparison modal for an indexed Mars-Earth pair
  const loadComparisonFor = useCallback(
    async (target: PlanetaryTarget, candidate: EarthCandidate) => {
      const earthPilotId = candidate.pilotRegion?.id ?? candidate.searchResult?.observation_id;
      if (target.pilotRegion && earthPilotId) {
        setComparisonBusy(true);
        setComparison(null);
        try {
          const data = await api.getComparison(target.pilotRegion.id, earthPilotId);
          setComparison(data);
        } catch {
          setComparison(null);
        } finally {
          setComparisonBusy(false);
        }
      } else {
        setComparison(null);
      }
    },
    [],
  );

  const handleSelectTarget = (target: PlanetaryTarget) => {
    if (weightTimer.current !== null) window.clearTimeout(weightTimer.current);
    surfaceRequest.current++;
    surfaceAbort.current?.abort();
    setSurfacePoint(null);
    setSurfaceContext(null);
    setSurfaceResults([]);
    setSurfaceEarthId(null);
    setSelectedTargetId(target.id);
    setAnalogueDiscovery(null);
    setLeftFocus({
      lat: target.latitude_deg,
      lon: target.longitude_east_deg,
      token: Date.now(),
    });
  };

  const handleSelectEarthCandidate = (candidate: EarthCandidate, openModal: boolean) => {
    setSelectedEarthId(candidate.id);
    setRightFocus({
      lat: candidate.latitude_deg,
      lon: candidate.longitude_east_deg,
      token: Date.now(),
    });
    if (openModal && selectedTarget) {
      void loadComparisonFor(selectedTarget, candidate);
      setComparisonOpen(true);
    }
  };

  const handleSelectCatalogueEarth = (entry: CatalogueEntry) => {
    setSelectedEarthId(entry.id);
    setRightFocus({
      lat: entry.latitude_deg,
      lon: entry.longitude_east_deg,
      token: Date.now(),
    });
    if (selectedTarget) {
      setComparison(null);
      setComparisonOpen(true);
    }
  };

  const handleSelectDiscoveredPlace = (row: DiscoveryRankRow) => {
    setSelectedEarthId(row.context.observation_id);
    setRightFocus({ lat: row.context.index_center.latitude_deg, lon: row.context.index_center.longitude_east_deg, token: Date.now() });
  };

  const handleDiscoveryProfileChange = (id: string) => {
    const profile = discoveryProfiles.find((item) => item.id === id);
    if (!profile) return;
    setDiscoveryProfileId(id);
    setDiscoveryWeights(profile.weights);
  };

  const handleEquipmentChange = (nextId: EquipmentId) => {
    setEquipmentId(nextId);
    const profile = getEquipmentProfile(nextId);
    setWeights(profile.defaultWeights);
  };

  const handleBodyChange = (nextBody: PlanetaryBody) => {
    if (nextBody === body) return;
    setBody(nextBody);
    setSelectedTargetId(null);
    setScorecard(null);
    setSearchResponse(null);
    setAnalogueDiscovery(null);
    setComparison(null);
  };

  // Left globe markers (cluster Pilot-100 Mars sub-patches only when needed, keep scorecard & catalogue pins distinct)
  const leftMarkers = useMemo<GlobeMarker[]>(() => {
    const seenLoc = new Set<string>();
    const result: GlobeMarker[] = [];
    for (const t of targets) {
      // Always include selected target, scorecard sites, and catalogue targets; deduplicate nearby sub-patches
      const bucketKey = t.latitude_deg.toFixed(1) + "," + t.longitude_east_deg.toFixed(1);
      if (t.id !== selectedTargetId && t.tier === "imagery_only" && seenLoc.has(bucketKey)) {
        continue;
      }
      seenLoc.add(bucketKey);
      result.push({
        id: t.id,
        label: t.name,
        lat: t.latitude_deg,
        lon: t.longitude_east_deg,
        kind: t.id === selectedTargetId ? "selected" : t.tier === "catalogue_only" ? "catalogue" : "indexed",
      });
    }
    return result;
  }, [targets, selectedTargetId]);

  // Right globe markers: ranked Earth analogues + catalogue Earth sites
  const rightMarkers = useMemo<GlobeMarker[]>(() => {
    const list: GlobeMarker[] = [];
    const seenGroup = new Set<string>();
    for (const c of earthCandidates) {
      const key = c.latitude_deg.toFixed(1) + "," + c.longitude_east_deg.toFixed(1);
      if (c.id !== selectedEarthId && seenGroup.has(key)) continue;
      seenGroup.add(key);
      list.push({
        id: c.id,
        label: c.regionLabel,
        lat: c.latitude_deg,
        lon: c.longitude_east_deg,
        kind: "ranked",
        rank: c.rank,
        score: c.scorecardCandidate?.similarity_score ?? c.searchResult?.cosine_similarity ?? null,
      });
    }
    const discoveredIds = new Set<string>();
    for (const row of analogueDiscovery?.recommendations ?? []) {
      const place = row.context;
      discoveredIds.add(place.observation_id);
      const key = place.index_center.latitude_deg.toFixed(1) + "," + place.index_center.longitude_east_deg.toFixed(1);
      if (place.observation_id !== selectedEarthId && seenGroup.has(key)) continue;
      seenGroup.add(key);
      list.push({
        id: place.observation_id,
        label: place.name ?? place.observation_id,
        lat: place.index_center.latitude_deg,
        lon: place.index_center.longitude_east_deg,
        kind: "ranked",
        rank: row.rank,
        score: row.score ?? null,
      });
    }
    for (const e of earthCatalogue) {
      if (discoveredIds.has(e.id)) continue;
      list.push({
        id: e.id,
        label: e.name,
        lat: e.latitude_deg,
        lon: e.longitude_east_deg,
        kind: "catalogue",
      });
    }
    return list;
  }, [earthCandidates, analogueDiscovery, earthCatalogue, selectedEarthId]);

  const activeEquipment = getEquipmentProfile(equipmentId);
  const activeEquipmentName =
    body === "moon" && activeEquipment.moonName
      ? activeEquipment.moonName
      : activeEquipment.name;
  const activeEquipmentSummary =
    body === "moon" && activeEquipment.moonSummary
      ? activeEquipment.moonSummary
      : activeEquipment.summary;

  return (
    <div className="min-h-dvh lg:h-dvh flex flex-col bg-[var(--bg-void)] text-[var(--text-primary)] lg:overflow-hidden">
      {/* Top Navigation & Equipment Bar */}
      <header className="sticky top-0 z-30 border-b border-[var(--border-subtle)] bg-[var(--bg-void)]/92 backdrop-blur-md pt-[env(safe-area-inset-top)]">
        <div className="px-3 sm:px-6 h-14 flex items-center justify-between gap-2 sm:gap-4">
          {/* Brand */}
          <div className="flex items-center gap-2 shrink-0">
            <img src={enomLogo} alt="" className="w-7 h-7 rounded-lg border border-[var(--border-subtle)] object-cover" />
            <span className="font-display text-base font-medium tracking-[-0.02em] text-[var(--text-primary)]">ENOM</span>
          </div>

          {/* Body Switcher: Mars / Moon */}
          <div
            role="tablist"
            aria-label="Target planetary body"
            className="relative inline-flex items-center p-1 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] shrink-0"
          >
            {(["mars", "moon"] as const).map((item) => {
              const active = body === item;
              return (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => handleBodyChange(item)}
                  className={
                    "relative z-10 inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors " +
                    (active ? "text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]")
                  }
                  style={active ? { color: planetaryColor(item) } : undefined}
                >
                  {active && (
                    <motion.span
                      layoutId="active-body-pill"
                      transition={{ type: "spring", bounce: 0.15, duration: 0.35 }}
                      className="absolute inset-0 rounded-lg bg-[var(--bg-hover)] border border-[var(--border-strong)] -z-10"
                    />
                  )}
                  <PlanetBadgeDot body={item} />
                  <span>{item === "mars" ? "Mars" : "Moon"}</span>
                </button>
              );
            })}
          </div>

          {/* Equipment Mission Factors Popover + Datasets Modal */}
          <div className="flex items-center gap-2 shrink-0">
            <Popover.Root>
              <Popover.Trigger className="pressable inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-panel)] hover-surface px-3 py-1.5 text-xs text-[var(--text-secondary)]">
                <Info className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
                <span className="hidden sm:inline">Mission factors</span>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Positioner sideOffset={8} align="end" className="z-50">
                  <Popover.Popup className="popover-popup w-80 sm:w-96 rounded-xl border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 shadow-2xl text-xs text-[var(--text-primary)] space-y-3">
                    <div className="flex items-center gap-2">
                      <EquipmentIcon id={equipmentId} className="w-4 h-4 text-[var(--text-muted)]" />
                      <div>
                        <div className="font-display text-sm font-medium text-[var(--text-primary)]">{activeEquipmentName}</div>
                        <div className="text-xs text-[var(--text-secondary)]">{activeEquipmentSummary}</div>
                      </div>
                    </div>
                    <div className="border-t border-[var(--border-subtle)] pt-3 space-y-1">
                      <div className="text-xs font-medium text-[var(--text-muted)]">Relevant factors</div>
                      {activeEquipment.keyFactors.map((f) => (
                        <div key={f} className="text-xs text-[var(--text-secondary)]">• {f}</div>
                      ))}
                    </div>
                    <div className="border-t border-[var(--border-subtle)] pt-3 space-y-1">
                      <div className="text-xs font-medium text-amber-300">Unscored gaps</div>
                      {activeEquipment.unscoredGaps.map((g) => (
                        <div key={g} className="text-xs text-[var(--text-muted)]">• {g}</div>
                      ))}
                    </div>
                  </Popover.Popup>
                </Popover.Positioner>
              </Popover.Portal>
            </Popover.Root>

            <button
              type="button"
              onClick={() => setOfflineMapsOpen(true)}
              className="pressable inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-panel)] hover-surface px-3 py-1.5 text-xs text-[var(--text-secondary)]"
              aria-label="Save maps offline"
            >
              <HardDrive className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
              <span className="hidden lg:inline">Save maps offline</span>
              <span className="lg:hidden">Offline</span>
            </button>

            <button
              type="button"
              onClick={() => setDatasetsOpen(true)}
              className="pressable inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-panel)] hover-surface px-3 py-1.5 text-xs text-[var(--text-secondary)]"
            >
              <Database className="w-4 h-4 text-[var(--text-muted)]" strokeWidth={1.5} />
              <span className="hidden md:inline">Datasets</span>
              <span className="font-mono-tabular text-xs text-[var(--text-muted)]">{datasets.length}</span>
            </button>
          </div>
        </div>

        {/* Compact Equipment Selector Strip */}
        <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-void)] px-4 sm:px-6 py-2 overflow-x-auto scroll-contain">
          <div className="flex items-center gap-1 min-w-max">
            {EQUIPMENT_PROFILES.map((item) => {
              const active = equipmentId === item.id;
              const label = body === "moon" && item.moonName ? item.moonName : item.name;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => handleEquipmentChange(item.id)}
                  aria-pressed={active}
                  className={
                    "pressable inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-medium " +
                    (active
                      ? "border-[var(--border-strong)] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "border-transparent bg-transparent text-[var(--text-muted)] hover-surface")
                  }
                >
                  <EquipmentIcon id={item.id} className="w-4 h-4 shrink-0" />
                  <span>{label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {bootError && (
        <div className="mx-4 mt-3 rounded-xl border border-rose-500/35 bg-rose-500/10 px-4 py-2.5 text-xs text-rose-200">
          ENOM service unavailable ({bootError}).
        </div>
      )}

      {/* Main Three-Area Workspace */}
      <main className="flex-1 min-h-0 p-4 flex flex-col lg:grid lg:grid-cols-[272px_minmax(0,1fr)_280px] xl:grid-cols-[280px_minmax(0,1fr)_304px] gap-4">
        {/* Left Rail (Desktop) */}
        <TargetSidebar
          body={body}
          targets={targets}
          selectedTargetId={selectedTargetId}
          equipmentId={equipmentId}
          searchMethod={searchMethod}
          scoreConfig={scoreConfig}
          weights={weights}
          onSelectTarget={handleSelectTarget}
          onSearchMethodChange={setSearchMethod}
          onWeightChange={(name, value) => setWeights((prev) => ({ ...prev, [name]: value }))}
          onResetWeights={() => setWeights(activeEquipment.defaultWeights)}
          className="hidden lg:flex lg:min-h-0"
        />

        {/* Centerpiece: Two Side-by-Side Interactive Globes */}
        <section className="flex flex-col min-w-0 min-h-0 gap-3">
          {/* Active Pair Connection Strip */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] px-4 py-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0 text-xs">
              <PlanetBadgeDot body={body} />
              <span className="font-medium truncate" style={{ color: planetaryColor(body) }}>
                {surfacePoint ? surfaceContext?.name ?? "Selected point" : selectedTarget?.name ?? "Select target"}
              </span>
              <ArrowLeftRight className="w-4 h-4 text-[var(--text-muted)] shrink-0" strokeWidth={1.5} />
              <PlanetBadgeDot body="earth" />
              <span className="font-medium truncate" style={{ color: planetaryColor("earth") }}>
                {surfacePoint ? surfaceResults.find(row => row.context.observation_id === surfaceEarthId)?.context.name ?? surfaceEarthId ?? "No Earth match" : selectedEarthCandidate?.regionLabel ?? "No Earth match"}
              </span>
              {!surfacePoint && selectedEarthCandidate?.scorecardCandidate?.similarity_score != null && (
                <span className="hidden sm:inline font-mono-tabular text-xs text-[var(--text-secondary)]">
                  · Terrain {selectedEarthCandidate.scorecardCandidate.similarity_score.toFixed(3)}
                </span>
              )}
              {!surfacePoint && selectedEarthCandidate?.searchResult && (
                <span className="hidden md:inline font-mono-tabular text-xs text-[var(--text-muted)]">
                  · Visual {selectedEarthCandidate.searchResult.cosine_similarity.toFixed(3)}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {/* Mobile globe view selector */}
              <div className="inline-flex lg:hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-void)] p-0.5 text-xs">
                {(["dual", "target", "earth"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMobileGlobeMode(m)}
                    className={"px-2 py-0.5 rounded-md capitalize " + (mobileGlobeMode === m ? "bg-[var(--bg-hover)] text-[var(--text-primary)]" : "text-[var(--text-muted)]")}
                  >
                    {m === "target" ? (body === "mars" ? "Mars" : "Moon") : m}
                  </button>
                ))}
              </div>
              {!surfacePoint && selectedTarget && selectedEarthCandidate && (
                <button
                  type="button"
                  onClick={() => {
                    void loadComparisonFor(selectedTarget, selectedEarthCandidate);
                    setComparisonOpen(true);
                  }}
                  className="pressable inline-flex items-center gap-1 rounded-lg bg-[var(--text-primary)] hover:bg-white text-[var(--bg-void)] px-3 py-1 text-xs font-medium"
                >
                  Scorecard
                  <ArrowUpRight className="w-3.5 h-3.5" strokeWidth={1.5} />
                </button>
              )}
            </div>
          </div>

          {surfacePoint ? (
            surfaceContext ? (
              <EvidenceCoveragePanel
                title={surfaceContext.name ?? surfaceContext.observation_id}
                subtitle={surfaceContext.dataset_id}
                imagery={{ label: "Not linked to this terrain context", available: false }}
                visual={{ label: "Not indexed for this terrain footprint", available: false }}
                measurements={surfaceContext.measurements ?? []}
                support={surfaceContext.observed_cell_fraction == null && surfaceContext.valid_pixel_fraction == null ? null : {
                  label: surfaceContext.dataset_id === "mola-meg128" ? "MOLA observed-bin support" : "Raster source-support coverage",
                  count: surfaceContext.observed_cell_count ?? null,
                  total: surfaceContext.grid_cell_count ?? null,
                  fraction: surfaceContext.observed_cell_fraction ?? surfaceContext.valid_pixel_fraction ?? null,
                  note: surfaceContext.missing_data_semantics ?? surfaceContext.uncertainty_note,
                }}
                availableContext={surfaceContext.land_cover?.status === "available" ? ["WorldCover land-cover classification"] : []}
                unavailableContext={["Thermal measurements", "Geology context"]}
                limitations={[
                  ...(surfaceContext.missing_data_semantics ? [surfaceContext.missing_data_semantics] : []),
                  ...(surfaceContext.dataset_id === "mola-meg128" ? ["The observed-bin elevation range may miss unsampled extremes; if observed-bin support meets the versioned minimum, any ranking remains exploratory and limited evidence."] : []),
                ]}
                sources={[
                  ...(surfaceContext.source_url ? [{ label: "Terrain source", url: surfaceContext.source_url }] : []),
                  ...(surfaceContext.land_cover?.source_url ? [{ label: "Land-cover source", url: surfaceContext.land_cover.source_url }] : []),
                ]}
              />
            ) : (
              <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-panel)] p-4 text-sm text-[var(--text-secondary)]" role="status">
                {surfaceStatus || "Checking indexed terrain coverage…"}
              </div>
            )
          ) : selectedTarget ? (
            <EvidenceCoveragePanel
              title={selectedTarget.name}
              subtitle={selectedTarget.subtitle}
              {...targetCoverage(selectedTarget)}
            />
          ) : null}

          {/* Dual Globe Stage */}
          <div
            className={
              "flex-1 min-h-[320px] grid gap-3 " +
              (mobileGlobeMode === "dual" ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1")
            }
          >
            {(mobileGlobeMode === "dual" || mobileGlobeMode === "target") && (
              <PlanetaryGlobe
                body={body}
                title={body === "mars" ? "Mars" : "Moon"}
                subtitle={
                  body === "mars"
                    ? "NASA Trek · Viking MDIM 2.1 · 232 m/px"
                    : "NASA Trek · LRO WAC global mosaic v2"
                }
                markers={[
                  ...leftMarkers.filter((marker) => !coverageContexts.some((context) => {
                    const lat1 = marker.lat * Math.PI / 180;
                    const lat2 = context.index_center.latitude_deg * Math.PI / 180;
                    const dlon = (marker.lon - context.index_center.longitude_east_deg) * Math.PI / 180;
                    const h = Math.sin((lat1 - lat2) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
                    return 2 * (body === "mars" ? 3396 : 1737.4) * Math.asin(Math.sqrt(Math.min(1, h))) < 15;
                  })),
                  ...coverageContexts.map((context) => ({ id: `coverage:${context.observation_id}`, label: `Indexed terrain: ${context.name ?? context.observation_id}${context.eligible_for_ranking ? "" : " · insufficient evidence"}`, lat: context.index_center.latitude_deg, lon: context.index_center.longitude_east_deg, kind: "indexed" as const })),
                  ...(surfacePoint ? [{ id: "surface-click", label: "Selected point", lat: surfacePoint.lat, lon: surfacePoint.lon, kind: "selected" as const }] : []),
                ]}
                onSelectSurface={selectSurface}
                footprint={surfaceContext?.index_footprint}
                selectedId={surfacePoint ? "surface-click" : selectedTargetId}
                focusCoords={leftFocus}
                defaultCoords={body === "mars" ? { lat: 8, lon: 135 } : { lat: 8, lon: 30 }}
                onSelectMarker={(id) => {
                  if (id.startsWith("coverage:")) {
                    const context = coverageContexts.find((item) => `coverage:${item.observation_id}` === id);
                    if (context) void selectSurface({ lat: context.index_center.latitude_deg, lon: context.index_center.longitude_east_deg });
                    return;
                  }
                  const t = targets.find((item) => item.id === id);
                  if (t) handleSelectTarget(t);
                }}
                className="min-h-[300px] lg:min-h-0"
              />
            )}
            {(mobileGlobeMode === "dual" || mobileGlobeMode === "earth") && (
              <PlanetaryGlobe
                body="earth"
                title="Earth"
                subtitle="NASA GIBS · Blue Marble (Aug 2004) · cloud-free global · 500 m/px"
                markers={surfacePoint ? surfaceResults.slice(0, 10).map((row, index) => ({ id: row.context.observation_id, label: row.context.name ?? row.context.observation_id, lat: row.context.index_center.latitude_deg, lon: row.context.index_center.longitude_east_deg, kind: "ranked" as const, rank: index + 1 })) : rightMarkers}
                selectedId={surfacePoint ? surfaceEarthId : selectedEarthId}
                focusCoords={rightFocus}
                defaultCoords={{ lat: -22, lon: 22 }}
                onSelectMarker={(id) => {
                  if (surfacePoint) {
                    const row = surfaceResults.find((item) => item.context.observation_id === id);
                    if (row) { setSurfaceEarthId(id); setRightFocus({ lat: row.context.index_center.latitude_deg, lon: row.context.index_center.longitude_east_deg, token: Date.now() }); }
                    return;
                  }
                  const discovered = analogueDiscovery?.recommendations.find((row) => row.context.observation_id === id);
                  if (discovered) {
                    handleSelectDiscoveredPlace(discovered);
                    return;
                  }
                  const cand = earthCandidates.find((c) => c.id === id);
                  if (cand) {
                    handleSelectEarthCandidate(cand, true);
                    return;
                  }
                  const cat = earthCatalogue.find((e) => e.id === id);
                  if (cat) {
                    handleSelectCatalogueEarth(cat);
                    return;
                  }
                }}
                className="min-h-[300px] lg:min-h-0"
              />
            )}
          </div>

          {coverageContexts.length > 0 && <p className="mx-3 mt-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-xs text-[var(--text-secondary)]">
            The globe shows global basemap imagery. Terrain comparisons are available only inside {coverageContexts.length} precomputed {body === "mars" ? "Mars" : "Moon"} windows, each roughly 10 km across. Click a marked window or choose one from the list below.
          </p>}
          {coverageContexts.length > 0 && <details open className="mx-3 mt-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-xs">
            <summary className="cursor-pointer text-[var(--text-primary)]">Terrain coverage · {coverageContexts.length} indexed regions · {coverageContexts.filter((context) => context.eligible_for_ranking).length} rank-eligible · {coverageContexts.filter((context) => !context.eligible_for_ranking).length} limited evidence</summary>
            <p className="mt-1 text-[var(--text-secondary)]">Choose an indexed region to inspect its measured footprint and find Earth comparisons.</p>
            <div className="mt-2 flex max-h-40 flex-wrap gap-2 overflow-auto">
              {coverageContexts.map((context) => <button key={context.observation_id} type="button" className="rounded border border-[var(--border-subtle)] px-2 py-1 text-left hover:bg-[var(--bg-hover)]" onClick={() => {
                const point = { lat: context.index_center.latitude_deg, lon: context.index_center.longitude_east_deg };
                setLeftFocus({ ...point, token: Date.now() });
                void selectSurface(point);
              }}>Find terrain near {context.name ?? context.observation_id}{!context.eligible_for_ranking && " · insufficient evidence"}</button>)}
            </div>
          </details>}

          {!surfacePoint && surfaceStatus && <p className="mx-3 mt-3 text-xs text-[var(--text-secondary)]" role="status">{surfaceStatus}</p>}
          {surfacePoint && <section className="m-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-xs" aria-live="polite">
            <p className="text-[var(--text-primary)]">{surfaceStatus}</p>
            <p className="mt-1 text-[var(--text-muted)]">Clicked {surfacePoint.lat.toFixed(4)}°, {surfacePoint.lon.toFixed(4)}°E {surfaceContext && `· analysed ${surfaceContext.observation_id}`}</p>
            {body === "moon" && <p className="mt-1 text-[var(--text-secondary)]">Moon coordinates use the LOLA mean-Earth frame; basemap alignment is unverified.</p>}
            <details className="mt-2">
              <summary className="cursor-pointer">Adjust eight dimension weights</summary>
              <p className="mt-1 text-[var(--text-secondary)]">Missing evidence is unscored. Terrain and operations share an evidence budget.</p>
              {Object.entries(discoveryProfiles[0]?.dimensions ?? {}).map(([id, dimension]) => <label key={id} className="mt-2 block">
                <span className="flex justify-between"><span>{dimension.label}</span><span>{(discoveryWeights[id] ?? 0).toFixed(2)}</span></span>
                <input type="range" min="0" max="1" step="0.01" value={discoveryWeights[id] ?? 0} aria-label={`${dimension.label} weight`} className="w-full" onChange={(event) => updateDimensionWeights({ ...discoveryWeights, [id]: Number(event.target.value) })} />
              </label>)}
            </details>
            <details className="mt-2">
              <summary className="cursor-pointer">Terrain weights</summary>
              <p className="mt-1 text-[var(--text-secondary)]">Only available, compatible measurements affect rankings.</p>
              {Object.entries(terrainWeights).map(([name, weight]) => <label key={name} className="mt-2 block">
                <span className="flex justify-between"><span>{name.replaceAll("_", " ")}</span><span>{weight.toFixed(2)}</span></span>
                <input type="range" min="0" max="1" step="0.01" value={weight} aria-label={`${name.replaceAll("_", " ")} terrain weight`} className="w-full" onChange={(event) => updateTerrainWeights({ ...terrainWeights, [name]: Number(event.target.value) })} />
              </label>)}
              <button type="button" className="mt-2 underline" onClick={() => updateTerrainWeights(INITIAL_TERRAIN_WEIGHTS)}>Reset terrain weights</button>
            </details>
            <details className="mt-2">
              <summary className="cursor-pointer">Land-cover limits (optional)</summary>
              <p className="mt-1 text-[var(--text-secondary)]">Set a maximum WorldCover share for a class. No class is excluded by default. Active limits require complete classification; unavailable or partial classification is not treated as zero.</p>
              {[["bare_sparse", "Bare or sparse"], ["forest", "Forest"], ["cropland", "Cropland"], ["built_up", "Built up"], ["snow_ice", "Snow and ice"], ["water", "Water"], ["grass_shrub_wetland", "Grass, shrub, wetland"]].map(([id, label]) => <label key={id} className="mt-2 flex items-center justify-between gap-3">
                <span>{label}</span>
                <span className="flex items-center gap-1"><input type="number" min="0" max="100" step="1" value={surfaceLandCoverFilters[id] == null ? "" : Math.round(surfaceLandCoverFilters[id] * 100)} placeholder="—" aria-label={`${label} maximum percent`} className="w-16 rounded border border-[var(--border-subtle)] bg-transparent px-2 py-1 text-right" onChange={(event) => {
                  const raw = event.target.value;
                  if (raw === "") {
                    const next = { ...surfaceLandCoverFilters };
                    delete next[id];
                    updateSurfaceLandCoverFilters(next);
                  } else {
                    const value = Number(raw);
                    if (Number.isFinite(value) && value >= 0 && value <= 100) updateSurfaceLandCoverFilters({ ...surfaceLandCoverFilters, [id]: value / 100 });
                  }
                }} /><span>% max</span></span>
              </label>)}
              <button type="button" className="mt-2 underline" onClick={() => updateSurfaceLandCoverFilters({})}>Clear land-cover limits</button>
            </details>
            {outsideCoverage && coverageContexts.map((context) => {
              const rad = Math.PI / 180;
              const lat1 = surfacePoint.lat * rad, lat2 = context.index_center.latitude_deg * rad;
              const deltaLon = (context.index_center.longitude_east_deg - surfacePoint.lon) * rad;
              const h = Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
              const km = 2 * (body === "mars" ? 3396 : 1737.4) * Math.asin(Math.sqrt(Math.min(1, h)));
              return { context, km };
            }).sort((a, b) => a.km - b.km).slice(0, 3).map(({ context, km }) => <button key={context.observation_id} type="button" className="mt-2 mr-3 underline" onClick={() => { const point = { lat: context.index_center.latitude_deg, lon: context.index_center.longitude_east_deg }; setLeftFocus({ ...point, token: Date.now() }); void selectSurface(point); }}>
              View {context.name ?? context.observation_id} ({Math.round(km)} km away)
            </button>)}
            {surfaceContext && <p className="mt-1 text-[var(--text-secondary)]">
              {surfaceContext.observed_cell_fraction != null ? `${surfaceContext.dataset_id === "mola-meg128" ? "Observed MOLA bins" : "Output cells passing source-support threshold"}: ${surfaceContext.observed_cell_count != null && surfaceContext.grid_cell_count != null ? `${surfaceContext.observed_cell_count}/${surfaceContext.grid_cell_count} · ` : ""}${(surfaceContext.observed_cell_fraction * 100).toFixed(1)}% · ` : "Direct observation support not quantified · "}
              {surfaceContext.missing_data_semantics ?? surfaceContext.uncertainty_note}
              {surfaceContext.source_url && <> · <a className="underline" href={surfaceContext.source_url} target="_blank" rel="noreferrer">Planetary data source</a></>}
            </p>}
            {surfaceContext?.measurements?.length ? <div className="mt-2 grid gap-1 sm:grid-cols-2" aria-label="Selected location terrain evidence">
              {surfaceContext.measurements.map((measurement) => {
                const available = measurement.availability === "available" && measurement.value !== null;
                return <p key={measurement.name} className={`rounded border px-2 py-1 ${available ? "border-emerald-500/20 text-emerald-200" : "border-amber-500/20 text-amber-200"}`}>
                  {measurement.name.replaceAll("_", " ")}: {available ? `${measurement.value} ${measurement.units}${measurement.spatial_scale_m ? ` · ${Math.round(measurement.spatial_scale_m)} m scale` : ""}` : `unavailable (${measurement.availability.replaceAll("_", " ")})`}
                </p>;
              })}
            </div> : surfaceContext && <p className="mt-2 text-[10px] text-amber-200">No terrain measurements are available for this indexed context.</p>}
            {surfaceContext?.dataset_id === "mola-meg128" && <p className="mt-1 text-[var(--text-secondary)]">The MOLA elevation range is calculated from observed bins only. Unobserved bins may contain larger extremes; any ranking is exploratory and limited evidence.</p>}
            {surfaceResults.slice(0, 10).map((row, index) => <details key={row.context.observation_id} className="mt-2 border-t border-[var(--border-subtle)] pt-2">
              <summary className="cursor-pointer" onClick={() => { setSurfaceEarthId(row.context.observation_id); setRightFocus({ lat: row.context.index_center.latitude_deg, lon: row.context.index_center.longitude_east_deg, token: Date.now() }); }}>
                {index + 1}. {row.context.name ?? row.context.observation_id} · similarity index {(row.score ?? row.similarity_score).toFixed(3)} · {row.matched_variable_count}/5 features · {row.evidence_class.replaceAll("_", " ")}
              </summary>
              <p className="mt-1 text-[var(--text-secondary)]">Partial observed similarity · {Math.round((row.evidence_coverage ?? 0) * 100)}% weighted evidence completeness. Results prioritize the number of independent evidence groups, then similarity. Terrain and operations share one group. This experimental index is not a probability or mission-suitability result.</p>
              {(row.dimension_scores ?? []).map((dimension) => <DimensionLine key={dimension.id} dimension={dimension} label={discoveryProfiles[0]?.dimensions[dimension.id]?.label ?? dimension.id} />)}
              <a className="mt-1 block underline" href={`/api/discovery/contexts/${encodeURIComponent(row.context.observation_id)}`} target="_blank" rel="noreferrer">Full context evidence and provenance</a>
              {row.context.land_cover && <p className="mt-1 text-[var(--text-secondary)]">WorldCover 2021 · {row.context.land_cover.status ?? "unavailable"}{row.context.land_cover.group_fractions && ` · ${Object.entries(row.context.land_cover.group_fractions).map(([name, fraction]) => `${name.replaceAll("_", " ")} ${(fraction * 100).toFixed(0)}%`).join(" · ")}`}{row.context.land_cover.source_url && <> · <a className="underline" href={row.context.land_cover.source_url} target="_blank" rel="noreferrer">classification source</a></>}</p>}
              {row.variables.map(v => <p key={v.name} className="mt-1">{v.name.replaceAll("_", " ")}: planetary {v.reference_value ?? "missing"}, Earth {v.earth_value ?? "missing"} {v.units} · difference {v.difference?.toFixed(2) ?? "unavailable"} · component {v.score?.toFixed(3) ?? "unavailable"}{v.reference_spatial_scale_m != null && ` · scales ${Math.round(v.reference_spatial_scale_m)} / ${Math.round(v.earth_spatial_scale_m ?? 0)} m`}</p>)}
              {row.context.uncertainty_note && <p className="mt-1 text-[var(--text-secondary)]">{row.context.uncertainty_note}</p>}
              {(row.context.source_url ?? row.context.source_catalog_url) && <a className="underline" href={row.context.source_url ?? row.context.source_catalog_url} target="_blank" rel="noreferrer">Earth data source</a>}
            </details>)}
          </section>}

          {/* Planet-to-Planet Baseline Strip */}
          <PlanetBaselineBar body={body} />
        </section>

        {/* Right Rail (Desktop) */}
        {!surfacePoint && <EarthAnalogueSidebar
          selectedTarget={selectedTarget}
          equipmentId={equipmentId}
          scorecard={scorecard}
          searchResponse={searchResponse}
          earthCandidates={earthCandidates}
          earthCatalogue={earthCatalogue}
          selectedEarthId={selectedEarthId}
          busy={busy}
          error={error}
          onSelectEarthCandidate={handleSelectEarthCandidate}
          onSelectCatalogueEarth={handleSelectCatalogueEarth}
          discoveryProfiles={discoveryProfiles}
          discoveryProfileId={discoveryProfileId}
          discoveryWeights={discoveryWeights}
          discoveryResult={analogueDiscovery}
          discoveryBusy={discoveryBusy}
          discoveryError={discoveryError}
          onDiscoveryProfileChange={handleDiscoveryProfileChange}
          onDiscoveryWeightChange={(id, value) => updateDimensionWeights({ ...discoveryWeights, [id]: value })}
          onResetDiscoveryWeights={() => {
            const profile = discoveryProfiles.find((item) => item.id === discoveryProfileId);
            if (profile) setDiscoveryWeights(profile.weights);
          }}
          onSelectDiscoveredPlace={handleSelectDiscoveredPlace}
          className="hidden lg:flex lg:min-h-0"
        />}

        {/* Mobile Tabbed Targets / Analogues Workspace (< lg) */}
        <section className="lg:hidden flex flex-col gap-3 pb-[env(safe-area-inset-bottom)]">
          <div className="grid grid-cols-2 gap-1 p-1 rounded-xl border border-[var(--border-subtle)] bg-[#0c1118]">
            <button
              type="button"
              onClick={() => setMobilePanelTab("targets")}
              className={"py-2 rounded-lg text-xs font-medium " + (mobilePanelTab === "targets" ? "bg-[#192231] text-slate-100" : "text-slate-400")}
            >
              {body === "mars" ? "Mars" : "Moon"} Targets ({targets.length})
            </button>
            <button
              type="button"
              onClick={() => setMobilePanelTab("analogues")}
              className={"py-2 rounded-lg text-xs font-medium " + (mobilePanelTab === "analogues" ? "bg-[#192231] text-slate-100" : "text-slate-400")}
            >
              Earth Analogues ({surfacePoint ? surfaceResults.length : analogueDiscovery?.results.length ?? earthCandidates.length})
            </button>
          </div>

          {mobilePanelTab === "targets" ? (
            <TargetSidebar
              body={body}
              targets={targets}
              selectedTargetId={selectedTargetId}
              equipmentId={equipmentId}
              searchMethod={searchMethod}
              scoreConfig={scoreConfig}
              weights={weights}
              onSelectTarget={(t) => {
                handleSelectTarget(t);
                setMobilePanelTab("analogues");
              }}
              onSearchMethodChange={setSearchMethod}
              onWeightChange={(name, value) => setWeights((prev) => ({ ...prev, [name]: value }))}
              onResetWeights={() => setWeights(activeEquipment.defaultWeights)}
              className="max-h-[480px]"
            />
          ) : surfacePoint ? (
            <p className="p-3 text-xs text-[var(--text-secondary)]">The selected location’s terrain comparisons are shown above.</p>
          ) : (
            <EarthAnalogueSidebar
              selectedTarget={selectedTarget}
              equipmentId={equipmentId}
              scorecard={scorecard}
              searchResponse={searchResponse}
              earthCandidates={earthCandidates}
              earthCatalogue={earthCatalogue}
              selectedEarthId={selectedEarthId}
              busy={busy}
              error={error}
              onSelectEarthCandidate={handleSelectEarthCandidate}
              onSelectCatalogueEarth={handleSelectCatalogueEarth}
              discoveryProfiles={discoveryProfiles}
              discoveryProfileId={discoveryProfileId}
              discoveryWeights={discoveryWeights}
              discoveryResult={analogueDiscovery}
              discoveryBusy={discoveryBusy}
              discoveryError={discoveryError}
              onDiscoveryProfileChange={handleDiscoveryProfileChange}
              onDiscoveryWeightChange={(id, value) => updateDimensionWeights({ ...discoveryWeights, [id]: value })}
              onResetDiscoveryWeights={() => {
                const profile = discoveryProfiles.find((item) => item.id === discoveryProfileId);
                if (profile) setDiscoveryWeights(profile.weights);
              }}
              onSelectDiscoveredPlace={handleSelectDiscoveredPlace}
              className="max-h-[520px]"
            />
          )}
        </section>
      </main>

      <ComparisonModal
        open={comparisonOpen}
        onOpenChange={setComparisonOpen}
        target={selectedTarget}
        earthCandidate={selectedEarthCandidate}
        scorecard={scorecard}
        comparison={comparison}
        comparisonBusy={comparisonBusy}
        equipmentId={equipmentId}
      />

      <DatasetsDialog
        open={datasetsOpen}
        onOpenChange={setDatasetsOpen}
        datasets={datasets}
      />
      <OfflineMapsDialog open={offlineMapsOpen} onOpenChange={setOfflineMapsOpen} />
    </div>
  );
}

export { formatCoords };
