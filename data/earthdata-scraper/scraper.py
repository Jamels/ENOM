import csv
import math

import earthaccess

earthaccess.login()

# Your coordinates: (lat, lon). Could come from a CSV: pd.read_csv("points.csv")[["lat","lon"]]
points = [
    (-21.17, 119.42),  # Dresser Formation, Pilbara, WA
    (-28.37, 137.37),  # Kati Thanda-Lake Eyre, SA
    (-32.60, 121.60),  # Lake Gilmore acid lakes, WA
    (-31.00, 129.00),  # Nullarbor Plain, SA/WA
    (-18.20, 144.60),  # Undara Lava Tubes, Qld
    (78.20, 15.80),  # Adventdalen, Svalbard (outside NASADEM coverage)
    (-24.25, 131.57),  # Kings Canyon (Watarrka), NT
    (-37.95, 143.20),  # Mt Elephant, Newer Volcanics, Vic
    (-19.17, 127.80),  # Wolfe Creek Crater, WA
    (-17.50, 129.00),  # Antrim Plateau basalts, NT/WA
    (-37.92, 141.95),  # Byaduk Caves, Budj Bim, Vic
    (-23.82, 132.31),  # Tnorala (Gosses Bluff), NT
    (-24.57, 133.15),  # Henbury Meteorites Reserve, NT
]


def tile_id(lat, lon):
    """NASADEM tile name from the SW corner, e.g. s25e015."""
    la, lo = math.floor(lat), math.floor(lon)
    return f"{'n' if la >= 0 else 's'}{abs(la):02d}{'e' if lo >= 0 else 'w'}{abs(lo):03d}"


def granule_name(g):
    umm = g["umm"]
    return (
        umm.get("DataGranule", {}).get("ProducerGranuleId")
        or umm.get("GranuleUR")
        or g["meta"].get("native-id")
    )


def find_granules(points, short_name="NASADEM_HGT", version="001", eps=1e-4):
    seen, rows = {}, []
    for lat, lon in points:
        results = earthaccess.search_data(
            short_name=short_name,
            version=version,
            bounding_box=(lon - eps, lat - eps, lon + eps, lat + eps),
        )
        if not results:
            print(f"no granule for ({lat}, {lon})")
            rows.append({"lat": lat, "lon": lon, "concept_id": None, "producer_granule_id": None})
            continue
        for g in results:
            cid = g["meta"]["concept-id"]
            seen.setdefault(cid, g)
            rows.append(
                {"lat": lat, "lon": lon, "concept_id": cid, "producer_granule_id": granule_name(g)}
            )
    return seen, rows


granules, point_to_granule = find_granules(points)
print(f"{len(points)} points -> {len(granules)} unique granules")
with open("point_granule_map.csv", "w", newline="") as csvfile:
    fieldnames = ["lat", "lon", "concept_id", "producer_granule_id"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(point_to_granule)

# Download only the unique granules
files = earthaccess.download(list(granules.values()), local_path="./nasadem")
