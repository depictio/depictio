# Hi-C Contact Map Viewer

Interactive Plotly/Dash prototype for visualizing Hi-C contact maps.
Designed for future integration into Depictio.

## Features

- **Synthetic demo data**: Generates realistic Hi-C contact maps with TADs, loops, and distance-dependent decay
- **Cool/mcool file support**: Reads nf-core/hic pipeline output files via h5py (no cooler dependency)
- **Interactive visualization**: Zoom, pan, region selection with Plotly
- **DMC 2.0+ UI**: Mantine-based controls matching Depictio conventions
- **Configurable**: Color scales, log transform, value capping, resolution switching

## Install

```bash
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .

# Optional: install cooler for advanced features
uv pip install -e ".[cooler]"
```

## Quick Start

```bash
# Synthetic demo (no data files needed)
python app.py

# With a cool/mcool file (e.g. nf-core/hic output)
python app.py --file data/HIC_ES_4.1000000_balanced.cool
python app.py --file data/HIC_ES_4.mcool

# Debug mode
python app.py --debug --port 8051
```

## Download test data (nf-core/hic v2.0.0 mouse ES cell)

```bash
mkdir -p data

# Small — 1Mb resolution (4.2 MB)
aws s3 cp s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/contact_maps/cool/HIC_ES_4.1000000_balanced.cool data/ --no-sign-request

# Medium — 500kb resolution (12 MB)
aws s3 cp s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/contact_maps/cool/HIC_ES_4.500000_balanced.cool data/ --no-sign-request

# Full multi-resolution mcool (368 MB, resolutions: 20kb–10Mb)
aws s3 cp s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/contact_maps/cool/HIC_ES_4.mcool data/ --no-sign-request
```

Sample: HIC_ES_4 (mouse ES cell Hi-C), genome: mm10, 22 chromosomes.

## Architecture

```
dev/hic-contact-map/
├── app.py           # Dash app with DMC 2.0+ layout and callbacks
├── hic_data.py      # Data loading: cool/mcool reader + synthetic generator
├── hic_figure.py    # Plotly figure generation for contact maps
├── pyproject.toml   # Project config for uv/pip install
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

### S3 test data (v2.0.0, complete run)
```
s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/
```

Available resolutions for `.cool`: 20kb, 40kb, 250kb, 500kb, 1Mb
Available resolutions for `.mcool`: 20kb, 40kb, 80kb, 160kb, 320kb, 640kb, 1.28Mb, 2.56Mb, 5.12Mb, 10.24Mb
