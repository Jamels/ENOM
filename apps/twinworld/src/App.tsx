import { useCallback, useEffect, useMemo, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { motion } from "motion/react";
import { ArrowLeftRight, ArrowUpRight, Database, Info, Sparkles } from "lucide-react";
import { api } from "./lib/api";
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
import { TargetSidebar } from "./components/TargetSidebar";
import { EarthAnalogueSidebar } from "./components/EarthAnalogueSidebar";
import { PlanetBaselineBar } from "./components/PlanetBaselineBar";
import { ComparisonModal } from "./components/ComparisonModal";
import { DatasetsDialog } from "./components/DatasetsDialog";

export function App() {
  const [body, setBody] = useState<PlanetaryBody>("mars");
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
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bootError, setBootError] = useState("");

  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [datasetsOpen, setDatasetsOpen] = useState(false);
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
      const pilot = regionById.get(site.id) ?? null;
      seenIds.add(site.id);
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
        site.body === "moon" && hasDiviner
          ? "Mare Tranquillitatis (Diviner + LOLA)"
          : site.body === "moon"
            ? "Mare Tranquillitatis (LOLA)"
            : site.id.includes("dune")
              ? "Mars Dune " + site.id.replace(/^mars-dune-(barchan_crescent_dune-|linear-)?/, "")
              : humanizeGroup(site.name.replaceAll(" ", "_")) + " · " + (site.id.split("-").at(-1) ?? "01");
      list.push({
        id: site.id,
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

    if (searchResponse?.results.length) {
      // Group or present top ranked Pilot-100 Earth observations
      return searchResponse.results.slice(0, 15).map((sr) => {
        const pilot = regionById.get(sr.observation_id) ?? null;
        return {
          id: sr.observation_id,
          name: sr.location.geographic_group,
          regionLabel: humanizeGroup(sr.location.geographic_group) + " · " + (sr.observation_id.split("-").at(-1) ?? ""),
          latitude_deg: sr.location.latitude_deg,
          longitude_east_deg: sr.location.longitude_east_deg,
          rank: sr.rank,
          scorecardCandidate: null,
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
  }, [earthCandidates]);

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
    setSelectedTargetId(target.id);
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
    for (const e of earthCatalogue) {
      list.push({
        id: e.id,
        label: e.name,
        lat: e.latitude_deg,
        lon: e.longitude_east_deg,
        kind: "catalogue",
      });
    }
    return list;
  }, [earthCandidates, earthCatalogue, selectedEarthId]);

  const activeEquipment = getEquipmentProfile(equipmentId);
  const activeEquipmentName =
    body === "moon" && activeEquipment.moonName
      ? activeEquipment.moonName
      : activeEquipment.name;
  const activeEquipmentSummary =
    body === "moon" && activeEquipment.moonSummary
      ? activeEquipment.moonSummary
      : activeEquipment.summary;

  const jumpToIngested = () => {
    const firstIngested =
      targets.find((t) => t.tier === "scorecard_imagery") ??
      targets.find((t) => t.tier === "scorecard_only");
    if (firstIngested) handleSelectTarget(firstIngested);
  };

  return (
    <div className="min-h-dvh lg:h-dvh flex flex-col bg-[var(--bg-void)] text-[var(--text-primary)] lg:overflow-hidden">
      {/* Top Navigation & Equipment Bar */}
      <header className="sticky top-0 z-30 border-b border-[var(--border-subtle)] bg-[#080b10]/90 backdrop-blur-md pt-[env(safe-area-inset-top)]">
        <div className="px-3 sm:px-5 h-14 flex items-center justify-between gap-3">
          {/* Brand */}
          <div className="flex items-center gap-2.5 shrink-0">
            <div className="w-7 h-7 rounded-lg border border-white/15 bg-[#111824] flex items-center justify-center">
              <PlanetBadgeDot body={body} />
            </div>
            <div className="leading-tight">
              <div className="font-display text-sm font-semibold tracking-[-0.02em] text-slate-50">ENOM</div>
              <div className="text-[10px] text-slate-400 hidden sm:block">Planetary Analogue Observatory</div>
            </div>
          </div>

          {/* Body Switcher: Mars / Moon */}
          <div
            role="tablist"
            aria-label="Target planetary body"
            className="relative inline-flex items-center p-1 rounded-xl border border-[var(--border-subtle)] bg-[#0e141d] shrink-0"
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
                    (active ? "text-slate-50" : "text-slate-400 hover:text-slate-200")
                  }
                >
                  {active && (
                    <motion.span
                      layoutId="active-body-pill"
                      transition={{ type: "spring", bounce: 0.15, duration: 0.35 }}
                      className="absolute inset-0 rounded-lg bg-[#192231] border border-[var(--border-strong)] -z-10"
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
              <Popover.Trigger className="pressable inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[#0f141c] hover-surface px-2.5 py-1.5 text-xs text-slate-200">
                <Info className="w-3.5 h-3.5 text-sky-400" />
                <span className="hidden sm:inline">Mission factors</span>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Positioner sideOffset={8} align="end" className="z-50">
                  <Popover.Popup className="popover-popup w-80 sm:w-96 rounded-xl border border-[var(--border-strong)] bg-[#0f1520] p-4 shadow-2xl text-xs text-slate-200 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <EquipmentIcon id={equipmentId} className="w-4 h-4 text-sky-400" />
                      <div>
                        <div className="font-display text-sm font-semibold text-slate-100">{activeEquipmentName}</div>
                        <div className="text-[11px] text-slate-400">{activeEquipmentSummary}</div>
                      </div>
                    </div>
                    <div className="border-t border-[var(--border-subtle)] pt-2 space-y-1">
                      <div className="text-[10px] font-mono-tabular uppercase tracking-[0.06em] text-slate-400">Relevant terrain & environmental factors</div>
                      {activeEquipment.keyFactors.map((f) => (
                        <div key={f} className="text-[11px] text-slate-300">• {f}</div>
                      ))}
                    </div>
                    <div className="border-t border-[var(--border-subtle)] pt-2 space-y-1">
                      <div className="text-[10px] font-mono-tabular uppercase tracking-[0.06em] text-amber-300/90">Unscored gaps</div>
                      {activeEquipment.unscoredGaps.map((g) => (
                        <div key={g} className="text-[11px] text-slate-400">• {g}</div>
                      ))}
                    </div>
                  </Popover.Popup>
                </Popover.Positioner>
              </Popover.Portal>
            </Popover.Root>

            <button
              type="button"
              onClick={() => setDatasetsOpen(true)}
              className="pressable inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[#0f141c] hover-surface px-2.5 py-1.5 text-xs text-slate-200"
            >
              <Database className="w-3.5 h-3.5 text-slate-400" />
              <span className="hidden md:inline">Datasets</span>
              <span className="font-mono-tabular text-[10px] text-slate-400">{datasets.length}</span>
            </button>
          </div>
        </div>

        {/* Compact Equipment Selector Strip */}
        <div className="border-t border-[var(--border-subtle)] bg-[#0a0e14]/80 px-3 sm:px-5 py-1.5 overflow-x-auto scroll-contain">
          <div className="flex items-center gap-1.5 min-w-max">
            <span className="text-[10px] font-mono-tabular uppercase tracking-[0.08em] text-slate-500 mr-1 hidden sm:inline">
              Equipment
            </span>
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
                    "pressable inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium " +
                    (active
                      ? "border-[var(--border-strong)] bg-[#172130] text-slate-50"
                      : "border-transparent bg-transparent text-slate-400 hover-surface")
                  }
                >
                  <EquipmentIcon id={item.id} className="w-3.5 h-3.5 shrink-0" />
                  <span>{label}</span>
                </button>
              );
            })}
            <span className="hidden xl:inline-block ml-auto text-[11px] text-slate-400 truncate max-w-md pl-4">
              {activeEquipmentSummary}
            </span>
          </div>
        </div>
      </header>

      {bootError && (
        <div className="mx-4 mt-3 rounded-xl border border-rose-500/35 bg-rose-500/10 px-4 py-2.5 text-xs text-rose-200">
          Backend API unavailable ({bootError}). Start FastAPI via <code className="font-mono-tabular">uvicorn twinworld.api:app</code>.
        </div>
      )}

      {/* Main Three-Area Workspace */}
      <main className="flex-1 min-h-0 p-3 sm:p-4 flex flex-col lg:grid lg:grid-cols-[284px_minmax(0,1fr)_308px] xl:grid-cols-[300px_minmax(0,1fr)_324px] gap-3.5">
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
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0c1118]/90 px-3.5 py-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0 text-xs">
              <PlanetBadgeDot body={body} />
              <span className="font-medium text-slate-100 truncate">
                {selectedTarget?.name ?? "Select target"}
              </span>
              <ArrowLeftRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
              <PlanetBadgeDot body="earth" />
              <span className="font-medium text-sky-300 truncate">
                {selectedEarthCandidate?.regionLabel ?? "No Earth match"}
              </span>
              {selectedEarthCandidate?.scorecardCandidate?.similarity_score != null && (
                <span className="hidden sm:inline-flex items-center rounded bg-sky-500/12 border border-sky-500/25 px-1.5 py-0.5 font-mono-tabular text-[10px] text-sky-300">
                  Terrain {selectedEarthCandidate.scorecardCandidate.similarity_score.toFixed(3)}
                </span>
              )}
              {selectedEarthCandidate?.searchResult && (
                <span className="hidden md:inline-flex items-center gap-1 rounded bg-white/6 border border-white/10 px-1.5 py-0.5 font-mono-tabular text-[10px] text-slate-300">
                  <Sparkles className="w-2.5 h-2.5 text-amber-300" />
                  DINOv2 {selectedEarthCandidate.searchResult.cosine_similarity.toFixed(3)}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {/* Mobile globe view selector */}
              <div className="inline-flex lg:hidden rounded-lg border border-[var(--border-subtle)] bg-[#080b10] p-0.5 text-[11px]">
                {(["dual", "target", "earth"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMobileGlobeMode(m)}
                    className={"px-2 py-0.5 rounded-md capitalize " + (mobileGlobeMode === m ? "bg-[#192231] text-slate-100" : "text-slate-400")}
                  >
                    {m === "target" ? (body === "mars" ? "Mars" : "Moon") : m}
                  </button>
                ))}
              </div>
              {selectedTarget && selectedEarthCandidate && (
                <button
                  type="button"
                  onClick={() => {
                    void loadComparisonFor(selectedTarget, selectedEarthCandidate);
                    setComparisonOpen(true);
                  }}
                  className="pressable inline-flex items-center gap-1 rounded-lg bg-sky-500/16 hover:bg-sky-500/26 border border-sky-400/35 px-2.5 py-1 text-[11px] font-medium text-sky-200"
                >
                  Open scorecard
                  <ArrowUpRight className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

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
                    ? "NASA Viking / MOLA global mosaic · 0–360°E"
                    : "NASA LRO WAC / Clementine mosaic"
                }
                markers={leftMarkers}
                selectedId={selectedTargetId}
                focusCoords={leftFocus}
                defaultCoords={body === "mars" ? { lat: 8, lon: 135 } : { lat: 8, lon: 30 }}
                onSelectMarker={(id) => {
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
                subtitle="NASA Blue Marble · Ranked analogue candidates"
                markers={rightMarkers}
                selectedId={selectedEarthId}
                focusCoords={rightFocus}
                defaultCoords={{ lat: -22, lon: 22 }}
                onSelectMarker={(id) => {
                  const cand = earthCandidates.find((c) => c.id === id);
                  if (cand) {
                    handleSelectEarthCandidate(cand, true);
                    return;
                  }
                  const cat = earthCatalogue.find((e) => e.id === id);
                  if (cat) handleSelectCatalogueEarth(cat);
                }}
                className="min-h-[300px] lg:min-h-0"
              />
            )}
          </div>

          {/* Planet-to-Planet Baseline Strip */}
          <PlanetBaselineBar body={body} />
        </section>

        {/* Right Rail (Desktop) */}
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
          onJumpToIngested={jumpToIngested}
          className="hidden lg:flex lg:min-h-0"
        />

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
              Earth Analogues ({earthCandidates.length})
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
              onJumpToIngested={jumpToIngested}
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
    </div>
  );
}

export { formatCoords };
