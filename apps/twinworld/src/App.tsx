import { useCallback, useEffect, useMemo, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { motion } from "motion/react";
import { ArrowLeftRight, ArrowUpRight, Database, HardDrive, Info } from "lucide-react";
import enomLogo from "../../../ENOM.png";
import { api, type AnalogueDiscovery, type AnalogueProfile } from "./lib/api";
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
import { TargetSidebar } from "./components/TargetSidebar";
import { EarthAnalogueSidebar } from "./components/EarthAnalogueSidebar";
import { PlanetBaselineBar } from "./components/PlanetBaselineBar";
import { ComparisonModal } from "./components/ComparisonModal";
import { DatasetsDialog } from "./components/DatasetsDialog";
import { OfflineMapsDialog } from "./components/OfflineMapsDialog";

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
  const [analogueDiscovery, setAnalogueDiscovery] = useState<AnalogueDiscovery | null>(null);
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

  useEffect(() => {
    if (!selectedTargetId || !discoveryProfiles.length || !Object.keys(discoveryWeights).length) {
      setAnalogueDiscovery(null);
      setDiscoveryBusy(false);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setDiscoveryBusy(true);
      setDiscoveryError("");
      api.discoverAnalogues({ target_site_id: selectedTargetId, profile_id: discoveryProfileId, weights: discoveryWeights, limit: 10 })
        .then((result) => { if (!cancelled) setAnalogueDiscovery(result); })
        .catch((err) => {
          if (!cancelled) {
            setAnalogueDiscovery(null);
            setDiscoveryError(err instanceof Error ? err.message : "Analogue ranking failed");
          }
        })
        .finally(() => { if (!cancelled) setDiscoveryBusy(false); });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [selectedTargetId, body, discoveryProfiles, discoveryProfileId, discoveryWeights]);

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
      const isCataloguePlace = catalogueEntries.some((entry) => entry.id === site.id);
      // Keep the scored observations in the API, but keep default place browsing to
      // reviewed imagery or explicit candidate catalogue entries.
      if (!isCataloguePlace && (!matchedRegion || matchedRegion.label_status !== "verified")) continue;
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
        // Keep source records in the catalogue, but do not expose unreviewed pilot patches
        // as default place targets. Reviewed observations can be restored by updating status.
        if (r.body !== "mars" || r.label_status !== "verified" || seenIds.has(r.id)) continue;
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

  const handleSelectDiscoveredPlace = (place: AnalogueDiscovery["results"][number]["place"]) => {
    setSelectedEarthId(place.id);
    setRightFocus({ lat: place.latitude_deg, lon: place.longitude_east_deg, token: Date.now() });
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
    for (const row of analogueDiscovery?.results ?? []) {
      const place = row.place;
      discoveredIds.add(place.id);
      const key = place.latitude_deg.toFixed(1) + "," + place.longitude_east_deg.toFixed(1);
      if (place.id !== selectedEarthId && seenGroup.has(key)) continue;
      seenGroup.add(key);
      list.push({
        id: place.id,
        label: place.name,
        lat: place.latitude_deg,
        lon: place.longitude_east_deg,
        kind: "ranked",
        rank: row.rank ?? undefined,
        score: row.score,
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
          Backend API unavailable ({bootError}). Start FastAPI via <code className="font-mono-tabular">uvicorn twinworld.api:app</code>.
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
                {selectedTarget?.name ?? "Select target"}
              </span>
              <ArrowLeftRight className="w-4 h-4 text-[var(--text-muted)] shrink-0" strokeWidth={1.5} />
              <PlanetBadgeDot body="earth" />
              <span className="font-medium truncate" style={{ color: planetaryColor("earth") }}>
                {selectedEarthCandidate?.regionLabel ?? "No Earth match"}
              </span>
              {selectedEarthCandidate?.scorecardCandidate?.similarity_score != null && (
                <span className="hidden sm:inline font-mono-tabular text-xs text-[var(--text-secondary)]">
                  · Terrain {selectedEarthCandidate.scorecardCandidate.similarity_score.toFixed(3)}
                </span>
              )}
              {selectedEarthCandidate?.searchResult && (
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
              {selectedTarget && selectedEarthCandidate && (
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
                subtitle="NASA GIBS · Blue Marble (Aug 2004) · cloud-free global · 500 m/px"
                markers={rightMarkers}
                selectedId={selectedEarthId}
                focusCoords={rightFocus}
                defaultCoords={{ lat: -22, lon: 22 }}
                onSelectMarker={(id) => {
                  const discovered = analogueDiscovery?.results.find((row) => row.place.id === id);
                  if (discovered) {
                    handleSelectDiscoveredPlace(discovered.place);
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
          discoveryProfiles={discoveryProfiles}
          discoveryProfileId={discoveryProfileId}
          discoveryWeights={discoveryWeights}
          discoveryResult={analogueDiscovery}
          discoveryBusy={discoveryBusy}
          discoveryError={discoveryError}
          onDiscoveryProfileChange={handleDiscoveryProfileChange}
          onDiscoveryWeightChange={(id, value) => setDiscoveryWeights((current) => ({ ...current, [id]: value }))}
          onResetDiscoveryWeights={() => {
            const profile = discoveryProfiles.find((item) => item.id === discoveryProfileId);
            if (profile) setDiscoveryWeights(profile.weights);
          }}
          onSelectDiscoveredPlace={handleSelectDiscoveredPlace}
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
              Earth Analogues ({analogueDiscovery?.results.length ?? earthCandidates.length})
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
              discoveryProfiles={discoveryProfiles}
              discoveryProfileId={discoveryProfileId}
              discoveryWeights={discoveryWeights}
              discoveryResult={analogueDiscovery}
              discoveryBusy={discoveryBusy}
              discoveryError={discoveryError}
              onDiscoveryProfileChange={handleDiscoveryProfileChange}
              onDiscoveryWeightChange={(id, value) => setDiscoveryWeights((current) => ({ ...current, [id]: value }))}
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
