# Dashboard YAML Files

This directory contains YAML representations of dashboards for version control and Infrastructure-as-Code workflows.

## Structure

When `organize_by_project: true` (default):
```
dashboards_yaml/
├── project_name/
│   ├── dashboard_title_abc12345.yaml
│   └── another_dashboard_xyz67890.yaml
└── another_project/
    └── dashboard_title_def12345.yaml
```

## Features

- **Bidirectional Sync**: Changes to YAML files are automatically synced to MongoDB
- **Version Control**: Track dashboard configuration changes in git
- **IaC Integration**: Deploy dashboards as code
- **File Watching**: Auto-sync enabled when `dashboard_yaml.enabled: true`

## Configuration

Configure via environment variables or settings:
- `DEPICTIO_DASHBOARD_YAML_ENABLED`: Enable/disable YAML sync (default: true)
- `DEPICTIO_DASHBOARD_YAML_BASE_DIR`: Custom base directory path
- `DEPICTIO_DASHBOARD_YAML_ORGANIZE_BY_PROJECT`: Organize by project (default: true)

## YAML Formats

Depictio supports three YAML export formats, each optimized for different use cases:

### 1. MVP Format (Recommended for IaC) 🎯

**Target: 60-80 lines | ~60-70% smaller than compact**

Minimal, human-readable format optimized for Infrastructure-as-Code workflows:

```yaml
dashboard: 6824cb3b89d2b72169309737
title: Iris Dashboard demo

components:
  - id: sepal-length-by-variety
    type: figure
    data: iris_table
    chart: box
    x: variety
    y: sepal.length
    color: variety
    style:
      map: '{"Setosa": "#1f77b4", "Versicolor": "#ff7f0e"}'
      boxmode: group
      points: all

  - id: sepal-scatter
    type: figure
    data: iris_table
    chart: scatter
    x: sepal.length
    y: sepal.width
    color: variety
    size: petal.length
    style:
      size_max: 20
      marginal_x: histogram

  - id: total-count
    type: card
    data: iris_table
    value: 150
```

**Key Features:**
- ✅ Human-readable component IDs (`sepal-scatter` vs UUIDs)
- ✅ Simple data references (`data: iris_table`)
- ✅ Flattened visualization config (`chart: scatter`, `x:`, `y:`)
- ✅ No layout (auto-generated on import)
- ✅ No runtime state (filter_applied, mode, buttons_data)
- ✅ No metadata bloat

**Enable MVP Format:**
```bash
export DEPICTIO_DASHBOARD_YAML_MVP_MODE=true
```

Or in Python:
```python
from depictio.models.yaml_serialization import dashboard_to_yaml

yaml_content = dashboard_to_yaml(dashboard_dict, mvp_mode=True)
```

### 2. Compact Format (Default)

**Target: ~240 lines | 75-80% smaller than full**

Balanced format with references to reduce duplication:

```yaml
_export_metadata:
  format_version: '2.0'
  exported_at: '2026-01-19T14:24:41'
dashboard_id: 6824cb3b89d2b72169309737
title: Iris Dashboard demo
stored_metadata:
- index: 1e9febfc-e48c-4614-8f0d-5c09ba73991f
  component_type: figure
  dc_ref:
    id: 646b0f3c1e4a2d7f8e5b8c9c
    tag: iris_table
    type: table
  dict_kwargs:
    x: variety
    y: sepal.length
  visu_type: box
stored_layout_data:
- w: 21
  h: 14
  x: 0
  y: 17
  i: box-1e9febfc
```

**Key Features:**
- ✅ Compact dc_ref/wf_ref references (not full configs)
- ✅ Filters out default parameters
- ✅ Includes layout data (for exact positioning)
- ✅ Includes runtime state (complete snapshot)

**Enable Compact Format (default):**
```bash
export DEPICTIO_DASHBOARD_YAML_COMPACT_MODE=true
```

### 3. Full Format (Legacy)

**Target: ~1200 lines | Complete MongoDB dump**

Full MongoDB document structure with all fields:
- All dc_config data (not just references)
- All default parameters
- All metadata fields
- Complete permissions structure

**Use Full Format:**
```bash
export DEPICTIO_DASHBOARD_YAML_COMPACT_MODE=false
export DEPICTIO_DASHBOARD_YAML_MVP_MODE=false
```

## Format Comparison

| Feature | MVP | Compact | Full |
|---------|-----|---------|------|
| **Typical Size** | 60-80 lines | 240 lines | 1200 lines |
| **Human-Readable** | ✅ Excellent | ⚠️ Good | ❌ Verbose |
| **IaC-Friendly** | ✅ Ideal | ⚠️ Good | ❌ Too large |
| **Git-Friendly** | ✅ Minimal diffs | ⚠️ Moderate diffs | ❌ Large diffs |
| **Component IDs** | Human-readable | UUIDs | UUIDs |
| **Data References** | Tags | References | Full configs |
| **Layout** | Auto-generated | Stored | Stored |
| **Runtime State** | Omitted | Included | Included |
| **Permissions** | Omitted | Included | Included |
| **Auto-Import** | ✅ Full restoration | ✅ Full restoration | ✅ Direct |

## When to Use Each Format

### Use MVP Format When:
- ✅ Creating dashboards in git for IaC workflows
- ✅ Version controlling dashboard definitions
- ✅ Minimal file size is important
- ✅ Human readability is a priority
- ✅ Collaboration on dashboard design (easy to review PRs)

### Use Compact Format When:
- ✅ Exact layout positioning matters
- ✅ Need runtime state preservation
- ✅ Exporting for backup/restore
- ✅ Migrating between environments

### Use Full Format When:
- ✅ Debugging MongoDB structure
- ✅ Complete data dump needed
- ✅ Legacy compatibility required

## Configuration

Configure via environment variables or settings:
- `DEPICTIO_DASHBOARD_YAML_ENABLED`: Enable/disable YAML sync (default: true)
- `DEPICTIO_DASHBOARD_YAML_MVP_MODE`: Use MVP format (default: false)
- `DEPICTIO_DASHBOARD_YAML_COMPACT_MODE`: Use compact format (default: true)
- `DEPICTIO_DASHBOARD_YAML_BASE_DIR`: Custom base directory path
- `DEPICTIO_DASHBOARD_YAML_ORGANIZE_BY_PROJECT`: Organize by project (default: true)
- `DEPICTIO_DASHBOARD_YAML_AUTO_LAYOUT`: Auto-generate layout on import (default: false)
- `DEPICTIO_DASHBOARD_YAML_REGENERATE_STATS`: Regenerate column stats on import (default: true)

## Implementation Details

See `depictio/models/yaml_serialization.py` for:
- `dashboard_to_yaml_mvp()` - MVP export logic
- `yaml_mvp_to_dashboard()` - MVP import logic
- `dashboard_to_yaml_dict()` - Compact export logic
- `yaml_dict_to_dashboard()` - Compact import logic
- Auto-format detection in `yaml_to_dashboard_dict()`
