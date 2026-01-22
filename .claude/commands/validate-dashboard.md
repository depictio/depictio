# Dashboard YAML Validation

Validate dashboard YAML files for syntax, schema, and required fields before deployment or syncing to MongoDB.

## Instructions

Use the depictio CLI dashboard validation tool to check YAML files:

1. **Parse arguments** to determine what to validate:
   - Single file path
   - Directory path
   - No args = validate current directory recursively

2. **Run validation** using the appropriate command:
   - Single file: `depictio dashboard validate <file>`
   - Directory: `depictio dashboard validate-dir <dir> --recursive`

3. **Report results clearly**:
   - Show validation status (✓ Valid / ✗ Invalid)
   - Display error count and warnings
   - For failures, show detailed error table with:
     - Component ID
     - Field name
     - Error message

4. **If validation fails**:
   - Analyze the errors
   - Suggest specific fixes for each issue
   - Offer to fix common issues automatically
   - Explain what each component type requires

5. **If validation passes**:
   - Confirm success
   - Show summary (X files validated, 0 errors)
   - Optionally suggest next steps (deploy, commit, etc.)

## Validation Checks

The validator checks for:

- **YAML syntax**: Valid YAML parsing
- **Required fields**: `title`, `components` array
- **Component structure**: Each component must have `type` field
- **Common component fields**: All components must have:
  - `workflow`: Must be a tag name (e.g., `iris_workflow`), NOT a tag reference (e.g., `wf_abc123`)
  - `data_collection`: Must be a tag name (e.g., `iris_table`), NOT a tag reference (e.g., `dc_646b0f3c`)
- **Type-specific requirements**:
  - `figure` components need `visualization` field
  - `card` components need `aggregation` field
  - `interactive` components need `filter` field

## Usage Examples

`/validate-dashboard` - Validate all YAML files in current directory

`/validate-dashboard <file>` - Validate specific YAML file
Example: `/validate-dashboard dashboards/my_dashboard.yaml`

`/validate-dashboard <dir>` - Validate all YAML files in directory
Example: `/validate-dashboard dashboards/`

`/validate-dashboard <file> --verbose` - Validate with detailed warnings

`/validate-dashboard <file> --fix` - Validate and auto-fix common issues (if implementing)

## Common Issues and Fixes

### Missing title
```yaml
# ❌ Invalid
dashboard: test-id
components: []

# ✓ Valid
title: My Dashboard  # Add this
dashboard: test-id
components: []
```

### Figure missing visualization
```yaml
# ❌ Invalid
- id: my-figure
  type: figure
  workflow: my_workflow
  data_collection: my_data

# ✓ Valid
- id: my-figure
  type: figure
  workflow: my_workflow
  data_collection: my_data
  visualization:      # Add this
    chart: scatter
    x: column1
    y: column2
```

### Card missing aggregation
```yaml
# ❌ Invalid
- id: my-card
  type: card
  workflow: my_workflow
  data_collection: my_data

# ✓ Valid
- id: my-card
  type: card
  workflow: my_workflow
  data_collection: my_data
  aggregation:        # Add this
    column: value
    function: average
    column_type: float64
```

### Tag references instead of tag names
```yaml
# ❌ Invalid - using tag references
- id: my-figure
  type: figure
  workflow: wf_abc123           # Tag reference NOT allowed
  data_collection: dc_646b0f3c  # Tag reference NOT allowed
  visualization:
    chart: scatter

# ✓ Valid - using tag names
- id: my-figure
  type: figure
  workflow: iris_workflow       # Human-readable tag name
  data_collection: iris_table   # Human-readable tag name
  visualization:
    chart: scatter
```

## Python Path

Use the project Python environment: `/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python`

Run as module: `python -m depictio.cli.depictio_cli dashboard validate <args>`

## Notes

- The validation tool uses the validation module at `depictio/models/yaml_serialization/validation.py`
- Validation can be enabled/disabled via environment variables:
  - `DEPICTIO_DASHBOARD_YAML_ENABLE_VALIDATION=true/false`
  - `DEPICTIO_DASHBOARD_YAML_BLOCK_ON_VALIDATION_ERRORS=true/false`
- Auto-sync watcher uses same validation logic to block invalid files
- Exit codes: 0 = valid, 1 = invalid (useful for CI/CD pipelines)

$ARGUMENTS
