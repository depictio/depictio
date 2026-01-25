# Image Viewer Component Hackathon Guide

## BioHackathon Project: Image Component Integration for Depictio

**Project Lead:** Thomas Weber
**Duration:** 3 days
**Participants:** 3
**Format:** Hybrid

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Goals & Deliverables](#goals--deliverables)
3. [Challenges & Requirements](#challenges--requirements)
4. [Use Cases](#use-cases)
5. [Technical Options](#technical-options)
6. [Sample Data](#sample-data)
7. [Environment Setup](#environment-setup)
8. [Getting Started](#getting-started)
9. [Suggested Approaches](#suggested-approaches)
10. [Resources & References](#resources--references)

---

## Project Overview

### What is Depictio?

Depictio is a modern, interactive platform for creating dashboards from bioinformatics workflow outputs. Built on **FastAPI** (backend) and **Plotly Dash** (frontend), it allows users to:

- Create interactive visualizations (figures, tables, metrics cards)
- Filter data using interactive components (sliders, dropdowns)
- Link components together (selecting data in one affects others)
- Save and share dashboards

### What We're Building

An **image viewer component** for Depictio dashboards that handles microscopy/bioimage data efficiently. Users should be able to:

- Pan and zoom through large images
- View multi-channel fluorescence data
- Connect image selection to other dashboard components (tables, charts)

### Why This Matters

Bioimaging generates massive datasets that are difficult to explore alongside quantitative data. Integrating image viewing into Depictio's dashboard ecosystem enables researchers to correlate visual observations with metrics and statistics in a unified interface.

---

## Goals & Deliverables

### Minimum Viable Product (MVP)

A **standalone Dash application** (outside Depictio codebase) demonstrating:

1. **Image Viewer(s)** - Display images with pan/zoom (format-specific viewers)
2. **Multi-format Support** - Different viewers for different formats (see architecture below)
3. **Metadata Connection** - Image selection linked to other components
4. **Basic Interactivity** - Selecting data shows corresponding image

### Multi-Viewer Architecture

Different formats → Different optimal viewers:

| Format | Viewer | Rationale |
|--------|--------|-----------|
| **TIFF/PNG/JPG** | Simple `html.Img` or dash-leaflet | No special handling needed |
| **OME-TIFF** | Viv/Avivator | Multi-channel, pyramidal support |
| **OME-Zarr** | Vizarr | Cloud-native, chunked access |

```python
def build_image_viewer(format, source, **kwargs):
    if format == "ome-zarr":
        return VizarrViewer(source)
    elif format == "ome-tiff":
        return VivViewer(source)
    else:  # tiff, png, jpg
        return SimpleImageViewer(source)
```

### Stretch Goals

- **Multi-channel Controls** - Toggle/blend fluorescence channels
- **Annotations** - Draw ROIs on images
- **3D Slicing** - Navigate Z-stacks
- **Thumbnail Gallery** - Grid view of multiple images
- **Unified API** - Single component dispatching to format-specific viewers

### Non-Goals (For This Hackathon)

- Full integration into Depictio codebase
- Data processing/conversion (Depictio visualizes, doesn't convert)
- Authentication/authorization
- Cloud deployment

---

## Challenges & Requirements

### Technical Challenges

| Challenge | Description | Difficulty |
|-----------|-------------|------------|
| **Large Image Handling** | Microscopy images can be gigabytes; need tiled/pyramidal loading | High |
| **Multi-channel Rendering** | Fluorescence images have multiple channels to blend | Medium |
| **Format Support** | Various formats (TIFF, OME-TIFF, OME-Zarr, CZI, LIF) | Medium |
| **Web Performance** | Smooth pan/zoom in browser with WebGL | Medium |
| **Dash Integration** | Connecting viewer to Dash callbacks | Medium |
| **Coordinate Systems** | Mapping image pixels to viewer coordinates | Low-Medium |

### Key Requirements

1. **Web-Based** - Must run in browser (no desktop app)
2. **Python Backend** - Dash/Flask compatible
3. **Responsive** - Handle images from small to gigapixel
4. **Open Formats** - Support OME-Zarr and/or OME-TIFF
5. **Interactive** - Pan, zoom, channel selection at minimum

### Format Considerations

| Format | Pros | Cons |
|--------|------|------|
| **OME-Zarr** | Cloud-native, chunked, multi-resolution | Newer, requires conversion |
| **OME-TIFF** | Widely used, Bio-Formats compatible | Not cloud-optimized |
| **Plain TIFF** | Universal | No metadata, no pyramids |
| **Deep Zoom (DZI)** | Optimized for web | No multi-channel |

**Recommendation:** Focus on **OME-Zarr** as primary format, with OME-TIFF as secondary.

---

## Use Cases

### Use Case 1: Cell Imaging Dashboard

A researcher has:
- 100 cell images (fluorescence microscopy)
- A CSV with measurements per cell (area, intensity, markers)

**Workflow:**
1. Select a cell from the data table
2. Image viewer shows that cell's image
3. Adjust channel visibility (DAPI, GFP, mCherry)
4. Compare metrics across selected cells

### Use Case 2: Tissue Section Browser

A pathologist has:
- Whole slide images (WSI) at 40x magnification
- Annotations marking regions of interest
- Quantification data per region

**Workflow:**
1. Pan/zoom across the slide
2. Click a region to see its metrics
3. Filter regions by classification
4. Export selected regions

### Use Case 3: High-Content Screening (HCS)

A drug screening lab has:
- 384-well plate with images per well
- Dose-response measurements

**Workflow:**
1. Select wells from a plate map visualization
2. View images from selected wells
3. Compare phenotypes across conditions

---

## Technical Options

### Option A: Vizarr (Zarr-Only)

**What:** Minimal Zarr viewer built on Viv
**Best For:** OME-Zarr images, Jupyter-like experience
**Integration:** iframe or custom component

```
Pros:
✅ Purpose-built for microscopy
✅ Multi-channel support
✅ GPU-accelerated (WebGL)
✅ Python API available

Cons:
❌ Zarr-only (no TIFF)
❌ Limited Dash integration
❌ Requires CORS configuration
```

**Demo:** https://hms-dbmi.github.io/vizarr/?source=https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr

### Option B: Viv Library (Full Control)

**What:** JavaScript library for OME-TIFF and OME-Zarr
**Best For:** Custom viewers, maximum flexibility
**Integration:** Custom Dash component (React)

```
Pros:
✅ Supports OME-TIFF and OME-Zarr
✅ deck.gl based (composable layers)
✅ Full control over UI
✅ Active development

Cons:
❌ Requires JavaScript/React knowledge
❌ More development effort
❌ Need to build Dash component
```

**Demo:** http://avivator.gehlenborglab.org/

### Option C: dash-leaflet (Map Library Adapted)

**What:** Dash wrapper for Leaflet.js maps
**Best For:** Tile-based images, geospatial
**Integration:** Native Dash component

```
Pros:
✅ Native Dash integration
✅ Well-documented
✅ Supports tile layers
✅ No custom JS needed

Cons:
❌ Not designed for microscopy
❌ No multi-channel support
❌ Requires tile server setup
```

**Docs:** https://dash-leaflet.herokuapp.com/

### Option D: OpenSeadragon (Deep Zoom)

**What:** JavaScript library for deep zoom images
**Best For:** Gigapixel images, pathology
**Integration:** Custom Dash component or iframe

```
Pros:
✅ Excellent for very large images
✅ IIIF support
✅ Mature, well-tested
✅ Plugin ecosystem

Cons:
❌ No multi-channel support
❌ Requires DZI/IIIF format
❌ Custom component needed for Dash
```

**Demo:** https://openseadragon.github.io/

### Recommendation for Hackathon

**Start with Option A (Vizarr) or Option B (Viv)** depending on team skills:

- **More Python-focused team:** Vizarr with iframe approach
- **JS/React experience:** Build with Viv directly

---

## Sample Data

### Public OME-Zarr Datasets

| Dataset | URL | Description |
|---------|-----|-------------|
| IDR 6001240 | `https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr` | Multi-channel fluorescence |
| Platynereis | `https://s3.embl.de/i2k-2020/platy-raw.ome.zarr` | EM volume |
| HeLa Cells | See EBI BioImage Archive | Serial block face SEM |

**Download OME-Zarr:**
```bash
pip install ome-zarr
ome_zarr download https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr
```

### Public OME-TIFF Samples

| Dataset | URL |
|---------|-----|
| Hand E Scan | `https://viv-demo.storage.googleapis.com/HandEuncompressed_Scan1.ome.tif` |
| Multi-channel Test | `https://downloads.openmicroscopy.org/images/OME-TIFF/2016-06/bioformats-artificial/multi-channel.ome.tif` |

**View in Avivator:**
```
http://avivator.gehlenborglab.org/?image_url=https://viv-demo.storage.googleapis.com/HandEuncompressed_Scan1.ome.tif
```

### Converting Your Own Data (Outside Depictio)

> **Note:** Depictio is a visualization platform, not a data processing tool.
> Conversion happens *before* ingestion, using external tools.

**TIFF → OME-Zarr:**
```bash
# Install bioformats2raw
# https://github.com/glencoesoftware/bioformats2raw

bioformats2raw input.tiff output.zarr
```

**Create Pyramidal OME-TIFF:**
```bash
# Using bfconvert from Bio-Formats
bfconvert -pyramid-resolutions 4 -pyramid-scale 2 input.tiff output.ome.tiff
```

---

## Environment Setup

### Prerequisites (Install Before Hackathon!)

Please have the following installed before arriving:

1. **Docker Desktop** - https://www.docker.com/products/docker-desktop/

2. **pixi** (recommended) OR **conda/mamba**:
   ```bash
   # pixi (faster, recommended)
   curl -fsSL https://pixi.sh/install.sh | bash

   # OR conda/mamba
   # https://docs.conda.io/en/latest/miniconda.html
   ```

3. **Python 3.11+**

4. **Node.js 18+** (if building custom components)

5. **Git**

6. **Code editor** (VS Code recommended)

### Standalone PoC Setup (Recommended for Hackathon)

```bash
# Create project directory
mkdir image-viewer-poc
cd image-viewer-poc

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install dash dash-mantine-components plotly
pip install zarr fsspec aiohttp  # For OME-Zarr
pip install ome-zarr  # CLI tools
pip install numpy pandas

# Optional: For Vizarr in Jupyter
pip install vizarr jupyter

# Optional: For serving local files
pip install http-server-with-cors
```

### Full Depictio Setup (Optional)

If you want to explore the full Depictio codebase:

```bash
# Clone repository
git clone https://github.com/depictio/depictio.git
cd depictio

# Option 1: Using pixi (recommended)
curl -fsSL https://pixi.sh/install.sh | bash
pixi install
pixi run api      # Start API server
pixi run dash     # Start Dash frontend

# Option 2: Using Docker Compose
docker compose -f docker-compose.dev.yaml up

# Option 3: Using uv
pip install uv
uv sync
```

**Documentation:** https://depictio.github.io/depictio-docs/latest/

---

## Schedule (CET Time Zone)

### Wednesday 28 January (Day 1)

| Time | Activity |
|------|----------|
| **11:30-12:30** | **Depictio presentation & demo** (Thomas) |
| **12:30-13:00** | Setup check - Docker, pixi/conda working? |
| **13:00-14:00** | *Lunch (EMBL canteen)* |
| **14:00-15:30** | **Brainstorming session:** |
| | • Which formats to support? (TIFF, OME-TIFF, OME-Zarr) |
| | • Explore public demo datasets online |
| | • Define MVP scope & approach |
| **15:30-16:00** | *Coffee break* |
| **16:00-17:30** | **Task distribution & start coding** |
| | • Decide: parallel approaches or collaborative? |
| | • Start implementing based on brainstorming |

### Thursday 29 January (Day 2)

| Time | Activity |
|------|----------|
| **9:30-11:00** | Continue development |
| **11:00-11:30** | *Coffee break* |
| **11:30-13:00** | Sync progress + integrate components |
| **13:00-14:00** | *Lunch* |
| **14:00-15:30** | Core functionality: viewer ↔ metadata connection |
| **15:30-16:00** | *Coffee break* |
| **16:00-18:00** | Polish / stretch goals |
| **18:00-20:00** | *Pizza, beer & informal demos* 🍕 |

### Friday 30 January (Day 3)

| Time | Activity |
|------|----------|
| **9:30-11:00** | **Project presentations** (present your PoC!) |
| **11:00-11:30** | *Coffee break* |
| **11:30-13:00** | Wrap-up presentations + closing remarks |
| **13:00** | *Lunch & end* |

---

## Task Distribution

Tasks will be defined during **Wednesday brainstorming** based on:
- Team skills and interests
- Chosen technical approach(es)
- Format priorities

**Possible splits:**

| Strategy | Description |
|----------|-------------|
| **By format** | P1: Simple TIFF viewer, P2: OME-Zarr (Vizarr), P3: OME-TIFF (Viv) |
| **By feature** | P1: Viewer core, P2: Channel controls, P3: Callbacks/metadata |
| **By approach** | Each person explores different viewer library |
| **Collaborative** | All work on same codebase together |

---

## Suggested Approaches

### Approach 1: Vizarr Iframe (Simplest)

Best for teams wanting quick results with less JS.

```python
# app.py
from dash import Dash, html, dcc, callback, Input, Output
import dash_mantine_components as dmc

app = Dash(__name__)

# Sample image URLs (OME-Zarr)
IMAGES = {
    "Cell 1": "https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr",
    "Platynereis": "https://s3.embl.de/i2k-2020/platy-raw.ome.zarr",
}

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container([
            dmc.Title("Image Viewer PoC", order=1),
            dmc.Grid([
                # Image selector
                dmc.GridCol([
                    dmc.Select(
                        id="image-select",
                        label="Select Image",
                        data=[{"value": k, "label": k} for k in IMAGES.keys()],
                        value=list(IMAGES.keys())[0],
                    ),
                ], span=3),

                # Image viewer (iframe to Vizarr)
                dmc.GridCol([
                    html.Iframe(
                        id="vizarr-viewer",
                        style={"width": "100%", "height": "600px", "border": "none"},
                    ),
                ], span=9),
            ]),
        ], fluid=True),
    ]
)

@callback(
    Output("vizarr-viewer", "src"),
    Input("image-select", "value"),
)
def update_viewer(selected_image):
    zarr_url = IMAGES.get(selected_image)
    return f"https://hms-dbmi.github.io/vizarr/?source={zarr_url}"

if __name__ == "__main__":
    app.run(debug=True)
```

**Limitations:** CORS issues with private data, limited callback integration.

---

### Approach 2: Custom Viv Component (Advanced)

Best for teams with React/JS experience wanting full integration.

**Step 1: Create Dash component boilerplate**
```bash
pip install cookiecutter
cookiecutter https://github.com/plotly/dash-component-boilerplate.git
# Answer prompts: project_name=dash_viv, component_name=VivViewer
```

**Step 2: Install Viv in the component**
```bash
cd dash_viv
npm install @hms-dbmi/viv deck.gl @luma.gl/core
```

**Step 3: Implement React component**
```javascript
// src/lib/components/VivViewer.react.js
import React, { useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import DeckGL from '@deck.gl/react';
import { OrthographicView } from '@deck.gl/core';
import { loadOmeZarr } from '@hms-dbmi/viv';
import { MultiscaleImageLayer } from '@hms-dbmi/viv';

const VivViewer = (props) => {
    const { id, source, setProps } = props;
    const [layers, setLayers] = React.useState([]);

    useEffect(() => {
        async function loadImage() {
            const loader = await loadOmeZarr(source);
            const layer = new MultiscaleImageLayer({
                loader,
                id: 'image-layer',
            });
            setLayers([layer]);
        }
        if (source) loadImage();
    }, [source]);

    return (
        <div id={id} style={{ width: '100%', height: '500px' }}>
            <DeckGL
                views={[new OrthographicView({ id: 'ortho' })]}
                layers={layers}
                controller={true}
            />
        </div>
    );
};

VivViewer.propTypes = {
    id: PropTypes.string,
    source: PropTypes.string,
    setProps: PropTypes.func,
};

export default VivViewer;
```

**Step 4: Build and use in Dash**
```bash
npm run build
pip install -e .
```

```python
from dash_viv import VivViewer

app.layout = html.Div([
    VivViewer(id="viewer", source="https://example.com/image.zarr")
])
```

---

### Approach 3: dash-leaflet with Tile Server (Alternative)

Best for teams familiar with web mapping.

**Step 1: Set up tile server (TiTiler)**
```bash
pip install titiler.core uvicorn
```

**Step 2: Create Dash app with leaflet**
```python
import dash_leaflet as dl
from dash import Dash, html

app = Dash(__name__)

app.layout = html.Div([
    dl.Map([
        dl.TileLayer(url="http://localhost:8000/tiles/{z}/{x}/{y}.png"),
    ],
    style={'height': '600px'},
    center=[0, 0],
    zoom=0,
    crs="Simple",  # For non-geographic images
    )
])
```

**Note:** Requires converting images to COG (Cloud Optimized GeoTIFF) or tile pyramid.

---

## Resources & References

### Documentation

| Resource | URL |
|----------|-----|
| **Depictio Docs** | https://depictio.github.io/depictio-docs/latest/ |
| **Dash Documentation** | https://dash.plotly.com/ |
| **Dash Mantine Components** | https://www.dash-mantine-components.com/ |
| **Viv Library** | https://github.com/hms-dbmi/viv |
| **Vizarr** | https://github.com/hms-dbmi/vizarr |
| **OME-Zarr Spec** | https://ngff.openmicroscopy.org/latest/ |

### Tools

| Tool | Purpose | URL |
|------|---------|-----|
| **bioformats2raw** | Convert images to OME-Zarr | https://github.com/glencoesoftware/bioformats2raw |
| **ome-zarr-py** | Python OME-Zarr tools | https://github.com/ome/ome-zarr-py |
| **napari** | Desktop viewer (for comparison) | https://napari.org/ |

### Papers

- [Viv: Multiscale visualization of high-resolution multiplexed bioimaging data](https://www.nature.com/articles/s41592-022-01482-7) - Nature Methods 2022
- [OME-Zarr: a cloud-optimized bioimaging file format](https://link.springer.com/article/10.1007/s00418-023-02209-1) - Histochemistry and Cell Biology 2023

### Community

- **Image.sc Forum** - https://forum.image.sc/ (search "viv", "vizarr", "ome-zarr")
- **OME Community** - https://www.openmicroscopy.org/

---

## FAQ

### Q: Should we support one format or multiple?

**A:** Consider supporting **multiple formats with different viewers**:
- Simple images (TIFF/PNG) → basic viewer
- OME-Zarr → Vizarr
- OME-TIFF → Viv/Avivator

This can be a good task split for parallel work!

### Q: What if we get stuck with CORS errors?

**A:** Options:
1. Use publicly hosted datasets (no CORS issues)
2. Run a local HTTP server with CORS enabled: `npx http-server --cors`
3. Proxy requests through your backend

### Q: How do we connect the viewer to a data table?

**A:** Use Dash callbacks:
```python
@callback(
    Output("viewer", "source"),
    Input("data-table", "selected_rows"),
    State("data-table", "data"),
)
def update_image(selected, data):
    if selected:
        return data[selected[0]]["image_url"]
    return dash.no_update
```

### Q: Can we work in parallel or should we collaborate?

**A:** Decide during Wednesday brainstorming! Options:
- **Parallel by format:** Each person tackles a different format/viewer
- **Parallel by feature:** Split viewer/callbacks/UI
- **Collaborative:** All work on same codebase
- **Hybrid:** Start parallel, integrate Thursday afternoon

---

## Contact & Support

**Project Lead:** Thomas Weber
**Depictio Repository:** https://github.com/depictio/depictio
**Issues:** https://github.com/depictio/depictio/issues

---

*Last updated: January 2025*
