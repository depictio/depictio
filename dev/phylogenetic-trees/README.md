# Phylogenetic Tree Prototypes

Prototypes for phylogenetic tree visualization in depictio, inspired by [Microreact](https://microreact.org/).

## Quick Start

```bash
# From project root, using the project venv:
pip install biopython  # if not already installed

# Run individual prototypes:
python dev/phylogenetic-trees/prototype_plotly.py      # Port 8051 - Plotly traces
python dev/phylogenetic-trees/prototype_cytoscape.py   # Port 8052 - Cytoscape graph
python dev/phylogenetic-trees/prototype_combined.py    # Port 8053 - Combined viewer

# Prototype 4 requires building the custom Dash component first:
cd packages/dash-phylotree && npm install && npm run build
pip install -e packages/dash-phylotree
python dev/phylogenetic-trees/prototype_phylocanvas.py # Port 8054 - Phylocanvas 3
```

## Prototypes

### 1. `prototype_plotly.py` — Pure Plotly Traces (port 8051)
Renders trees as Plotly scatter/line traces with manually computed coordinates.

**Layouts**: Rectangular, Circular, Radial (unrooted), Diagonal

**Pros**: Full control over rendering, circular/radial layouts look great, consistent with existing depictio figure components, Plotly's zoom/pan/hover.

**Cons**: Many traces for large trees (one per edge), less native graph interactivity than Cytoscape.

### 2. `prototype_cytoscape.py` — Dash Cytoscape (port 8052)
Renders trees as Cytoscape.js graph with built-in layout algorithms.

**Layouts**: Preset (phylogram), Dagre (hierarchical), Breadthfirst, Circle, Concentric, CoSE (force-directed)

**Pros**: Rich interactivity (click selection, box selection, hover), built-in layout algorithms, `dash-cytoscape` already a project dependency, good for graph operations.

**Cons**: No true circular/radial phylogram layout (circle layout != circular phylogram), less fine-grained visual control than Plotly.

### 3. `prototype_combined.py` — Combined Viewer (port 8053)
Best of both worlds: switch between Plotly and Cytoscape engines via segmented control.

**Features**:
- Engine toggle (Plotly vs Cytoscape)
- Dynamic layout options per engine
- Metadata coloring with legend
- Newick file upload + sample trees
- Dark/light theme toggle
- Node info panel on click

### 4. `prototype_phylocanvas.py` — Phylocanvas 3 / Custom Dash Component (port 8054)
Uses a custom Dash component (`dash-phylotree`) wrapping [react-phylogeny-tree](https://github.com/mkoliba/react-phylogeny-tree), which is a React wrapper around Phylocanvas 3 (`@mkoliba/phylogeny-tree`). Renders directly to HTML canvas.

**Layouts**: Rectangular, Circular, Radial, Diagonal, Hierarchical (all 5 natively!)

**Pros**: Purpose-built for phylogenetics, all 5 tree layouts natively, canvas rendering (fast), native interaction (pan/zoom/selection/context menu), handles up to ~15k leaves, closest to Microreact's actual rendering engine.

**Cons**: Requires building a custom Dash component (`npm install && npm run build`), canvas-based (harder to integrate with Plotly theming), no Plotly hover/trace interop.

**Custom component**: `packages/dash-phylotree/` — wraps react-phylogeny-tree with Dash-compatible JSON props and `setProps()` for bidirectional selectedIds.

## Architecture

```
dev/phylogenetic-trees/
├── README.md
├── tree_utils.py              # Core: Newick parsing, coordinate computation
├── prototype_plotly.py        # Prototype 1: Plotly traces
├── prototype_cytoscape.py     # Prototype 2: Cytoscape graph
├── prototype_combined.py      # Prototype 3: Combined viewer
├── prototype_phylocanvas.py   # Prototype 4: Phylocanvas 3 (custom Dash component)
└── data/
    ├── sample_tree.nwk        # Mammal phylogeny (15 taxa)
    ├── bacterial_tree.nwk     # Bacterial phylogeny (21 taxa)
    ├── sample_metadata.csv    # Metadata for bacterial tree
    └── mammal_metadata.csv    # Metadata for mammal tree
```

### `tree_utils.py` — Core Utilities

| Function | Description |
|---|---|
| `parse_newick(str)` | Parse Newick string → Biopython Tree |
| `compute_rectangular_coords(tree)` | Rectangular phylogram (x=depth, y=leaf order) |
| `compute_circular_coords(tree)` | Circular phylogram (polar transform of rectangular) |
| `compute_radial_coords(tree)` | Radial/unrooted (equal-angle algorithm) |
| `compute_diagonal_coords(tree)` | Diagonal cladogram (direct parent→child lines) |
| `merge_metadata_to_nodes(nodes, df)` | Join metadata CSV to tree leaf nodes |

## Research: Rendering Library Options

### Option A: Pure Plotly Traces (recommended for depictio)
- **Approach**: Parse tree with Biopython, compute coordinates, render as `go.Scatter` traces
- **Circular layout**: Polar coordinate transform `(r, θ)` with arc interpolation for branches
- **Best for**: Consistent with existing figure component architecture, easy theme integration
- **Reference**: [empet/Phylogenetic-trees](https://github.com/empet/Phylogenetic-trees)

### Option B: Dash Cytoscape
- **Approach**: Convert tree to Cytoscape elements (nodes + edges), use built-in layouts
- **Layouts**: dagre (best for trees), breadthfirst, circle, cose, preset
- **Best for**: Interactive exploration, node selection, subgraph highlighting
- **Already a dependency**: `dash-cytoscape==1.0.2` in `pyproject.toml`
- **Reference**: [Dash Cytoscape Biopython example](https://dash.plotly.com/cytoscape/biopython)

### Option C: Phylocanvas.gl (future consideration)
- **What**: WebGL tree viewer used by Microreact, supports rect/circular/radial/diagonal/hierarchical
- **Approach**: Would need a custom Dash component wrapping `@phylocanvas/phylocanvas.gl`
- **Pros**: Purpose-built for phylogenetics, scales to 100k+ leaves, all layout types native
- **Cons**: Requires building a custom Dash React component
- **Reference**: [Phylocanvas.gl docs](https://www.phylocanvas.gl/docs/)
- **React wrapper exists**: [react-phylogeny-tree](https://github.com/mkoliba/react-phylogeny-tree) wraps Phylocanvas 3

### Option D: Dash Bio Clustergram
- **Not suitable**: Clustergram is for heatmaps with dendrograms, not standalone phylogenetic trees
- **Reference**: [Dash Bio](https://dash.plotly.com/dash-bio/clustergram)

## Microreact Feature Comparison

| Feature | Microreact | Plotly Proto | Cytoscape Proto | Phylocanvas Proto |
|---|---|---|---|---|
| Rectangular tree | ✅ | ✅ | ✅ (dagre/preset) | ✅ |
| Circular tree | ✅ | ✅ | ❌ (circle ≠ circular phylogram) | ✅ |
| Radial tree | ✅ | ✅ | ❌ | ✅ |
| Diagonal tree | ✅ | ✅ | ❌ | ✅ |
| Hierarchical tree | ✅ | ✅ (rectangular) | ✅ (breadthfirst) | ✅ |
| Leaf labels | ✅ | ✅ | ✅ | ✅ |
| Metadata coloring | ✅ | ✅ | ✅ | ✅ |
| Node selection | ✅ | ⚠️ (click only) | ✅ (click + box) | ✅ (click + context menu) |
| Subtree filtering | ✅ | ❌ | ✅ (possible) | ✅ (context menu) |
| Zoom/Pan | ✅ | ✅ | ✅ | ✅ |
| Newick input | ✅ | ✅ | ✅ | ✅ |
| Canvas rendering | ✅ | ❌ (SVG) | ❌ (SVG) | ✅ |
| Same engine as Microreact | ✅ | ❌ | ❌ | ✅ (Phylocanvas 3) |

## Integration Path into Depictio

Future integration would follow the existing component pattern:

```
depictio/models/components/tree.py         # TreeComponent model
depictio/models/components/lite.py         # TreeLiteComponent (YAML-definable)
depictio/dash/modules/tree_component/
├── __init__.py
├── utils.py                               # build_tree() + render_tree()
├── design_ui.py                           # Stepper step 3 configuration
└── callbacks/
    ├── core.py                            # Rendering callback
    ├── design.py                          # Design panel callbacks
    └── edit.py                            # Edit mode callbacks
```

**Data flow**: Newick string stored in data collection → API serves → Dash renders with tree_utils.

## Dependencies

- `biopython` — Tree parsing (Newick, PhyloXML, NEXUS) — for prototypes 1-3
- `dash-cytoscape` — Already in pyproject.toml — for prototypes 2-3
- `dash-phylotree` — Custom package in `packages/dash-phylotree/` — for prototype 4
- `plotly` / `dash` — Already in project
- `dash-mantine-components` — Already in project
- `pandas` — For metadata handling

### Building dash-phylotree

```bash
cd packages/dash-phylotree
npm install                    # Install react-phylogeny-tree + webpack deps
npm run build                  # Bundle → dash_phylotree/dash_phylotree.min.js (96 KB)
pip install -e .               # Install Python package in editable mode
```

The package wraps [react-phylogeny-tree](https://github.com/mkoliba/react-phylogeny-tree) v0.0.4, which uses `@mkoliba/phylogeny-tree` (Phylocanvas 3 beta). The React component renders to an HTML canvas and supports all 5 tree layouts natively.
