#!/usr/bin/env python3
"""Generate GeoJSON from ESA WorldCover satellite imagery for ampliseq geospatial dashboard.

Downloads ESA WorldCover 10m GeoTIFF tiles, crops to 5km radius around each
sampling city, vectorizes land cover polygons, and generates simplified GeoJSON
with real coastlines and city boundaries.

Outputs:
  - anthropogenic_impact.geojson  (real satellite-derived land cover polygons)
  - anthropogenic_metrics.tsv     (metrics per polygon)

Requirements:
  - rasterio
  - shapely
  - numpy
  - requests (for downloading tiles)

Usage:
  python generate_real_landcover.py [--cell-size 500] [--skip-download]

After generating GeoJSON, convert to PMTiles:
  tippecanoe -o anthropogenic.pmtiles -l land_cover \
    --minimum-zoom=4 --maximum-zoom=14 \
    --drop-densest-as-needed --extend-zooms-if-still-dropping \
    anthropogenic_impact.geojson
"""

import argparse
import csv
import json
import sys
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

GRID_RADIUS_M = 5000

# ESA WorldCover 2021 land cover classes
# https://esa-worldcover.org/en/data-access
ESA_CLASSES = {
    10: "Tree Cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Water",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

# Impact index per land cover class
ESA_IMPACT = {
    10: 0.1,  # Tree Cover
    20: 0.15,  # Shrubland
    30: 0.3,  # Grassland
    40: 0.5,  # Cropland
    50: 0.9,  # Built-up
    60: 0.05,  # Bare
    70: 0.0,  # Snow
    80: 0.2,  # Water
    90: 0.15,  # Wetland
    95: 0.1,  # Mangroves
    100: 0.05,  # Moss
}

# ESA WorldCover tile naming: N{lat}E{lon} for 3x3 degree tiles
# Tiles needed for the 6 German cities:
ESA_TILES_NEEDED = [
    "N48E006",
    "N48E008",
    "N48E009",
    "N48E011",
    "N51E006",
    "N51E008",
    "N51E010",
    "N51E013",
    "N54E008",
    "N54E009",
    "N54E010",
]

ESA_BASE_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "depictio"
    / "projects"
    / "test"
    / "geospatial_demo"
)

CACHE_DIR = Path(__file__).resolve().parent / ".tile_cache"


def _get_tile_name_for_coords(lat: float, lon: float) -> str:
    """Compute the ESA WorldCover tile name for given coordinates."""
    tile_lat = int(lat // 3) * 3
    tile_lon = int(lon // 3) * 3
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"{ns}{abs(tile_lat):02d}{ew}{abs(tile_lon):03d}"


def _download_tile(tile_name: str) -> Path:
    """Download an ESA WorldCover tile if not already cached."""
    import requests

    cache_path = CACHE_DIR / f"ESA_WorldCover_10m_2021_v200_{tile_name}_Map.tif"
    if cache_path.exists():
        print(f"  Using cached tile: {tile_name}")
        return cache_path

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    url = f"{ESA_BASE_URL}/ESA_WorldCover_10m_2021_v200_{tile_name}_Map.tif"
    print(f"  Downloading tile: {tile_name} from {url}...")

    resp = requests.get(url, stream=True, timeout=120)
    if resp.status_code == 404:
        print(f"  WARNING: Tile {tile_name} not found (404). Skipping.")
        return None
    resp.raise_for_status()

    with open(cache_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

    size_mb = cache_path.stat().st_size / 1_000_000
    print(f"  Downloaded {tile_name}: {size_mb:.1f} MB")
    return cache_path


def _crop_and_vectorize(
    tile_path: Path,
    center_lat: float,
    center_lon: float,
    radius_m: int,
    simplify_tolerance: float = 0.001,
) -> list[dict]:
    """Crop raster to bounding box around center, vectorize into GeoJSON features.

    Args:
        tile_path: Path to GeoTIFF file.
        center_lat: Center latitude.
        center_lon: Center longitude.
        radius_m: Radius in meters for the bounding box.
        simplify_tolerance: Shapely simplification tolerance in degrees.

    Returns:
        List of GeoJSON feature dicts.
    """
    # Compute bounding box in degrees (approximate)
    import math

    import rasterio
    from rasterio.features import shapes
    from rasterio.mask import mask as rasterio_mask
    from shapely.geometry import box, mapping, shape

    lat_deg = radius_m / 111_320
    lon_deg = radius_m / (111_320 * math.cos(math.radians(center_lat)))

    bbox = box(
        center_lon - lon_deg,
        center_lat - lat_deg,
        center_lon + lon_deg,
        center_lat + lat_deg,
    )

    features = []

    with rasterio.open(tile_path) as src:
        # Crop to bounding box
        try:
            out_image, out_transform = rasterio_mask(src, [mapping(bbox)], crop=True, nodata=0)
        except ValueError:
            # Bounding box doesn't overlap with tile
            return []

        out_image = out_image[0]  # First band

        # Vectorize — groups adjacent pixels with same value into polygons
        for geom, value in shapes(out_image, transform=out_transform):
            value = int(value)
            if value == 0:
                continue  # Skip nodata
            if value not in ESA_CLASSES:
                continue

            # Convert to shapely, simplify to reduce vertex count
            poly = shape(geom)
            if poly.is_empty or not poly.is_valid:
                continue

            # Simplify geometry to reduce file size
            simplified = poly.simplify(simplify_tolerance, preserve_topology=True)
            if simplified.is_empty:
                continue

            # Filter out tiny polygons (< ~100m2 at equator)
            if simplified.area < 1e-7:
                continue

            land_cover = ESA_CLASSES[value]
            impact = ESA_IMPACT.get(value, 0.0)

            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "land_cover": land_cover,
                        "impact_index": impact,
                        "esa_class": value,
                    },
                    "geometry": mapping(simplified),
                }
            )

    return features


