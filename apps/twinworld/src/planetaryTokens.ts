import type { CSSProperties } from "react";
import type { AnyBody } from "./types";

export const PLANETARY_PALETTES = {
  moon: { light: "#E4E9F2", primary: "#CFD6E6", deep: "#9FA8BB" },
  mars: { light: "#DD8B63", primary: "#C97852", deep: "#9F5637" },
  earth: { light: "#7AC6F0", primary: "#56B4E9", deep: "#2C85B8" },
} as const satisfies Record<AnyBody, Record<"light" | "primary" | "deep", string>>;

export type PlanetaryPalette = (typeof PLANETARY_PALETTES)[AnyBody];
export type PlanetaryShade = keyof PlanetaryPalette;

export function planetaryColor(body: AnyBody, shade: PlanetaryShade = "primary"): string {
  return PLANETARY_PALETTES[body][shade];
}

export function planetarySourceStyle(body: AnyBody): CSSProperties {
  return {
    "--planetary-color": planetaryColor(body),
    "--planetary-light": planetaryColor(body, "light"),
    "--planetary-deep": planetaryColor(body, "deep"),
  } as CSSProperties;
}

export function installPlanetaryTokens(): void {
  if (typeof document === "undefined") return;
  for (const [body, shades] of Object.entries(PLANETARY_PALETTES)) {
    for (const [shade, color] of Object.entries(shades)) {
      document.documentElement.style.setProperty(`--planet-${body}-${shade}`, color);
    }
  }
}
