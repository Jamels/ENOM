import type { AnyBody, EquipmentId, PlanetaryBody } from "../types";

export type MissionObjectiveId = "landing" | "base_construction" | "rover_mobility";

export type EquipmentProfile = {
  id: EquipmentId;
  name: string;
  moonName?: string;
  summary: string;
  moonSummary?: string;
  missionObjective: MissionObjectiveId;
  objectiveNote: string;
  defaultWeights: Record<string, number>;
  keyFactors: string[];
  unscoredGaps: string[];
  earthAnalogueLimits: {
    mars: string;
    moon: string;
  };
};

export const EQUIPMENT_PROFILES: EquipmentProfile[] = [
  {
    id: "rover",
    name: "Rovers",
    summary: "Surface mobility, slope traversal and dune navigation",
    missionObjective: "rover_mobility",
    objectiveNote: "Uses backend rover-mobility screening and slope-weighted terrain scoring.",
    defaultWeights: {
      elevation_range: 0.2,
      mean_slope: 0.16,
      slope_p90: 0.32,
      median_local_relief_3x3: 0.2,
      median_roughness_3x3: 0.12,
    },
    keyFactors: [
      "90th percentile slope (926 m scale)",
      "Local 3x3 relief and surface roughness",
      "Bedform, crater-rim and layered sedimentary morphology",
    ],
    unscoredGaps: [
      "Wheel-soil terramechanics, bearing strength and fine dust cohesion",
      "Sub-meter boulder hazards below 30-463 m DEM posting",
    ],
    earthAnalogueLimits: {
      mars: "Earth gravity and soil moisture differ from Mars, affecting traction and sinkage.",
      moon: "Lunar vacuum, gravity and abrasive regolith differ from terrestrial sand.",
    },
  },
  {
    id: "lander",
    name: "Landers",
    summary: "Touchdown hazard screening, slope limits and flat plains",
    missionObjective: "landing",
    objectiveNote: "Uses backend landing-site screening (VIPER draft slope context) and slope-prioritized weights.",
    defaultWeights: {
      elevation_range: 0.2,
      mean_slope: 0.28,
      slope_p90: 0.24,
      median_local_relief_3x3: 0.16,
      median_roughness_3x3: 0.12,
    },
    keyFactors: [
      "Mean slope and 90th percentile slope",
      "Footprint elevation range over 10.2 km",
      "Smooth volcanic mare and flat basin topography",
    ],
    unscoredGaps: [
      "Meter-scale landing-foot hazards and plume-ejecta scouring",
      "Descent radar/lidar dust obscuration",
    ],
    earthAnalogueLimits: {
      mars: "Mars’s thin atmosphere changes parachute and powered-descent behavior.",
      moon: "The Moon has no atmosphere; descent and ejecta behavior differ from Earth.",
    },
  },
  {
    id: "habitat",
    name: "Habitats & caves",
    summary: "Base construction, level pads and lava-tube sheltering",
    missionObjective: "base_construction",
    objectiveNote: "Uses backend base-construction screening (<5 deg notional pad context) and relief/roughness weights.",
    defaultWeights: {
      elevation_range: 0.2,
      mean_slope: 0.16,
      slope_p90: 0.12,
      median_local_relief_3x3: 0.28,
      median_roughness_3x3: 0.24,
    },
    keyFactors: [
      "Median 3x3 local relief and roughness for foundation grading",
      "Low mean slope for pad and module siting",
      "Volcanic skylights, collapsed lava tubes and polar crater rims",
    ],
    unscoredGaps: [
      "Subsurface cave geometry, roof thickness and structural stability",
      "Ionizing radiation flux and solar illumination duty cycles",
    ],
    earthAnalogueLimits: {
      mars: "Mars gravity, humidity and biology differ from Earth cave conditions.",
      moon: "Lunar caves face vacuum, radiation and long thermal cycles absent on Earth.",
    },
  },
  {
    id: "drill",
    name: "Drills & ice",
    summary: "Subsurface sampling, permafrost and volatile access",
    missionObjective: "base_construction",
    objectiveNote: "Applies base-construction stability checks with custom drill-rig slope/relief weights.",
    defaultWeights: {
      elevation_range: 0.25,
      mean_slope: 0.25,
      slope_p90: 0.15,
      median_local_relief_3x3: 0.2,
      median_roughness_3x3: 0.15,
    },
    keyFactors: [
      "Moderate slope and stable local relief for drilling platform setup",
      "Diviner nighttime regolith temperature context (Moon)",
      "Polar cold traps and layered sedimentary stratigraphy",
    ],
    unscoredGaps: [
      "Subsurface water-ice concentration, depth and hardness",
      "Volatile sublimation physics in vacuum or near-vacuum",
    ],
    earthAnalogueLimits: {
      mars: "Low pressure and temperature change how Martian ground ice behaves.",
      moon: "Lunar polar volatiles occur in vacuum; Earth permafrost is sampled in an atmosphere.",
    },
  },
  {
    id: "drone",
    name: "Aerial drones",
    moonName: "Hoppers",
    summary: "Rotorcraft scouting across steep canyons and rims",
    moonSummary: "Propulsive hopper scouting into shadowed craters",
    missionObjective: "landing",
    objectiveNote: "Applies landing touchdown screening with custom relief-emphasized weights for scouting.",
    defaultWeights: {
      elevation_range: 0.3,
      mean_slope: 0.15,
      slope_p90: 0.2,
      median_local_relief_3x3: 0.25,
      median_roughness_3x3: 0.1,
    },
    keyFactors: [
      "10 km regional elevation range (canyon walls, crater rims)",
      "Local relief transitions between highlands and floor",
      "Safe flat touchdown zones near steep science targets",
    ],
    unscoredGaps: [
      "Atmospheric density for rotor aerodynamics or thruster propellant budgets",
      "Terrain-relative navigation texture contrast and GPS-denied localization",
    ],
    earthAnalogueLimits: {
      mars: "Mars’s thin atmosphere limits rotorcraft flight; the Moon has no aerodynamic lift.",
      moon: "The Moon has no atmosphere for flight; scouting requires a hopper, not a drone.",
    },
  },
  {
    id: "suit",
    name: "Spacesuits & EVA",
    summary: "Crewed field geology, traverse ergonomics and dust control",
    missionObjective: "rover_mobility",
    objectiveNote: "Applies mobility slope checks with custom roughness and slope weights for traverse safety.",
    defaultWeights: {
      elevation_range: 0.15,
      mean_slope: 0.25,
      slope_p90: 0.25,
      median_local_relief_3x3: 0.15,
      median_roughness_3x3: 0.2,
    },
    keyFactors: [
      "Surface roughness and slope percentiles affecting astronaut footing",
      "USGS regional geologic map units and volcanic/impact diversity",
      "Surface thermal regime (Diviner / TES context)",
    ],
    unscoredGaps: [
      "Suit joint stiffness under pressurized operation in 17% or 38% gravity",
      "Abrasive regolith dust adhesion on visors, seals and bearings",
    ],
    earthAnalogueLimits: {
      mars: "Earth gravity, air and temperature differ from Mars suit and dust conditions.",
      moon: "Lunar EVA involves low gravity, vacuum, abrasive dust and extreme temperatures.",
    },
  },
];

