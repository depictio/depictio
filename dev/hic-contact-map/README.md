# Hi-C Contact Map Viewer

Interactive Plotly/Dash prototype for visualizing Hi-C contact maps.
Designed for future integration into Depictio.

## Features

- **Synthetic demo data**: Generates realistic Hi-C contact maps with TADs, loops, and distance-dependent decay
- **Cool/mcool file support**: Reads nf-core/hic pipeline output files via h5py (no cooler dependency)
- **Interactive visualization**: Zoom, pan, region selection with Plotly
- **DMC 2.0+ UI**: Mantine-based controls matching Depictio conventions
- **Configurable**: Color scales, log transform, value capping, resolution switching

## Quick Start

```bash
# Synthetic demo (no data files needed)
python app.py

# With a cool/mcool file (e.g. nf-core/hic output)
python app.py --file /path/to/matrix.mcool

# Debug mode
python app.py --debug --port 8051
```

## Dependencies

```
dash>=2.0
dash-mantine-components>=0.14
plotly>=5.0
numpy
scipy
h5py
```

## Architecture

```
dev/hic-contact-map/
├── app.py          # Dash app with DMC 2.0+ layout and callbacks
├── hic_data.py     # Data loading: cool/mcool reader + synthetic generator
├── hic_figure.py   # Plotly figure generation for contact maps
└── README.md
```

## Integration with Depictio

This prototype follows Depictio component patterns:
- Uses `dmc.*` components (DMC 2.0+)
- Transparent backgrounds for theme compatibility
- `go.Heatmap` based rendering (similar to existing heatmap component)
- Can be registered as a new visualization type via `definitions.py` and `parameter_discovery.py`

To integrate:
1. Add `"hic_contact_map"` to `ALLOWED_VISUALIZATIONS` in `figure_component/definitions.py`
2. Create `create_hic_visualization_definition()` in `parameter_discovery.py`
3. Add `_render_hic_figure()` in `figure_component/utils.py`
4. Route via `render_figure()` type check

## Data Sources

### nf-core/hic pipeline
Output contact maps are in:
- `results/contact_maps/raw/` — raw .cool files
- `results/contact_maps/norm/` — normalized .cool and .mcool files

### S3 test data
```
s3://nf-core-awsmegatests/hic/results-fe4ac656317d24c37e81e7940a526ed9ea812f8e/
```
