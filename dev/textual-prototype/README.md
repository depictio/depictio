# Depictio Project Wizard - Textual Prototype

## Overview

A Textual-based TUI wizard for creating and editing Depictio project YAML configurations. This prototype provides an interactive interface for building complex project configurations step-by-step.

## Features

### Core Functionality
- ✅ **Step-by-step wizard**: Project → Workflows → Data Collections  
- ✅ **Interactive forms**: Using Textual widgets for input validation
- ✅ **Live YAML preview**: Real-time YAML generation and display
- ✅ **Edit existing projects**: Load and modify existing YAML files
- ✅ **File navigation**: Browse for example files and data sources
- ✅ **Schema auto-generation**: Use polars/pandera for dataframe schema detection

### Advanced Features  
- 🔄 **Pydantic integration**: Validate inputs against project models
- 🔄 **Example-driven design**: Use iris/penguins datasets as templates
- 🔄 **Table-focused**: Focus on Table data collections initially
- 🔄 **Regex helpers**: Interactive regex building and testing
- 🔄 **Column descriptions**: Auto-suggest based on data inspection

## Architecture

### UI Structure
```
┌─────────────────────────────────────────────────────────────────┐
│ Depictio Project Wizard                                         │
├─────────────────────────────────────────────────────────────────┤
│ Steps: [1. Project] [2. Workflows] [3. Data Collections]       │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ Form Panel ────────┐ ┌─ Preview Panel ──────────────────────┐ │
│ │                     │ │ name: "My Project"                  │ │
│ │ Project Name:       │ │ project_type: "basic"               │ │
│ │ [____________]      │ │ workflows:                          │ │
│ │                     │ │   - name: "my_workflow"             │ │
│ │ Project Type:       │ │     engine:                         │ │
│ │ ( ) Basic           │ │       name: "python"                │ │
│ │ (•) Advanced        │ │     data_location:                  │ │
│ │                     │ │       structure: "flat"             │ │
│ │ [Next >]            │ │       locations: [...]              │ │
│ └─────────────────────┘ └─────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Status: Step 1/3 - Project Configuration                       │
└─────────────────────────────────────────────────────────────────┘
```

### Component Architecture
- **WizardApp**: Main application controller
- **StepManager**: Handles step navigation and state
- **ProjectStep**: Project-level configuration
- **WorkflowStep**: Workflow configuration with data location
- **DataCollectionStep**: Data collection configuration with file browsing
- **YAMLPreview**: Live YAML generation and display
- **FileNavigator**: File tree browsing and selection
- **SchemaGenerator**: Automatic dataframe schema detection

## Usage

```bash
# Run the wizard
python wizard.py

# Edit existing project
python wizard.py --edit project.yaml

# Start with template
python wizard.py --template iris
python wizard.py --template penguins
```

## Implementation Plan

### Phase 1: Basic Wizard ✅
- [x] Project step with basic fields
- [x] Simple workflow step  
- [x] Basic data collection step
- [x] YAML preview panel
- [x] Step navigation

### Phase 2: Enhanced UI 🔄
- [ ] File navigation widget
- [ ] Schema auto-generation
- [ ] Regex helper tools
- [ ] Advanced validation

### Phase 3: Integration 🔄
- [ ] Pydantic model integration
- [ ] Template system (iris/penguins)
- [ ] Edit existing projects
- [ ] CLI integration

## Technical Notes

### Dependencies
- **textual**: TUI framework
- **pydantic**: Data validation (reuse depictio models)
- **polars**: Data inspection and schema generation
- **pandera**: Schema validation
- **pyyaml**: YAML generation

### File Structure
```
textual-prototype/
├── wizard.py              # Main application
├── steps/
│   ├── __init__.py
│   ├── base.py            # Base step class
│   ├── project.py         # Project configuration step
│   ├── workflow.py        # Workflow configuration step
│   └── data_collection.py # Data collection step
├── widgets/
│   ├── __init__.py
│   ├── yaml_preview.py    # YAML preview widget
│   ├── file_navigator.py  # File browsing widget
│   └── schema_generator.py # Schema generation widget
├── models/
│   └── wizard_state.py    # Wizard state management
└── templates/
    ├── iris.yaml          # Iris dataset template
    └── penguins.yaml      # Penguins dataset template
```

## Why Textual?

**Advantages over alternatives:**
- **Rich widgets**: Built-in forms, trees, text inputs
- **Styling**: CSS-like styling system
- **Reactive**: Event-driven programming model
- **Interactive**: Mouse and keyboard support
- **Modern**: Active development, good documentation

**Alternatives considered:**
- Rich + Typer: Less interactive, more limited UI
- Inquirer: Simple questionnaires, less flexible
- Prompt Toolkit: More complex, steeper learning curve
- Questionary: Good but less widget variety

## Future Enhancements

- **Multi-file projects**: Handle complex project structures
- **Validation feedback**: Real-time validation with error highlights
- **Plugin system**: Extensible data collection types
- **Export options**: Multiple output formats
- **Integration**: Direct API calls to Depictio server