export type PlanetaryBaselineRow = {
  label: string;
  earth: string;
  mars: string;
  moon: string;
};

export const PLANETARY_BASELINE: PlanetaryBaselineRow[] = [
  { label: "Surface gravity", earth: "9.81 m/s²", mars: "3.71 m/s² (38%)", moon: "1.62 m/s² (17%)" },
  { label: "Solar day", earth: "24 h", mars: "24 h 37 min", moon: "29.5 Earth days" },
  { label: "Surface temp", earth: "15 °C avg", mars: "−63 °C avg", moon: "−173 to +127 °C" },
  { label: "Surface pressure", earth: "1,013 hPa", mars: "≈ 6 hPa (<1%)", moon: "Near vacuum" },
  { label: "Atmosphere", earth: "78% N₂, 21% O₂", mars: "95% CO₂ (thin)", moon: "Trace exosphere" },
  { label: "Mean diameter", earth: "12,742 km", mars: "6,779 km", moon: "3,474 km" },
];

export function getEquipmentProfile(id: EquipmentId): EquipmentProfile {
  return EQUIPMENT_PROFILES.find((item) => item.id === id) ?? EQUIPMENT_PROFILES[0];
}

export function formatLatitude(lat: number): string {
  return Math.abs(lat).toFixed(2) + "°" + (lat >= 0 ? "N" : "S");
}

export function formatLongitude(longitude: number, body: AnyBody | string): string {
  const east = ((longitude % 360) + 360) % 360;
  if (body === "mars") {
    return east.toFixed(2) + "°E";
  }
  const signed = east > 180 ? east - 360 : east;
  return Math.abs(signed).toFixed(2) + "°" + (signed < 0 ? "W" : "E");
}