def generate(skip_download: bool = False, simplify_tolerance: float = 0.001) -> None:
    """Generate GeoJSON and metrics from real ESA WorldCover data."""
    all_features = []
    metrics_rows = []
    cell_counter = 0

    # Determine which tiles we need
    tiles_needed = set()
    for city, (clat, clon) in CITIES.items():
        tile_name = _get_tile_name_for_coords(clat, clon)
        tiles_needed.add(tile_name)

    print(f"Tiles needed: {sorted(tiles_needed)}")

    if skip_download:
        print("Skipping download (--skip-download), using cached tiles only")

    # Download tiles
    tile_paths: dict[str, Path | None] = {}
    for tile_name in sorted(tiles_needed):
        if skip_download:
            cache_path = CACHE_DIR / f"ESA_WorldCover_10m_2021_v200_{tile_name}_Map.tif"
            tile_paths[tile_name] = cache_path if cache_path.exists() else None
        else:
            tile_paths[tile_name] = _download_tile(tile_name)

    # Process each city
    for city, (clat, clon) in CITIES.items():
        tile_name = _get_tile_name_for_coords(clat, clon)
        tile_path = tile_paths.get(tile_name)

        if not tile_path or not tile_path.exists():
            print(f"Skipping {city}: tile {tile_name} not available")
            continue

        print(f"Processing {city} ({clat}, {clon}) from tile {tile_name}...")

        features = _crop_and_vectorize(
            tile_path,
            clat,
            clon,
            GRID_RADIUS_M,
            simplify_tolerance=simplify_tolerance,
        )

        # Add city and cell_id to each feature
        for feat in features:
            cell_id = f"{city}_{cell_counter:06d}"
            cell_counter += 1
            feat["properties"]["cell_id"] = cell_id
            feat["properties"]["city"] = city
            feat["id"] = cell_id

            metrics_rows.append(
                {
                    "cell_id": cell_id,
                    "city": city,
                    "land_cover": feat["properties"]["land_cover"],
                    "impact_index": feat["properties"]["impact_index"],
                }
            )

        all_features.extend(features)
        print(f"  {city}: {len(features)} polygons")

    if not all_features:
        print("ERROR: No features generated. Check tile downloads and paths.")
        sys.exit(1)

    # Write GeoJSON
    geojson = {"type": "FeatureCollection", "features": all_features}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    geojson_path = OUTPUT_DIR / "anthropogenic_impact.geojson"
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, separators=(",", ":"))
    size_mb = geojson_path.stat().st_size / 1_000_000
    print(f"\nWrote {geojson_path.name}: {len(all_features)} features, {size_mb:.1f} MB")

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

    # Print tippecanoe command for PMTiles conversion
    print("\nTo convert to PMTiles, run:")
    print(f"  tippecanoe -o {OUTPUT_DIR / 'anthropogenic.pmtiles'} \\")
    print("    -l land_cover \\")
    print("    --minimum-zoom=4 --maximum-zoom=14 \\")
    print("    --drop-densest-as-needed \\")
    print("    --extend-zooms-if-still-dropping \\")
    print(f"    {geojson_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate real land cover GeoJSON")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading tiles (use cached only)",
    )
    parser.add_argument(
        "--simplify",
        type=float,
        default=0.001,
        help="Simplification tolerance in degrees (default: 0.001 ~ 100m)",
    )
    args = parser.parse_args()
    generate(skip_download=args.skip_download, simplify_tolerance=args.simplify)
