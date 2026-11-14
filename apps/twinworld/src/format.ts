export const formatLongitude = (longitude: number, planet: string) => {
  const east = ((longitude % 360) + 360) % 360;
  return planet === "mars"
    ? `${east.toFixed(3)}°E`
    : `${Math.abs(longitude).toFixed(3)}°${longitude < 0 ? "W" : "E"}`;
};
