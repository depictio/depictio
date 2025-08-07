#!/usr/bin/env python3
"""
Depictio Project Wizard - Modal-Based TUI Application

A streamlined wizard for creating Depictio project YAML configurations:
- Project information section
- Workflow management with modal creation
- Data collection management via modals for each workflow
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)

# Depictio brand colors from depictio/dash/colors.py
DEPICTIO_COLORS = {
    "purple": "#9966CC",
    "violet": "#7A5DC7",
    "blue": "#6495ED",
    "teal": "#45B8AC",
    "green": "#8BC34A",
    "yellow": "#F9CB40",
    "orange": "#F68B33",
    "pink": "#E6779F",
    "red": "#E53935",
    "black": "#000000",
    "grey": "#B0BEC5",
}

# from textual.css import CSS  # Not needed for basic styling

# Add the project root to the path to import depictio models
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from depictio.models.models.data_collections import DataCollection
    from depictio.models.models.projects import Project
    from depictio.models.models.workflows import Workflow
    HAS_DEPICTIO = True
except ImportError:
    HAS_DEPICTIO = False
    print("Warning: Could not import Depictio models. Some validation features will be disabled.")


class WizardState:
    """Manages the state of the wizard across different steps."""
    
    def __init__(self):
        self.current_step = 0
        self.project_data = {"project_type": "basic"}  # Set default project type
        self.workflows = []
        self.data_collections = []
        self.file_path: Optional[Path] = None
        
    def to_yaml(self) -> str:
        """Convert current state to YAML format."""
        config = {
            "name": self.project_data.get("name", ""),
            "project_type": self.project_data.get("project_type", "basic"),
        }
        
        # Add optional fields
        if self.project_data.get("data_management_platform_project_url"):
            config["data_management_platform_project_url"] = self.project_data["data_management_platform_project_url"]
            
        if self.project_data.get("is_public") is not None:
            config["is_public"] = self.project_data["is_public"]
        
        # Add workflows
        if self.workflows:
            config["workflows"] = self.workflows
            
        # Add direct data collections for basic projects
        if self.project_data.get("project_type") == "basic" and self.data_collections:
            config["data_collections"] = self.data_collections
            
        return yaml.dump(config, default_flow_style=False, sort_keys=False)
        
    def load_from_yaml(self, file_path: Path) -> None:
        """Load wizard state from existing YAML file."""
        self.file_path = file_path
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
            
        # Extract project data
        self.project_data = {
            "name": data.get("name", ""),
            "project_type": data.get("project_type", "basic"),
            "data_management_platform_project_url": data.get("data_management_platform_project_url", ""),
            "is_public": data.get("is_public", False),
        }
        
        # Extract workflows
        self.workflows = data.get("workflows", [])
        
        # Extract data collections
        self.data_collections = data.get("data_collections", [])
    
    def load_from_dict(self, data: dict) -> None:
        """Load wizard state from parsed YAML dictionary."""
        # Extract project data
        self.project_data = {
            "name": data.get("name", ""),
            "project_type": data.get("project_type", "basic"),
            "data_management_platform_project_url": data.get("data_management_platform_project_url", ""),
            "is_public": data.get("is_public", False),
        }
        
        # Extract workflows
        self.workflows = data.get("workflows", [])
        
        # Extract data collections
        self.data_collections = data.get("data_collections", [])


class WorkflowModal(ModalScreen[dict]):
    """Modal screen for creating a new workflow."""
    
    def compose(self) -> ComposeResult:
        with Container(id="modal-dialog"):
            yield Label("Create New Workflow", id="modal-title")
            
            yield Label("Workflow Name:")
            yield Input(placeholder="Enter workflow name...", id="workflow-name")
            
            yield Label("Engine:")
            with RadioSet(id="workflow-engine"):
                yield RadioButton("Python", value=True)
                yield RadioButton("R", value=False)
                yield RadioButton("Snakemake", value=False)
            
            yield Label("Data Structure:")
            with RadioSet(id="data-structure"):
                yield RadioButton("Flat", value=True)
                yield RadioButton("Sequencing Runs", value=False)
            
            yield Label("Data Location:")
            yield Input(placeholder="./data", id="data-location")
            
            # Regex pattern field (only shown for sequencing-runs)
            with Container(id="regex-container", classes="hidden"):
                yield Label("Runs Regex Pattern:")
                yield Input(placeholder=".*\\.fastq$", id="runs-regex")
                yield Static("", id="regex-validation", classes="validation-message")
            
            with Horizontal(id="modal-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="error")
                yield Button("Save", id="save-btn", variant="success")
    
    def on_mount(self) -> None:
        """Set up initial state."""
        self._update_regex_visibility()
    
    @on(RadioSet.Changed, "#data-structure")
    def _on_data_structure_change(self, _: RadioSet.Changed) -> None:
        """Handle data structure radio button changes."""
        self._update_regex_visibility()
    
    def _update_regex_visibility(self) -> None:
        """Show/hide regex field based on data structure selection."""
        try:
            data_structure_radio = self.query_one("#data-structure", RadioSet)
            regex_container = self.query_one("#regex-container")
            
            # Check if "Sequencing Runs" is selected
            sequencing_selected = False
            for button in data_structure_radio.query(RadioButton):
                if button.value and "Sequencing" in str(button.label):
                    sequencing_selected = True
                    break
            
            if sequencing_selected:
                regex_container.remove_class("hidden")
            else:
                regex_container.add_class("hidden")
        except Exception:
            pass
    
    @on(Button.Pressed, "#cancel-btn")
    def cancel_modal(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)
    
    @on(Button.Pressed, "#save-btn")
    def save_workflow(self) -> None:
        """Save the workflow and close the modal."""
        workflow_name = self.query_one("#workflow-name", Input).value.strip()
        if not workflow_name:
            self.notify("Please enter a workflow name", severity="error")
            return
        
        # Get selected engine
        engine_radio = self.query_one("#workflow-engine", RadioSet)
        engine_name = "python"
        for button in engine_radio.query(RadioButton):
            if button.value:
                engine_name = button.label.plain.lower()
                break
        
        # Get data structure
        structure_radio = self.query_one("#data-structure", RadioSet)
        structure = "flat"
        for button in structure_radio.query(RadioButton):
            if button.value:
                structure = "flat" if button.label.plain == "Flat" else "sequencing-runs"
                break
        
        # Get data location
        data_location = self.query_one("#data-location", Input).value or "./data"
        
        # Get regex pattern
        runs_regex = self.query_one("#runs-regex", Input).value or ".*"
        
        # Validate regex for sequencing-runs
        if structure == "sequencing-runs":
            try:
                re.compile(runs_regex)
            except re.error as e:
                self.notify(f"Invalid regex pattern: {str(e)}", severity="error")
                return
        
        # Create workflow object
        workflow = {
            "name": workflow_name,
            "engine": {"name": engine_name},
            "data_location": {
                "structure": structure,
                "locations": [data_location]
            },
            "data_collections": []
        }
        
        # Add runs_regex for sequencing-runs structure
        if structure == "sequencing-runs":
            workflow["data_location"]["runs_regex"] = runs_regex
        
        self.dismiss(workflow)


class DataCollectionModal(ModalScreen[dict]):
    """Modal screen for creating a new data collection."""
    
    def __init__(self, workflow_name: str):
        super().__init__()
        self.workflow_name = workflow_name
    
    def compose(self) -> ComposeResult:
        with Container(id="modal-dialog"):
            yield Label(f"Add Data Collection to: {self.workflow_name}", id="modal-title")
            
            yield Label("Data Collection Name:")
            yield Input(placeholder="Enter collection name...", id="dc-name")
            
            yield Label("Description:")
            yield Input(placeholder="Enter description...", id="dc-description")
            
            yield Label("Type:")
            with RadioSet(id="dc-type"):
                yield RadioButton("Table", value=True)
                yield RadioButton("JBrowse2", value=False)
            
            yield Label("Metatype:")
            with RadioSet(id="dc-metatype"):
                yield RadioButton("Metadata", value=True)
                yield RadioButton("Aggregate", value=False)
            
            yield Label("Scan Mode:")
            with RadioSet(id="scan-mode"):
                yield RadioButton("Single File", value=True)
                yield RadioButton("Recursive", value=False)
            
            yield Label("File Pattern/Filename:")
            yield Input(placeholder="*.csv or specific filename", id="file-pattern")
            
            yield Label("Format:")
            with RadioSet(id="file-format"):
                yield RadioButton("CSV", value=True)
                yield RadioButton("TSV", value=False)
                yield RadioButton("Parquet", value=False)
            
            with Horizontal(id="modal-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="error")
                yield Button("Save", id="save-btn", variant="success")
    
    @on(Button.Pressed, "#cancel-btn")
    def cancel_modal(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)
    
    @on(Button.Pressed, "#save-btn")
    def save_data_collection(self) -> None:
        """Save the data collection and close the modal."""
        dc_name = self.query_one("#dc-name", Input).value.strip()
        if not dc_name:
            self.notify("Please enter a data collection name", severity="error")
            return
        
        dc_description = self.query_one("#dc-description", Input).value or "Data collection"
        
        # Get type
        type_radio = self.query_one("#dc-type", RadioSet)
        dc_type = "Table"
        for button in type_radio.query(RadioButton):
            if button.value:
                dc_type = button.label.plain
                break
        
        # Get metatype
        metatype_radio = self.query_one("#dc-metatype", RadioSet)
        metatype = "Metadata"
        for button in metatype_radio.query(RadioButton):
            if button.value:
                metatype = button.label.plain
                break
        
        # Get scan mode
        scan_radio = self.query_one("#scan-mode", RadioSet)
        scan_mode = "single"
        for button in scan_radio.query(RadioButton):
            if button.value:
                scan_mode = "single" if button.label.plain == "Single File" else "recursive"
                break
        
        # Get file pattern
        file_pattern = self.query_one("#file-pattern", Input).value or "*.csv"
        
        # Get format
        format_radio = self.query_one("#file-format", RadioSet)
        file_format = "CSV"
        for button in format_radio.query(RadioButton):
            if button.value:
                file_format = button.label.plain
                break
        
        # Create data collection
        data_collection = {
            "data_collection_tag": dc_name,
            "description": dc_description,
            "config": {
                "type": dc_type,
                "metatype": metatype,
                "scan": {
                    "mode": scan_mode,
                    "scan_parameters": {}
                },
                "dc_specific_properties": {
                    "format": file_format,
                    "polars_kwargs": {"separator": "," if file_format == "CSV" else "\t"}
                }
            }
        }
        
        # Set scan parameters based on mode
        if scan_mode == "single":
            data_collection["config"]["scan"]["scan_parameters"]["filename"] = file_pattern
        else:
            data_collection["config"]["scan"]["scan_parameters"]["regex_config"] = {"pattern": file_pattern}
        
        self.dismiss(data_collection)


class ProjectStep(Container):
    """Step 1: Project Configuration"""
    
    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(**kwargs)
        self.wizard_state = wizard_state
        
    def compose(self) -> ComposeResult:
        yield Label("Project Configuration", classes="step-title")
        yield Label("Configure basic project information")
        
        with Vertical(classes="form-container"):
            yield Label("Project Name:")
            yield Input(
                value=self.wizard_state.project_data.get("name", ""),
                placeholder="Enter project name...",
                id="project-name"
            )
            
            yield Label("Project Type:")
            with RadioSet(id="project-type"):
                yield RadioButton("Basic", value=True if self.wizard_state.project_data.get("project_type") == "basic" else False)
                yield RadioButton("Advanced", value=True if self.wizard_state.project_data.get("project_type") == "advanced" else False)
            
            yield Label("Data Management Platform URL (optional):")
            yield Input(
                value=self.wizard_state.project_data.get("data_management_platform_project_url", ""),
                placeholder="https://example.com/project/...",
                id="project-url"
            )
            
            yield Label("Public Project:")
            with RadioSet(id="project-public"):
                yield RadioButton("Public", value=self.wizard_state.project_data.get("is_public", False))
                yield RadioButton("Private", value=not self.wizard_state.project_data.get("is_public", False))
    
    @on(Input.Changed)
    def update_project_data(self, event: Input.Changed) -> None:
        """Update wizard state when input values change."""
        if event.input.id == "project-name":
            self.wizard_state.project_data["name"] = event.value
        elif event.input.id == "project-url":
            self.wizard_state.project_data["data_management_platform_project_url"] = event.value
        
        # Update YAML preview
        self.app.update_preview()
            
    @on(RadioSet.Changed)
    def update_radio_data(self, event: RadioSet.Changed) -> None:
        """Update wizard state when radio selections change."""
        if event.radio_set.id == "project-type":
            self.wizard_state.project_data["project_type"] = "basic" if event.pressed.label.plain == "Basic" else "advanced"
        elif event.radio_set.id == "project-public":
            self.wizard_state.project_data["is_public"] = event.pressed.label.plain == "Public"
        
        # Update YAML preview
        self.app.update_preview()


class WorkflowStep(Container):
    """Step 2: Workflow Configuration"""
    
    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(**kwargs)
        self.wizard_state = wizard_state
        
    def compose(self) -> ComposeResult:
        yield Label("Workflow Configuration", classes="step-title")
        yield Label("Configure workflows for your project")
        
        # For now, show a simple form for one workflow
        with Vertical(classes="form-container"):
            yield Label("Workflow Name:")
            yield Input(placeholder="Enter workflow name...", id="workflow-name")
            
            yield Label("Engine:")
            with RadioSet(id="workflow-engine"):
                yield RadioButton("Python", value=True)
                yield RadioButton("Snakemake", value=False)
                yield RadioButton("Nextflow", value=False)
            
            yield Label("Data Structure:")
            with RadioSet(id="data-structure"):
                yield RadioButton("Flat", value=True)
                yield RadioButton("Sequencing Runs", value=False)
            
            yield Label("Data Locations:")
            yield Input(placeholder="Enter data location path...", id="data-location")
            
            yield Label("Runs Regex (for sequencing-runs structure):")
            yield Input(placeholder="Enter regex pattern (e.g., .*_R[12]_.*\\.fastq\\.gz)", id="runs-regex")
            yield Static("", id="regex-validation", classes="validation-message")
            
            yield Button("🔍 Validate Regex + Path", id="validate-combo", variant="default")
            yield Button("Add Workflow", id="add-workflow", variant="primary")
            
            # Always show workflow management section
            yield Label("Workflow Management:", classes="section-title")
            with Vertical(id="existing-workflows"):
                if self.wizard_state.workflows:
                    for i, workflow in enumerate(self.wizard_state.workflows):
                        with Horizontal(classes="workflow-item"):
                            yield Label(f"• {workflow['name']} ({workflow['data_location']['structure']})", classes="workflow-label")
                            yield Button("🗑️", id=f"delete-workflow-{i}", variant="error", classes="delete-btn")
                else:
                    yield Label("No workflows added yet", classes="empty-state")
            
    @on(Input.Changed)
    def update_workflow_data(self, _: Input.Changed) -> None:
        """Update wizard state when workflow inputs change."""
        # Update YAML preview
        self.app.update_preview()
    
    @on(RadioSet.Changed)
    def update_workflow_radio(self, event: RadioSet.Changed) -> None:
        """Update wizard state when workflow radio selections change."""
        # Update YAML preview
        self.app.update_preview()
        # Clear validation message when data structure changes
        if str(event.radio_set.id) == "data-structure":
            self.query_one("#regex-validation", Static).update("")
    
    @on(Input.Changed, "#runs-regex")
    def validate_regex_on_change(self, event: Input.Changed) -> None:
        """Validate regex pattern as user types."""
        regex_pattern = event.value
        validation_msg = self.query_one("#regex-validation", Static)
        
        if not regex_pattern:
            validation_msg.update("")
            validation_msg.remove_class("validation-success", "validation-error")
            return
        
        try:
            re.compile(regex_pattern)
            validation_msg.update("✓ Valid regex pattern")
            validation_msg.remove_class("validation-error")
            validation_msg.add_class("validation-success")
        except re.error as e:
            validation_msg.update(f"✗ Invalid regex: {str(e)}")
            validation_msg.remove_class("validation-success")
            validation_msg.add_class("validation-error")
    
    @on(Button.Pressed, "#validate-combo")
    def validate_path_regex_combo(self) -> None:
        """Validate the combination of data location and regex pattern."""
        data_location = self.query_one("#data-location", Input).value
        regex_pattern = self.query_one("#runs-regex", Input).value
        validation_msg = self.query_one("#regex-validation", Static)
        
        if not data_location:
            validation_msg.update("✗ Please enter a data location path")
            validation_msg.remove_class("validation-success")
            validation_msg.add_class("validation-error")
            return
        
        if not regex_pattern:
            validation_msg.update("✗ Please enter a regex pattern")
            validation_msg.remove_class("validation-success")  
            validation_msg.add_class("validation-error")
            return
        
        # Validate regex syntax first
        try:
            compiled_regex = re.compile(regex_pattern)
        except re.error as e:
            validation_msg.update(f"✗ Invalid regex: {str(e)}")
            validation_msg.remove_class("validation-success")
            validation_msg.add_class("validation-error")
            return
        
        # Check if path exists (basic validation)
        path_obj = Path(data_location)
        if not path_obj.exists():
            validation_msg.update("⚠ Path does not exist - will be created if needed")
            validation_msg.remove_class("validation-success", "validation-error")
            return
        
        if path_obj.is_file():
            validation_msg.update("✗ Path points to a file, expected directory")
            validation_msg.remove_class("validation-success")
            validation_msg.add_class("validation-error")
            return
        
        # Test regex against actual files in the directory
        if path_obj.is_dir():
            matching_files = []
            all_files = []
            try:
                for file_path in path_obj.rglob("*"):
                    if file_path.is_file():
                        all_files.append(file_path.name)
                        if compiled_regex.search(file_path.name):
                            matching_files.append(file_path.name)
                
                if matching_files:
                    validation_msg.update(f"✓ Found {len(matching_files)} matching files out of {len(all_files)} total")
                    validation_msg.remove_class("validation-error")
                    validation_msg.add_class("validation-success")
                elif all_files:
                    validation_msg.update(f"⚠ No matches found in {len(all_files)} files")
                    validation_msg.remove_class("validation-success", "validation-error")
                else:
                    validation_msg.update("⚠ Directory is empty")
                    validation_msg.remove_class("validation-success", "validation-error")
            except Exception as e:
                validation_msg.update(f"✗ Error scanning directory: {str(e)}")
                validation_msg.remove_class("validation-success")
                validation_msg.add_class("validation-error")
    
    @on(Button.Pressed)
    def handle_workflow_delete(self, event: Button.Pressed) -> None:
        """Handle workflow deletion."""
        button_id = str(event.button.id)
        if button_id.startswith("delete-workflow-"):
            try:
                workflow_idx = int(button_id.split("-")[-1])
                if 0 <= workflow_idx < len(self.wizard_state.workflows):
                    workflow_name = self.wizard_state.workflows[workflow_idx]["name"]
                    # Remove the workflow
                    del self.wizard_state.workflows[workflow_idx]
                    
                    # Update UI
                    self.app.update_preview()
                    self.app.update_step_indicator()
                    self.app.notify(f"Deleted workflow: {workflow_name}")
                    
                    # Refresh this tab to update the workflow list
                    self._refresh_workflow_tab()
                    
                    # Refresh data collection tab to update workflow selection
                    try:
                        dc_tab_pane = self.app.query_one("#data-collections", TabPane)
                        old_dc_step = dc_tab_pane.query_one(DataCollectionStep)
                        old_dc_step.remove()
                        dc_tab_pane.mount(DataCollectionStep(self.wizard_state))
                    except Exception:
                        pass
            except (ValueError, IndexError):
                self.app.notify("Error deleting workflow", severity="error")
    
    def _refresh_workflow_tab(self) -> None:
        """Refresh the workflow tab to show updated workflow list."""
        try:
            # Get current tab pane and rebuild it
            tab_pane = self.parent
            if tab_pane and hasattr(tab_pane, 'mount'):
                # Remove current step and create new one
                self.remove()
                new_step = WorkflowStep(self.wizard_state)
                tab_pane.mount(new_step)
        except Exception:
            pass
    
    @on(Button.Pressed, "#add-workflow")
    def add_workflow(self) -> None:
        """Add a new workflow to the wizard state."""
        workflow_name = self.query_one("#workflow-name", Input).value or "new_workflow"
        
        # Get selected engine
        engine_radio = self.query_one("#workflow-engine", RadioSet)
        engine_name = "python"  # default
        for button in engine_radio.query(RadioButton):
            if button.value:
                engine_name = button.label.plain.lower()
                break
        
        # Get data structure
        structure_radio = self.query_one("#data-structure", RadioSet)
        structure = "flat"  # default
        for button in structure_radio.query(RadioButton):
            if button.value:
                structure = "flat" if button.label.plain == "Flat" else "sequencing-runs"
                break
        
        # Get data location
        data_location = self.query_one("#data-location", Input).value or "./data"
        
        # Get regex pattern
        runs_regex = self.query_one("#runs-regex", Input).value or ".*"
        
        # Validate regex before adding workflow
        if structure == "sequencing-runs":
            try:
                compiled_regex = re.compile(runs_regex)
            except re.error as e:
                self.app.notify(f"Invalid regex pattern: {str(e)}", severity="error")
                return
            
            # For sequencing-runs, validate that regex matches at least one file/folder in data location
            path_obj = Path(data_location)
            if path_obj.exists() and path_obj.is_dir():
                matching_files = []
                try:
                    for file_path in path_obj.rglob("*"):
                        if file_path.is_file() and compiled_regex.search(file_path.name):
                            matching_files.append(file_path.name)
                    
                    if not matching_files:
                        self.app.notify(f"Regex pattern '{runs_regex}' doesn't match any files in '{data_location}'. Please adjust the pattern or validate the combination first.", severity="error")
                        return
                except Exception as e:
                    self.app.notify(f"Error validating regex against files: {str(e)}", severity="error")
                    return
            else:
                # If path doesn't exist, warn but allow (path might be created later)
                self.app.notify(f"Warning: Data location '{data_location}' doesn't exist yet. Ensure the regex pattern is correct when files are available.", severity="warning")
        
        # Create workflow
        workflow = {
            "name": workflow_name,
            "engine": {"name": engine_name},
            "data_location": {
                "structure": structure,
                "locations": [data_location]
            },
            "data_collections": []
        }
        
        # Add runs_regex for sequencing-runs structure
        if structure == "sequencing-runs":
            workflow["data_location"]["runs_regex"] = runs_regex
        
        # Add to wizard state
        self.wizard_state.workflows.append(workflow)
        
        # Clear form
        self.query_one("#workflow-name", Input).value = ""
        self.query_one("#data-location", Input).value = ""
        self.query_one("#runs-regex", Input).value = ""
        self.query_one("#regex-validation", Static).update("")
        self.query_one("#regex-validation", Static).remove_class("validation-success", "validation-error")
        
        # Update preview
        self.app.update_preview()
        self.app.notify(f"Added workflow: {workflow_name}")
        
        # Update step indicator to show workflow count
        self.app.update_step_indicator()
        
        # Refresh this workflow tab to show the new workflow in the management section
        self._refresh_workflow_tab()
        
        # Refresh data collection tab to show updated workflow list
        self._refresh_datacollection_tab_external()
    
    def _refresh_datacollection_tab_external(self) -> None:
        """Refresh data collection tab from workflow step."""
        try:
            # Get the data collections tab pane
            dc_tab_pane = self.app.query_one("#data-collections", TabPane)
            
            # Remove old data collection step and add new one with updated workflows
            old_dc_step = dc_tab_pane.query_one(DataCollectionStep)
            old_dc_step.remove()
            dc_tab_pane.mount(DataCollectionStep(self.wizard_state))
        except Exception:
            pass  # Data collection step not mounted yet


class DataCollectionStep(Container):
    """Step 3: Data Collection Configuration"""
    
    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(**kwargs)
        self.wizard_state = wizard_state
        
    def _create_workflow_selection(self):
        """Create workflow selection as a generator for compose."""
        with RadioSet(id="target-workflow"):
            if self.wizard_state.workflows:
                for i, workflow in enumerate(self.wizard_state.workflows):
                    yield RadioButton(workflow["name"], value=(i == 0), id=f"workflow-{i}")
            else:
                yield RadioButton("No workflows available", value=False, disabled=True)
    
    def refresh_workflow_list(self) -> None:
        """Refresh workflow list by rebuilding the form."""
        # For now, just trigger an update on tab switch
        pass
        
    def compose(self) -> ComposeResult:
        yield Label("Data Collection Configuration", classes="step-title")
        yield Label("Configure data collections for your workflows")
        
        with Vertical(classes="form-container"):
            # Workflow selection dropdown - always fresh
            yield Label("Target Workflow:")
            yield from self._create_workflow_selection()
            
            yield Label("Data Collection Tag:")
            yield Input(placeholder="Enter data collection tag...", id="dc-tag")
            
            yield Label("Description:")
            yield Input(placeholder="Enter description...", id="dc-description")
            
            yield Label("Type:")
            with RadioSet(id="dc-type"):
                yield RadioButton("Table", value=True)
                yield RadioButton("JBrowse2", value=False)
            
            yield Label("Metatype:")
            with RadioSet(id="dc-metatype"):
                yield RadioButton("Metadata", value=True)
                yield RadioButton("Aggregate", value=False)
            
            yield Label("Scan Mode:")
            with RadioSet(id="scan-mode"):
                yield RadioButton("Single File", value=True)
                yield RadioButton("Recursive", value=False)
            
            yield Label("File Pattern/Filename:")
            yield Input(placeholder="*.csv or specific filename", id="file-pattern")
            
            yield Label("Format:")
            with RadioSet(id="file-format"):
                yield RadioButton("CSV", value=True)
                yield RadioButton("TSV", value=False)
                yield RadioButton("Parquet", value=False)
            
            yield Button("Add Data Collection", id="add-datacollection", variant="primary")
            
            # Always show data collection management section
            yield Label("Data Collection Management:", classes="section-title")
            with Vertical(id="existing-datacollections"):
                if self.wizard_state.workflows:
                    has_collections = False
                    for workflow_idx, workflow in enumerate(self.wizard_state.workflows):
                        if workflow["data_collections"]:
                            has_collections = True
                            yield Label(f"In workflow '{workflow['name']}':", classes="workflow-group-label")
                            for dc_idx, dc in enumerate(workflow["data_collections"]):
                                with Horizontal(classes="datacollection-item"):
                                    yield Label(f"  • {dc['data_collection_tag']} ({dc['config']['type']})", classes="datacollection-label")
                                    yield Button("🗑️", id=f"delete-dc-{workflow_idx}-{dc_idx}", variant="error", classes="delete-btn")
                    
                    if not has_collections:
                        yield Label("No data collections added yet", classes="empty-state")
                else:
                    yield Label("Create workflows first to add data collections", classes="empty-state")
            
    @on(Input.Changed)
    def update_dc_data(self, _: Input.Changed) -> None:
        """Update wizard state when data collection inputs change."""
        # Update YAML preview
        self.app.update_preview()
    
    @on(RadioSet.Changed)
    def update_dc_radio(self, _: RadioSet.Changed) -> None:
        """Update wizard state when data collection radio selections change."""
        # Update YAML preview
        self.app.update_preview()
    
    @on(Button.Pressed, "#add-datacollection")
    def add_data_collection(self) -> None:
        """Add a new data collection to the wizard state."""
        dc_tag = self.query_one("#dc-tag", Input).value or "new_collection"
        dc_description = self.query_one("#dc-description", Input).value or "Data collection"
        
        # Get selected workflow
        workflow_radio = self.query_one("#target-workflow", RadioSet)
        selected_workflow_idx = None
        for button in workflow_radio.query(RadioButton):
            if button.value and not button.disabled:
                # Extract workflow index from button id
                button_id = str(button.id)
                if button_id.startswith("workflow-"):
                    selected_workflow_idx = int(button_id.split("-")[1])
                break
        
        if selected_workflow_idx is None or not self.wizard_state.workflows:
            self.app.notify("Please select a workflow or create one first", severity="error")
            return
        
        # Get type
        type_radio = self.query_one("#dc-type", RadioSet)
        dc_type = "Table"  # default
        for button in type_radio.query(RadioButton):
            if button.value:
                dc_type = button.label.plain
                break
        
        # Get metatype
        metatype_radio = self.query_one("#dc-metatype", RadioSet)
        metatype = "Metadata"  # default
        for button in metatype_radio.query(RadioButton):
            if button.value:
                metatype = button.label.plain
                break
        
        # Get scan mode
        scan_radio = self.query_one("#scan-mode", RadioSet)
        scan_mode = "single"  # default
        for button in scan_radio.query(RadioButton):
            if button.value:
                scan_mode = "single" if button.label.plain == "Single File" else "recursive"
                break
        
        # Get file pattern
        file_pattern = self.query_one("#file-pattern", Input).value or "*.csv"
        
        # Get format
        format_radio = self.query_one("#file-format", RadioSet)
        file_format = "CSV"  # default
        for button in format_radio.query(RadioButton):
            if button.value:
                file_format = button.label.plain
                break
        
        # Create data collection
        data_collection = {
            "data_collection_tag": dc_tag,
            "description": dc_description,
            "config": {
                "type": dc_type,
                "metatype": metatype,
                "scan": {
                    "mode": scan_mode,
                    "scan_parameters": {}
                },
                "dc_specific_properties": {
                    "format": file_format,
                    "polars_kwargs": {"separator": "," if file_format == "CSV" else "\t"}
                }
            }
        }
        
        # Set scan parameters based on mode
        if scan_mode == "single":
            data_collection["config"]["scan"]["scan_parameters"]["filename"] = file_pattern
        else:
            data_collection["config"]["scan"]["scan_parameters"]["regex_config"] = {"pattern": file_pattern}
        
        # Add to selected workflow
        target_workflow = self.wizard_state.workflows[selected_workflow_idx]
        target_workflow["data_collections"].append(data_collection)
        
        # Clear form
        self.query_one("#dc-tag", Input).value = ""
        self.query_one("#dc-description", Input).value = ""
        self.query_one("#file-pattern", Input).value = ""
        
        # Update preview
        self.app.update_preview()
        workflow_name = target_workflow["name"]
        self.app.notify(f"Added data collection '{dc_tag}' to workflow '{workflow_name}'")
    
    @on(Button.Pressed)
    def handle_datacollection_delete(self, event: Button.Pressed) -> None:
        """Handle data collection deletion."""
        button_id = str(event.button.id)
        if button_id.startswith("delete-dc-"):
            try:
                # Parse workflow_idx and dc_idx from button ID: delete-dc-{workflow_idx}-{dc_idx}
                parts = button_id.split("-")
                workflow_idx = int(parts[2])
                dc_idx = int(parts[3])
                
                if (0 <= workflow_idx < len(self.wizard_state.workflows) and 
                    0 <= dc_idx < len(self.wizard_state.workflows[workflow_idx]["data_collections"])):
                    
                    workflow = self.wizard_state.workflows[workflow_idx]
                    dc_tag = workflow["data_collections"][dc_idx]["data_collection_tag"]
                    
                    # Remove the data collection
                    del workflow["data_collections"][dc_idx]
                    
                    # Update UI
                    self.app.update_preview()
                    self.app.notify(f"Deleted data collection: {dc_tag}")
                    
                    # Refresh this tab to update the data collection list
                    self._refresh_datacollection_tab()
                    
            except (ValueError, IndexError):
                self.app.notify("Error deleting data collection", severity="error")
    
    def _refresh_datacollection_tab(self) -> None:
        """Refresh the data collection tab to show updated list."""
        try:
            # Get current tab pane and rebuild it
            tab_pane = self.parent
            if tab_pane and hasattr(tab_pane, 'mount'):
                # Remove current step and create new one
                self.remove()
                new_step = DataCollectionStep(self.wizard_state)
                tab_pane.mount(new_step)
        except Exception:
            pass


class YAMLPreview(Container):
    """YAML Preview Panel"""
    
    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(**kwargs)
        self.wizard_state = wizard_state
        
    def compose(self) -> ComposeResult:
        with Horizontal(classes="yaml-header"):
            yield Label("YAML Configuration", classes="preview-title")
            yield Button("📝 Edit", id="toggle-edit", variant="default", classes="edit-toggle-btn")
            yield Button("💾 Apply Changes", id="apply-yaml", variant="success", classes="apply-btn", disabled=True)
        
        yield TextArea(
            text=self.wizard_state.to_yaml(),
            read_only=True,
            id="yaml-preview",
            language="yaml"
        )
        yield Static("", id="yaml-validation", classes="validation-message")
        
    def update_preview(self) -> None:
        """Update the YAML preview with current wizard state."""
        yaml_text = self.wizard_state.to_yaml()
        try:
            preview = self.query_one("#yaml-preview", TextArea)
            if preview.read_only:  # Only update if not in edit mode
                preview.text = yaml_text
        except Exception:
            # Preview widget might not be ready yet
            pass
    
    @on(Button.Pressed, "#toggle-edit")
    def toggle_edit_mode(self) -> None:
        """Toggle between read-only and edit mode for YAML."""
        try:
            preview = self.query_one("#yaml-preview", TextArea)
            toggle_btn = self.query_one("#toggle-edit", Button)
            apply_btn = self.query_one("#apply-yaml", Button)
            validation_msg = self.query_one("#yaml-validation", Static)
            
            if preview.read_only:
                # Switch to edit mode
                preview.read_only = False
                toggle_btn.label = "👁️ View"
                apply_btn.disabled = False
                validation_msg.update("📝 Edit mode - make changes and click Apply")
                validation_msg.remove_class("validation-success", "validation-error")
            else:
                # Switch back to read-only mode
                preview.read_only = True
                toggle_btn.label = "📝 Edit"
                apply_btn.disabled = True
                validation_msg.update("")
                validation_msg.remove_class("validation-success", "validation-error")
                # Refresh preview with current wizard state
                self.update_preview()
        except Exception as e:
            self.app.notify(f"Error toggling edit mode: {str(e)}", severity="error")
    
    @on(Button.Pressed, "#apply-yaml")
    def apply_yaml_changes(self) -> None:
        """Apply YAML changes back to wizard state."""
        try:
            preview = self.query_one("#yaml-preview", TextArea)
            validation_msg = self.query_one("#yaml-validation", Static)
            
            yaml_content = preview.text
            
            # Validate YAML syntax
            try:
                parsed_yaml = yaml.safe_load(yaml_content)
            except yaml.YAMLError as e:
                validation_msg.update(f"✗ Invalid YAML: {str(e)}")
                validation_msg.remove_class("validation-success")
                validation_msg.add_class("validation-error")
                return
            
            # Update wizard state from parsed YAML
            try:
                self.wizard_state.load_from_dict(parsed_yaml)
                validation_msg.update("✓ YAML applied successfully")
                validation_msg.remove_class("validation-error")
                validation_msg.add_class("validation-success")
                
                # Refresh all tabs to reflect changes
                self._refresh_all_tabs()
                
                self.app.notify("YAML changes applied successfully")
            except Exception as e:
                validation_msg.update(f"✗ Error applying YAML: {str(e)}")
                validation_msg.remove_class("validation-success")
                validation_msg.add_class("validation-error")
                
        except Exception as e:
            self.app.notify(f"Error applying YAML: {str(e)}", severity="error")
    
    def _refresh_all_tabs(self) -> None:
        """Refresh all tabs to reflect YAML changes."""
        try:
            # Refresh workflow tab
            workflow_tab_pane = self.app.query_one("#workflows", TabPane)
            old_workflow_step = workflow_tab_pane.query_one(WorkflowStep)
            old_workflow_step.remove()
            workflow_tab_pane.mount(WorkflowStep(self.wizard_state))
            
            # Refresh data collection tab
            dc_tab_pane = self.app.query_one("#data-collections", TabPane)
            old_dc_step = dc_tab_pane.query_one(DataCollectionStep)
            old_dc_step.remove()
            dc_tab_pane.mount(DataCollectionStep(self.wizard_state))
            
            # Update step indicator
            self.app.update_step_indicator()
            
        except Exception:
            pass


class LandingScreen(Container):
    """Landing screen with welcome message and options."""
    
    def compose(self) -> ComposeResult:
        with Vertical(id="landing-container"):
            yield Static("", id="top-spacer")
            yield Static("🎨 DEPICTIO PROJECT WIZARD", id="title")
            yield Static("Create and configure Depictio projects with ease", id="subtitle")
            yield Static("", id="middle-spacer")
            
            with Vertical(id="button-container"):
                yield Button("📝 Create New Project", id="new-project")
                yield Static("", id="button-spacer")
                yield Button("📂 Edit Existing Project", id="edit-project")
                yield Static("", id="button-spacer2")
                yield Button("❌ Exit", id="exit-landing", variant="error")
            
            yield Static("", id="bottom-spacer")


class MainWizardInterface(Container):
    """Main wizard interface with project info, workflows, and data collections."""
    
    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(**kwargs)
        self.wizard_state = wizard_state
    
    def compose(self) -> ComposeResult:
        # Project Information Section
        yield Label("📋 Project Configuration", classes="section-title")
        with Container(classes="project-section"):
            yield Label("Project Name:")
            yield Input(
                value=self.wizard_state.project_data.get("name", ""),
                placeholder="Enter project name...",
                id="project-name"
            )
            
            yield Label("Project Type:")
            with RadioSet(id="project-type"):
                # Default to "basic" if no project type is set
                project_type = self.wizard_state.project_data.get("project_type", "basic")
                yield RadioButton("Basic", value=(project_type == "basic"))
                yield RadioButton("Advanced", value=(project_type == "advanced"))
            
            yield Label("Data Management Platform URL (optional):")
            yield Input(
                value=self.wizard_state.project_data.get("data_management_platform_project_url", ""),
                placeholder="https://example.com/project/...",
                id="project-url"
            )
        
        # Workflow Management Section
        yield Label("⚙️ Workflow Management", classes="section-title")
        with Container(classes="workflow-section"):
            yield Button("➕ Add Workflow", id="add-workflow-btn", variant="primary")
            
            # Workflow list container
            with Container(id="workflows-container", classes="workflows-list"):
                if not self.wizard_state.workflows:
                    yield Static("No workflows yet. Click 'Add Workflow' to create one!", classes="empty-state")
                else:
                    for i, workflow in enumerate(self.wizard_state.workflows):
                        with Container(classes="workflow-item"):
                            # Workflow header with info
                            engine_name = self._get_engine_name(workflow)
                            dc_count = len(workflow.get('data_collections', []))
                            
                            yield Label(f"🔧 {workflow['name']} ({engine_name}) - {dc_count} data collection{'s' if dc_count != 1 else ''}", classes="workflow-label")
                            
                            # Workflow actions
                            with Horizontal(classes="workflow-actions"):
                                yield Button("📊 Add Data Collection", id=f"add-dc-{i}", variant="success")
                                yield Button("🗑️ Delete", id=f"delete-workflow-{i}", variant="error")
                            
                            # Data collections list for this workflow
                            if workflow.get('data_collections'):
                                with Container(classes="dc-list"):
                                    for j, dc in enumerate(workflow['data_collections']):
                                        dc_name = dc.get('data_collection_tag', dc.get('name', 'Unknown'))
                                        dc_type = self._get_dc_type(dc)
                                        with Horizontal(classes="dc-item"):
                                            yield Label(f"  📊 {dc_name} ({dc_type})", classes="dc-label")
                                            yield Button("🗑️", id=f"delete-dc-{i}-{j}", classes="delete-btn-small")
    
    
    def _get_engine_name(self, workflow: dict) -> str:
        """Extract engine name from workflow."""
        if 'engine' in workflow:
            if isinstance(workflow['engine'], dict):
                return workflow['engine'].get('name', 'python')
            else:
                return workflow['engine']
        return 'python'
    
    def _get_dc_type(self, dc: dict) -> str:
        """Extract data collection type."""
        if 'type' in dc:
            return dc['type']
        elif 'config' in dc and 'type' in dc['config']:
            return dc['config']['type']
        return 'table'
    
    
    @on(Input.Changed, "#project-name")
    def project_name_changed(self, event: Input.Changed) -> None:
        """Handle project name changes."""
        self.wizard_state.project_data["name"] = event.value
        self.app.update_preview()
    
    @on(Input.Changed, "#project-url")
    def project_url_changed(self, event: Input.Changed) -> None:
        """Handle project URL changes."""
        self.wizard_state.project_data["data_management_platform_project_url"] = event.value
        self.app.update_preview()
    
    @on(RadioSet.Changed, "#project-type")
    def project_type_changed(self, event: RadioSet.Changed) -> None:
        """Handle project type changes."""
        if event.pressed and event.pressed.label:
            project_type = "basic" if event.pressed.label.plain == "Basic" else "advanced"
            self.wizard_state.project_data["project_type"] = project_type
            self.app.update_preview()
    
    @on(Button.Pressed, "#add-workflow-btn")
    def open_workflow_modal(self) -> None:
        """Open the modal to create a new workflow."""
        self.app.notify("Opening workflow modal...", severity="info")
        
        def handle_workflow_result(result: dict | None) -> None:
            if result:
                self.wizard_state.workflows.append(result)
                # Notify the main app to refresh the entire interface
                self.app.refresh_main_interface()
                self.app.notify(f"Added workflow: {result['name']}", severity="success")
            else:
                self.app.notify("Workflow creation cancelled", severity="info")
        
        self.app.push_screen(WorkflowModal(), handle_workflow_result)
    
    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed) -> None:
        """Handle various button presses."""
        button_id = str(event.button.id) if event.button.id else ""
        
        if not button_id:
            return
        
        # Handle add data collection buttons
        if button_id.startswith("add-dc-"):
            try:
                workflow_index = int(button_id.split("-")[-1])
                self.app.notify(f"Adding data collection to workflow {workflow_index}...", severity="info")
                
                if workflow_index < len(self.wizard_state.workflows):
                    workflow = self.wizard_state.workflows[workflow_index]
                    workflow_name = workflow['name']
                    
                    def handle_dc_result(result: dict | None) -> None:
                        if result:
                            workflow['data_collections'].append(result)
                            self.app.refresh_main_interface()
                            self.app.notify(f"Added data collection to {workflow_name}", severity="success")
                        else:
                            self.app.notify("Data collection creation cancelled", severity="info")
                    
                    self.app.push_screen(DataCollectionModal(workflow_name), handle_dc_result)
                else:
                    self.app.notify(f"Invalid workflow index: {workflow_index}", severity="error")
            except (ValueError, IndexError) as e:
                self.app.notify(f"Error adding data collection: {str(e)}", severity="error")
        
        # Handle workflow deletion
        elif button_id.startswith("delete-workflow-"):
            try:
                workflow_index = int(button_id.split("-")[-1])
                if workflow_index < len(self.wizard_state.workflows):
                    workflow_name = self.wizard_state.workflows[workflow_index]["name"]
                    del self.wizard_state.workflows[workflow_index]
                    self.app.refresh_main_interface()
                    self.app.notify(f"Deleted workflow: {workflow_name}", severity="success")
            except (ValueError, IndexError) as e:
                self.app.notify(f"Error deleting workflow: {str(e)}", severity="error")
        
        # Handle data collection deletion
        elif button_id.startswith("delete-dc-"):
            try:
                parts = button_id.split("-")
                if len(parts) >= 4:
                    workflow_index = int(parts[-2])
                    dc_index = int(parts[-1])
                    
                    if (workflow_index < len(self.wizard_state.workflows) and 
                        dc_index < len(self.wizard_state.workflows[workflow_index]["data_collections"])):
                        
                        workflow = self.wizard_state.workflows[workflow_index]
                        dc_name = workflow["data_collections"][dc_index].get("data_collection_tag", "Unknown")
                        del workflow["data_collections"][dc_index]
                        
                        self.app.refresh_main_interface()
                        self.app.notify(f"Deleted data collection: {dc_name}", severity="success")
            except (ValueError, IndexError) as e:
                self.app.notify(f"Error deleting data collection: {str(e)}", severity="error")


class WizardApp(App):
    """Main Wizard Application"""
    
    ENABLE_COMMAND_PALETTE = True  # Enable command palette for theme access
    
    def __init__(self, yaml_file: Optional[Path] = None, template: Optional[str] = None):
        super().__init__()
        self.wizard_state = WizardState()
        self.show_landing = yaml_file is None and template is None  # Show landing if no file/template provided
        
        # Load existing file if provided
        if yaml_file and yaml_file.exists():
            self.wizard_state.load_from_yaml(yaml_file)
            
        # Load template if provided
        elif template:
            self.load_template(template)
    
    CSS = """
    /* Landing Screen Styles */
    LandingScreen {
        align: center middle;
    }
    
    #landing-container {
        width: auto;
        height: auto;
        align: center middle;
    }
    
    #title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 1 0;
        width: 100%;
    }
    
    #subtitle {
        text-align: center;
        color: $text-muted;
        margin: 1 0;
        width: 100%;
    }
    
    #button-container {
        width: auto;
        align: center middle;
    }
    
    #button-container Button {
        width: 25;
        margin: 1 0;
    }
    
    #top-spacer, #middle-spacer, #bottom-spacer {
        height: 2;
    }
    
    #button-spacer, #button-spacer2 {
        height: 1;
    }
    
    /* Main Wizard Styles */
    #step-indicator {
        dock: top;
        height: 3;
        text-align: center;
        text-style: bold;
        background: $surface;
        padding: 1;
    }
    
    .navigation {
        dock: bottom;
        height: 3;
        background: $surface;
        padding: 0 1;
    }
    
    #main-container {
        layout: horizontal;
        height: 100%;
    }
    
    #left-panel {
        width: 3fr;
        height: 100%;
        overflow-y: scroll;
        scrollbar-size: 1 1;
        scrollbar-background: $surface;
        scrollbar-color: $primary;
        border-right: solid $primary;
        padding: 1;
    }
    
    MainWizardInterface {
        height: auto;
        min-height: 100%;
    }
    
    #right-panel {
        width: 2fr;
        height: 100%;
        padding: 1;
    }
    
    /* Section Styles */
    .section-title {
        text-style: bold;
        margin: 0 0 1 0;
        color: $primary;
        background: $surface;
        padding: 1;
        text-align: center;
    }
    
    .project-section {
        border: solid $primary;
        padding: 1;
        margin: 0 0 2 0;
        background: $surface;
        height: auto;
    }
    
    .workflow-section {
        border: solid $secondary;
        padding: 1;
        margin: 0 0 2 0;
        background: $surface;
        height: auto;
        min-height: 20;
    }
    
    /* Workflow List Styles */
    .workflows-list {
        margin: 1 0;
        height: auto;
        min-height: 15;
    }
    
    #workflows-container {
        height: auto;
        min-height: 10;
    }
    
    .workflow-item {
        border: solid $primary;
        margin: 0 0 1 0;
        padding: 1;
        background: $panel;
        height: auto;
        min-height: 8;
    }
    
    .workflow-label {
        text-style: bold;
        margin: 0 0 1 0;
        color: $text;
    }
    
    .workflow-actions {
        height: auto;
        min-height: 3;
        margin: 1 0;
    }
    
    .workflow-actions Button {
        margin: 0 1 0 0;
    }
    
    /* Data Collection Styles */
    .dc-list {
        margin: 1 0 0 0;
        border-top: solid $accent;
        padding: 1 0 0 0;
        height: auto;
    }
    
    .dc-item {
        height: auto;
        min-height: 3;
        margin: 0 0 1 0;
        padding: 0 1;
        background: $surface;
        border: solid $accent;
    }
    
    .dc-label {
        width: 1fr;
    }
    
    .delete-btn-small {
        width: 3;
        min-width: 3;
        margin: 0;
        background: $error;
    }
    
    /* Modal Styles */
    #modal-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: solid $primary;
        background: $surface;
        padding: 2;
        overflow-y: auto;
        align: center middle;
    }
    
    #modal-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 0 0 2 0;
    }
    
    #modal-buttons {
        height: 3;
        margin: 2 0 0 0;
    }
    
    #modal-buttons Button {
        width: 1fr;
        margin: 0 1;
    }
    
    /* Regex field visibility */
    #regex-container.hidden {
        height: 0;
        max-height: 0;
        overflow: hidden;
        visibility: hidden;
    }
    
    /* General Styles */
    Button {
        margin: 0 1;
        min-width: 8;
    }
    
    .empty-state {
        color: $text-muted;
        text-style: italic;
        margin: 2 0;
        padding: 1;
        text-align: center;
    }
    
    .validation-message {
        height: 1;
        text-align: center;
        margin: 1 0;
    }
    
    .validation-success {
        color: $success;
    }
    
    .validation-error {
        color: $error;
    }
    
    /* YAML Preview Styles */
    .yaml-header {
        dock: top;
        height: 3;
        background: $surface;
        padding: 0 1;
    }
    
    .preview-title {
        width: 24;
        text-style: bold;
    }
    
    .edit-toggle-btn {
        width: 12;
        min-width: 12;
        margin: 0 0 0 1;
    }
    .apply-btn {
        width: 22;
        min-width: 22;
        margin: 0 0 0 1;
    }
    
    #yaml-preview {
        dock: bottom;
        height: 1fr;
        border: solid $primary;
    }
    
    #yaml-preview-container {
        height: 100%;
        layout: vertical;
    }
    
    """
    
    
    def compose(self) -> ComposeResult:
        if self.show_landing:
            # Show landing screen
            yield LandingScreen(id="landing-screen")
        else:
            # Show wizard interface
            yield from self.compose_wizard()
    
    def compose_wizard(self) -> ComposeResult:
        """Compose the main wizard interface."""
        # Step indicator with Depictio branding
        yield Static("🎨 DEPICTIO Project Wizard", id="step-indicator", classes="step-indicator")
        
        # Main content area
        with Horizontal(id="main-container"):
            # Left panel - main interface
            with Container(id="left-panel"):
                yield MainWizardInterface(self.wizard_state)
            
            # Right panel - YAML preview
            with Container(id="right-panel"):
                yield YAMLPreview(self.wizard_state, id="yaml-preview-container")
        
        # Navigation
        with Horizontal(classes="navigation"):
            yield Button("💾 Save YAML", id="save-btn", variant="success")
            yield Button("❌ Exit", id="exit-btn", variant="error")
    
    def on_ready(self) -> None:
        """Called when the app is ready and all widgets are mounted."""
        if not self.show_landing:
            # Initial preview update
            self.update_preview()
    
    def refresh_main_interface(self) -> None:
        """Refresh the main wizard interface."""
        try:
            # Find the left panel and refresh its contents
            left_panel = self.query_one("#left-panel")
            # Remove current main interface
            old_interface = left_panel.query_one(MainWizardInterface)
            old_interface.remove()
            # Mount new interface
            new_interface = MainWizardInterface(self.wizard_state)
            left_panel.mount(new_interface)
            # Force a refresh after mounting
            self.call_after_refresh(self.update_preview)
        except Exception as e:
            self.notify(f"Error refreshing interface: {str(e)}", severity="error")
    
    async def switch_to_wizard(self) -> None:
        """Switch from landing screen to wizard interface."""
        self.show_landing = False
        # Clear and recompose
        await self.recompose()
        # Initialize wizard after recompose
        self.call_after_refresh(self.on_ready)
    
    # Landing screen event handlers
    @on(Button.Pressed, "#new-project")
    async def start_new_project(self) -> None:
        """Start creating a new project."""
        await self.switch_to_wizard()
    
    
    @on(Button.Pressed, "#edit-project")
    async def start_edit_project(self) -> None:
        """Start editing an existing project (placeholder)."""
        self.notify("File dialog would open here - for now, starting new project")
        await self.switch_to_wizard()
    
    @on(Button.Pressed, "#exit-landing")
    def exit_from_landing(self) -> None:
        """Exit from landing screen."""
        self.exit()
    
    
    @on(Button.Pressed, "#save-btn")
    def save_yaml(self) -> None:
        """Save the current configuration to YAML file."""
        yaml_content = self.wizard_state.to_yaml()
        
        # For now, save to a default filename
        output_file = Path("depictio_project.yaml")
        with open(output_file, 'w') as f:
            f.write(yaml_content)
        
        self.notify(f"YAML saved to {output_file}")
    
    @on(Button.Pressed, "#exit-btn")
    def exit_app(self) -> None:
        """Exit the application."""
        self.exit()
    
    def update_step_indicator(self, text: str = None) -> None:
        """Update the step indicator text."""
        if text is None:
            # Auto-generate based on current state
            workflow_count = len(self.wizard_state.workflows)
            project_name = self.wizard_state.project_data.get("name", "Unnamed Project")
            
            if workflow_count == 0:
                text = f"{project_name} (No workflows)"
            else:
                text = f"{project_name} ({workflow_count} workflow{'s' if workflow_count != 1 else ''})"
        
        try:
            indicator = self.query_one("#step-indicator", Static)
            indicator.update(f"🎨 DEPICTIO Project Wizard - {text}")
        except Exception:
            # Indicator might not exist yet
            pass
    
    def update_preview(self) -> None:
        """Update the YAML preview."""
        try:
            preview_container = self.query_one("#yaml-preview-container", YAMLPreview)
            preview_container.update_preview()
        except Exception:
            # Preview container might not be ready yet
            pass
    
    def load_template(self, template: str) -> None:
        """Load a predefined template."""
        templates = {
            "iris": {
                "name": "Iris Dataset Project",
                "project_type": "basic",
                "workflows": [{
                    "name": "iris_workflow",
                    "engine": {"name": "python"},
                    "data_location": {
                        "structure": "flat",
                        "locations": ["./data/iris"]
                    },
                    "data_collections": [{
                        "data_collection_tag": "iris_table",
                        "description": "Iris dataset in CSV format",
                        "config": {
                            "type": "Table",
                            "metatype": "Metadata",
                            "scan": {
                                "mode": "single",
                                "scan_parameters": {"filename": "iris.csv"}
                            },
                            "dc_specific_properties": {
                                "format": "CSV",
                                "polars_kwargs": {"separator": ","}
                            }
                        }
                    }]
                }]
            },
            "penguins": {
                "name": "Palmer Penguins Species Comparison",
                "project_type": "advanced",
                "workflows": [{
                    "name": "penguin_species_analysis",
                    "engine": {"name": "python", "version": "3.11"},
                    "description": "Comparative analysis of Palmer Archipelago penguin species",
                    "data_location": {
                        "structure": "sequencing-runs",
                        "runs_regex": "run_*",
                        "locations": ["./data/penguins"]
                    },
                    "data_collections": [
                        {
                            "data_collection_tag": "physical_features",
                            "description": "Physical characteristics measurements",
                            "config": {
                                "type": "Table",
                                "metatype": "Aggregate",
                                "scan": {
                                    "mode": "recursive",
                                    "scan_parameters": {
                                        "regex_config": {"pattern": "physical_features.csv"}
                                    }
                                },
                                "dc_specific_properties": {
                                    "format": "CSV",
                                    "polars_kwargs": {"separator": ","}
                                }
                            }
                        }
                    ]
                }]
            }
        }
        
        if template in templates:
            data = templates[template]
            self.wizard_state.project_data.update({
                "name": data["name"],
                "project_type": data["project_type"]
            })
            self.wizard_state.workflows = data.get("workflows", [])


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Depictio Project Wizard")
    parser.add_argument("--edit", type=Path, help="Edit existing YAML file")
    parser.add_argument("--template", choices=["iris", "penguins"], help="Start with template")
    
    args = parser.parse_args()
    
    app = WizardApp(yaml_file=args.edit, template=args.template)
    app.run()


if __name__ == "__main__":
    main()