export function formatCoords(lat: number, lon: number, body: AnyBody | string): string {
  return formatLatitude(lat) + ", " + formatLongitude(lon, body);
}

const PRETTY_GROUP_NAMES: Record<string, string> = {
  earth_badain_otherdune: "Badain Jaran Dunes",
  earth_capitolreef_layered: "Capitol Reef Layered Rock",
  earth_grandcanyon_layered: "Grand Canyon Layered Rock",
  earth_namib_barchan: "Namib Barchan Dunes",
  earth_reykjanes_nondune: "Reykjanes Volcanic Plains",
  earth_rubalkhali_linear: "Rub' al Khali Linear Dunes",
  earth_simpson_linear: "Simpson Desert Linear Dunes",
  earth_taklamakan_barchan: "Taklamakan Barchan Dunes",
  earth_uyuni_nondune: "Salar de Uyuni",
  earth_whitesands_otherdune: "White Sands Dune Field",
  mars_aeolis_nondune: "Aeolis Region",
  mars_eberswalde_layered: "Eberswalde Layered Delta",
  mars_elysium_nondune: "Elysium Planitia",
  mars_hecates_nondune: "Hecates Tholus Region",
  mars_mawrth_layered: "Mawrth Vallis Layered",
  mars_medusae_nondune: "Medusae Fossae",
  mars_memnonia_nondune: "Memnonia Region",
  mars_valles_layered: "Valles Marineris Layered",
};

export function humanizeGroup(raw: string): string {
  if (PRETTY_GROUP_NAMES[raw]) return PRETTY_GROUP_NAMES[raw];
  return raw
    .replace(/^(earth|mars|moon)[_-]/i, "")
    .replace(/^dune[_-]/i, "Dune ")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function inferEquipmentTagsForTarget(
  id: string,
  name: string,
  body: PlanetaryBody,
  candidateType?: string,
): EquipmentId[] {
  const key = (id + " " + name + " " + (candidateType ?? "")).toLowerCase();
  const tags = new Set<EquipmentId>();
  if (key.includes("pit") || key.includes("hole") || key.includes("tube") || key.includes("cave")) {
    tags.add("habitat");
    tags.add("suit");
    tags.add("drone");
  }
  if (key.includes("polar") || key.includes("shackleton") || key.includes("malapert") || key.includes("gerlache")) {
    tags.add("drill");
    tags.add("habitat");
    tags.add("rover");
    tags.add("drone");
  }
  if (key.includes("tranquillitatis") || key.includes("viking") || key.includes("nondune") || key.includes("elysium")) {
    tags.add("lander");
    tags.add("rover");
    tags.add("suit");
  }
  if (key.includes("dune") || key.includes("jezero") || key.includes("gale") || key.includes("layered") || key.includes("mawrth") || key.includes("eberswalde")) {
    tags.add("rover");
    tags.add("drill");
    tags.add("suit");
  }
  if (key.includes("valles") || key.includes("canyon")) {
    tags.add("drone");
    tags.add("rover");
  }
  if (tags.size === 0) {
    tags.add("rover");
    tags.add("lander");
    if (body === "mars") tags.add("drone");
  }
  return Array.from(tags);
}

export function inferEquipmentTagsForEarth(id: string, name: string, candidateType?: string): EquipmentId[] {
  const key = (id + " " + name + " " + (candidateType ?? "")).toLowerCase();
  const tags = new Set<EquipmentId>();
  if (key.includes("cave") || key.includes("tube") || key.includes("lava_beds")) {
    tags.add("habitat");
    tags.add("suit");
    tags.add("drone");
  }
  if (key.includes("mcmurdo") || key.includes("haughton") || key.includes("polar") || key.includes("arctic")) {
    tags.add("drill");
    tags.add("habitat");
    tags.add("suit");
  }
  if (key.includes("uyuni") || key.includes("simpson") || key.includes("whitesands") || key.includes("namib")) {
    tags.add("lander");
    tags.add("rover");
  }
  if (key.includes("grandcanyon") || key.includes("capitolreef")) {
    tags.add("drone");
    tags.add("drill");
    tags.add("suit");
  }
  if (key.includes("reykjanes") || key.includes("holuhraun")) {
    tags.add("suit");
    tags.add("rover");
    tags.add("habitat");
    tags.add("lander");
  }
  if (key.includes("dune") || key.includes("barchan") || key.includes("linear") || key.includes("atacama")) {
    tags.add("rover");
    tags.add("drill");
  }
  if (tags.size === 0) {
    tags.add("rover");
    tags.add("lander");
  }
  return Array.from(tags);
}
