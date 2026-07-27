# YAML Serialization Module - DEPRECATED

**Status**: Deprecated as of 2026-01-26
**Removal Target**: TBD (after transition period)
**Migration Guide**: See `/YAML_MONGODB_ANALYSIS.md`

---

## ⚠️ This Module is Deprecated

The YAML serialization system (`depictio/models/yaml_serialization/`) is **deprecated** and will be removed in a future release.

### Why Deprecated?

1. **Overcomplexity**: 3,399 lines of code for functionality already provided by simpler means
2. **Redundant**: MongoDB's native JSON format + Pydantic already provides serialization
3. **Maintenance Burden**: 3 competing formats (legacy, compact, MVP) requiring continuous upkeep
4. **Better Alternative**: JSON-based approach achieves the same goals with 98% less code

### What to Use Instead

#### Export Dashboard
```python
# ❌ OLD (YAML)
from depictio.models.yaml_serialization import export_dashboard_to_yaml
yaml_content = export_dashboard_to_yaml(dashboard, format="compact")

# ✅ NEW (JSON)
from bson import json_util
import json

# Export to dict
data = dashboard.model_dump()

# Save to file
with open("dashboard.json", "w") as f:
    json.dump(data, f, indent=2, default=str)
```

#### Import Dashboard
```python
# ❌ OLD (YAML)
from depictio.models.yaml_serialization import import_dashboard_from_file
dashboard = import_dashboard_from_file("dashboard.yaml")

# ✅ NEW (JSON)
from bson import json_util
import json
from depictio.models.models.dashboards import DashboardData

# Load from file
with open("dashboard.json") as f:
    data = json.load(f, object_hook=json_util.object_hook)

# Validate with Pydantic
dashboard = DashboardData.model_validate(data)
await dashboard.save()
```

#### API Endpoints
```python
# ❌ OLD (YAML - DEPRECATED)
POST /api/v1/dashboards/import/yaml
GET  /api/v1/dashboards/export/{id}/yaml

# ✅ NEW (JSON)
POST /api/v1/dashboards/import/json
GET  /api/v1/dashboards/export/{id}/json
GET  /api/v1/dashboards/schema  # Get JSON Schema
```

### Configuration Changes

The YAML system is now **disabled by default**:

```python
# depictio/api/v1/configs/settings_models.py
class DashboardYAMLConfig(BaseSettings):
    enabled: bool = False  # Changed from True
    auto_export_on_save: bool = False  # Changed from True
    auto_import_on_change: bool = False  # Changed from True
    watcher_auto_start: bool = False  # Changed from True
    watch_local_dir: bool = False  # Changed from True
```

To re-enable temporarily (not recommended):
```bash
# Set environment variable
export DEPICTIO_DASHBOARD_YAML_ENABLED=true
```

### Migration Timeline

- **2026-01-26**: YAML system disabled by default, all endpoints marked deprecated
- **TBD**: Documentation updated to use JSON examples
- **TBD**: YAML endpoints removed from API
- **TBD**: Module archived/removed from codebase

### Migration Tools

A migration script is available to convert existing YAML files to JSON:

```bash
# Convert all YAML dashboards to JSON
python scripts/migrate_yaml_to_json.py \
  --yaml-dir dashboards/local \
  --output-dir dashboards/json
```

### Questions?

See the comprehensive analysis and migration guide:
- **Full Analysis**: `/YAML_MONGODB_ANALYSIS.md`
- **Quick Guide**: `/QUICK_DECISION_GUIDE.md`
- **POC Code**: `/SIMPLE_JSON_POC.py`

### Module Contents (Reference Only)

This module will remain for backward compatibility during the transition period:

- `export.py` - YAML generation (3,399 lines total across module)
- `loader.py` - YAML parsing
- `compact_format.py` - Compact format (75-80% size reduction)
- `mvp_format.py` - MVP minimal format (60-80 lines)
- `utils.py` - Shared utilities
- `validation.py` - Schema validation

**Do not extend or enhance this module.** Use JSON-based approaches instead.
