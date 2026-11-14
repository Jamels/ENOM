import type { EquipmentId } from "../types";
import { planetaryColor } from "../planetaryTokens";

export function EquipmentIcon({
  id,
  className = "w-4 h-4",
}: {
  id: EquipmentId;
  className?: string;
}) {
  switch (id) {
    case "rover":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <rect x="4" y="9" width="14" height="5" rx="1.2" />
          <path d="M14 9V5.5h3.2M17.2 5.5l2 1.5" />
          <circle cx="6.5" cy="17.5" r="2" />
          <circle cx="12" cy="17.5" r="2" />
          <circle cx="17.5" cy="17.5" r="2" />
          <path d="M6.5 14v1.5M12 14v1.5M17.5 14v1.5" />
        </svg>
      );
    case "lander":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <path d="M8 7h8l2 6H6z" />
          <path d="M7 13l-3 6M17 13l3 6M12 13v6M2.5 19h3M18.5 19h3M10 4h4" />
        </svg>
      );
    case "habitat":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <path d="M3.5 18.5a8.5 8 0 0 1 17 0z" />
          <path d="M10 18.5v-4.2h4v4.2M2 18.5h20" />
        </svg>
      );
    case "drill":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <path d="M8.5 3.5h7v4h-7zM12 7.5v11.5M9.5 11l5 2M9.5 14.5l5 2M4 20h16" />
        </svg>
      );
    case "drone":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <path d="M4.5 6.5h15M12 6.5V10M7 4.5h10" />
          <rect x="8.5" y="10" width="7" height="4.5" rx="1" />
          <path d="M8.5 14.5l-2.5 4.5M15.5 14.5l2.5 4.5" />
        </svg>
      );
    case "suit":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
          <circle cx="12" cy="6.2" r="3.2" />
          <path d="M10.2 6.2h3.6" />
          <path d="M7.5 11.5h9l1 5.5h-2.8v4H9.3v-4H6.5z" />
        </svg>
      );
  }
}

export function PlanetBadgeDot({ body }: { body: "earth" | "mars" | "moon" }) {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full shrink-0 border"
      style={{ backgroundColor: planetaryColor(body), borderColor: planetaryColor(body, "deep") }}
      aria-hidden="true"
    />
  );
}
