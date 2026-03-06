#!/usr/bin/env python3
"""Generate synthetic GeoJSON grid + metrics for ampliseq geospatial dashboard.

Creates 100m x 100m grid cells within a 5km radius of 6 German sampling cities,
with spatially coherent land cover and anthropogenic impact index values.

Outputs:
  - anthropogenic_impact.geojson  (~9 MB, ~47K features)
  - anthropogenic_metrics.tsv     (~47K rows)

Both are written to the ampliseq project data directory.
"""

import csv
import json
import math
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# City coordinates (from merged_metadata.tsv)
# ---------------------------------------------------------------------------
CITIES = {
    "Frankfurt": (50.126437, 8.676333),
    "Hamburg": (53.571516, 10.001842),
    "Munich": (48.115651, 11.608537),
    "Berlin": (52.535668, 13.417164),
    "Cologne": (50.917687, 6.957023),
    "Cuxhaven": (53.878632, 8.719366),
}

# Radius in meters
GRID_RADIUS_M = 5000
CELL_SIZE_M = 100

# Approximate conversions at ~51°N latitude
LAT_DEG_PER_M = 1.0 / 111_320
LON_DEG_PER_M = 1.0 / (111_320 * math.cos(math.radians(51.0)))

# Coastal / river cities get water cells near certain angles
WATER_CITIES = {"Hamburg", "Cuxhaven"}

# Land cover categories
LAND_COVERS = ["Built-up", "Grassland", "Tree Cover", "Water"]

# Output directory — navigate from dev/geomap-features/ up to repo root, then into depictio/projects/...
OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "depictio"
    / "projects"
    / "test"
    / "geospatial_demo"
)


def _make_cell_polygon(center_lat: float, center_lon: float) -> list[list[float]]:
    """Create a GeoJSON polygon ring for a 100m cell centered at (lat, lon)."""
    half_lat = (CELL_SIZE_M / 2) * LAT_DEG_PER_M
    half_lon = (CELL_SIZE_M / 2) * LON_DEG_PER_M
    # GeoJSON coordinates are [lon, lat]
    sw = [round(center_lon - half_lon, 6), round(center_lat - half_lat, 6)]
    se = [round(center_lon + half_lon, 6), round(center_lat - half_lat, 6)]
    ne = [round(center_lon + half_lon, 6), round(center_lat + half_lat, 6)]
    nw = [round(center_lon - half_lon, 6), round(center_lat + half_lat, 6)]
    return [sw, se, ne, nw, sw]  # closed ring


def _assign_land_cover_and_impact(dist_m: float, angle_deg: float, city: str) -> tuple[str, float]:
    """Assign land cover type and impact index based on distance from city center.

    Spatially coherent pattern:
      - Inner ring (0-1500m): Built-up, high impact (0.7-1.0)
      - Mid ring (1500-3000m): Grassland, moderate impact (0.3-0.6)
      - Outer ring (3000-5000m): Tree Cover, low impact (0.0-0.3)
      - Water cities: certain angular sectors become Water with variable impact
    """
    rng = random.Random(f"{city}-{dist_m:.0f}-{angle_deg:.0f}")

    # Water sectors for coastal/river cities
    if city in WATER_CITIES:
        # Hamburg: Elbe roughly N-NE; Cuxhaven: North Sea roughly N-NW
        water_sector = (330, 60) if city == "Hamburg" else (300, 30)
        lo, hi = water_sector
        if lo > hi:
            in_water = angle_deg >= lo or angle_deg <= hi
        else:
            in_water = lo <= angle_deg <= hi
        if in_water and dist_m > 800:
            impact = round(rng.uniform(0.1, 0.5), 3)
            return "Water", impact

    # Distance-based rings with some noise
    noise = rng.gauss(0, 200)
    effective_dist = dist_m + noise

    if effective_dist < 1500:
        impact = round(rng.uniform(0.7, 1.0), 3)
        return "Built-up", impact
    elif effective_dist < 3000:
        impact = round(rng.uniform(0.3, 0.6), 3)
        # Occasional parks in mid ring
        if rng.random() < 0.15:
            impact = round(rng.uniform(0.1, 0.3), 3)
            return "Tree Cover", impact
        return "Grassland", impact
    else:
        impact = round(rng.uniform(0.0, 0.3), 3)
        # Occasional built-up in outer ring (suburbs)
        if rng.random() < 0.1:
            impact = round(rng.uniform(0.4, 0.7), 3)
            return "Built-up", impact
        return "Tree Cover", impact


def generate() -> None:
    """Generate GeoJSON and metrics TSV files."""
    features = []
    metrics_rows = []
    cell_counter = 0

    steps = int(GRID_RADIUS_M / CELL_SIZE_M)  # number of steps in each direction

    for city, (clat, clon) in CITIES.items():
        print(f"Generating grid for {city} ({clat}, {clon})...")
        city_cells = 0

        for row in range(-steps, steps + 1):
            for col in range(-steps, steps + 1):
                # Cell center offset in meters
                dy = row * CELL_SIZE_M
                dx = col * CELL_SIZE_M
                dist = math.sqrt(dx * dx + dy * dy)

                if dist > GRID_RADIUS_M:
                    continue

                angle = math.degrees(math.atan2(dx, dy)) % 360

                # Cell center in degrees
                lat = clat + dy * LAT_DEG_PER_M
                lon = clon + dx * LON_DEG_PER_M

                cell_id = f"{city}_{cell_counter:06d}"
                cell_counter += 1
                city_cells += 1

                land_cover, impact_index = _assign_land_cover_and_impact(dist, angle, city)

                # GeoJSON feature (geometry only, cell_id in properties)
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"cell_id": cell_id},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [_make_cell_polygon(lat, lon)],
                        },
                    }
                )

                # Metrics row
                metrics_rows.append(
                    {
                        "cell_id": cell_id,
                        "city": city,
                        "land_cover": land_cover,
                        "impact_index": impact_index,
                    }
                )

        print(f"  {city}: {city_cells} cells")

    # Write GeoJSON
    geojson = {"type": "FeatureCollection", "features": features}
    geojson_path = OUTPUT_DIR / "anthropogenic_impact.geojson"
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, separators=(",", ":"))
    size_mb = geojson_path.stat().st_size / 1_000_000
    print(f"\nWrote {geojson_path.name}: {len(features)} features, {size_mb:.1f} MB")

    # Write metrics TSV
    tsv_path = OUTPUT_DIR / "anthropogenic_metrics.tsv"
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["cell_id", "city", "land_cover", "impact_index"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(metrics_rows)
    print(f"Wrote {tsv_path.name}: {len(metrics_rows)} rows")


if __name__ == "__main__":
    generate()
