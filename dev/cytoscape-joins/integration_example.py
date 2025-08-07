#!/usr/bin/env python3
"""
Integration Example: Adding Cytoscape Joins to Project Data Collections

This shows how to integrate the cytoscape joins visualization into the existing
project data collections management interface.
"""

# Example modifications to add to project_data_collections.py

INTEGRATION_CODE = """
# Add to imports section:
from dev.cytoscape_joins.depictio_cytoscape_joins import (
    create_joins_visualization_section,
    register_joins_callbacks,
    generate_sample_elements  # For testing
)

# Add to the layout creation function (around line 900+):
def create_project_data_collections_layout(app):
    # ... existing layout code ...
    
    # Add joins visualization section after data collection viewer
    joins_section = dmc.Stack([
        dmc.Divider(label="Data Collection Relationships", labelPosition="center", my="xl"),
        create_joins_visualization_section(
            elements=[],  # Will be populated by callback
            theme="light"  # Will be updated by theme callback
        )
    ], id="joins-visualization-section", style={"display": "none"})  # Hidden by default
    
    # Register the joins callbacks
    register_joins_callbacks(app)
    
    return dmc.Stack([
        # ... existing sections ...
        joins_section  # Add at the end
    ])

# Add callback to show/hide joins section based on data collections:
@app.callback(
    [Output("joins-visualization-section", "style"),
     Output("depictio-cytoscape-joins", "elements")],
    [Input("project-data-store", "data"),
     Input("selected-workflow-store", "data")],
    prevent_initial_call=True
)
def update_joins_visualization(project_data, selected_workflow_id):
    '''Update joins visualization based on project data.'''
    
    if not project_data:
        return {"display": "none"}, []
    
    # Get data collections from project
    data_collections = []
    
    if project_data.get("project_type") == "basic":
        # Basic projects: use flattened data collections
        data_collections = project_data.get("data_collections", [])
    else:
        # Advanced projects: use selected workflow's data collections
        if selected_workflow_id:
            workflows = project_data.get("workflows", [])
            selected_workflow = next(
                (w for w in workflows if str(w.get("id")) == selected_workflow_id),
                None
            )
            if selected_workflow:
                data_collections = selected_workflow.get("data_collections", [])
    
    # Generate cytoscape elements from data collections
    elements = []
    if data_collections:
        # Check if any data collections have joins
        has_joins = any(
            dc.get("config", {}).get("join") is not None
            for dc in data_collections
        )
        
        if has_joins:
            # Generate elements from real data
            elements = generate_cytoscape_elements_from_project_data(data_collections)
            return {"display": "block"}, elements
        else:
            # Show sample for demonstration
            elements = generate_sample_elements()
            return {"display": "block"}, elements
    
    return {"display": "none"}, []

def generate_cytoscape_elements_from_project_data(data_collections):
    '''Convert project data collections to cytoscape elements.'''
    elements = []
    
    # Create data collection groups and column nodes
    for i, dc in enumerate(data_collections):
        dc_id = dc.get("id", f"dc_{i}")
        dc_tag = dc.get("data_collection_tag", f"DC_{i}")
        dc_type = dc.get("config", {}).get("type", "table")
        dc_metatype = dc.get("config", {}).get("metatype", "unknown")
        
        if dc_type.lower() != "table":
            continue  # Skip non-table collections
        
        # Create data collection group
        elements.append({
            "data": {
                "id": f"dc_group_{dc_id}",
                "label": f"{dc_tag}\\n[{dc_metatype}]",
                "type": "data_collection",
                "dc_id": dc_id,
                "dc_tag": dc_tag
            },
            "position": {"x": i * 200 + 100, "y": 100},
            "classes": "data-collection-group"
        })
        
        # Get column information (this would need to be fetched from delta tables API)
        # For now, use placeholder columns
        columns = ["id", "name", "created_at"]  # Placeholder
        
        # Create column nodes
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}_{column}"
            
            # Check if this column is part of a join
            join_config = dc.get("config", {}).get("join")
            is_join_column = (
                join_config and 
                column in join_config.get("on_columns", [])
            )
            
            elements.append({
                "data": {
                    "id": column_id,
                    "label": column,
                    "parent": f"dc_group_{dc_id}",
                    "type": "column",
                    "dc_tag": dc_tag,
                    "dc_id": dc_id,
                    "is_join_column": is_join_column
                },
                "position": {"x": i * 200 + 100, "y": 140 + j * 30},
                "classes": "column-node join-column" if is_join_column else "column-node"
            })
        
        # Create join edges
        if join_config:
            on_columns = join_config.get("on_columns", [])
            join_type = join_config.get("how", "inner")
            target_dc_tags = join_config.get("with_dc", [])
            
            for target_dc_tag in target_dc_tags:
                for col in on_columns:
                    source_node = f"{dc_tag}_{col}"
                    target_node = f"{target_dc_tag}_{col}"  # Assume same column name
                    
                    elements.append({
                        "data": {
                            "id": f"join_{dc_tag}_{target_dc_tag}_{col}",
                            "source": source_node,
                            "target": target_node,
                            "label": join_type,
                            "join_type": join_type
                        },
                        "classes": f"join-edge join-{join_type}"
                    })
    
    return elements
"""

def print_integration_steps():
    """Print step-by-step integration instructions."""
    print("🔧 Depictio Cytoscape Joins Integration Steps")
    print("=" * 50)
    print()
    
    print("1. 📂 Copy the module:")
    print("   cp dev/cytoscape-joins/depictio_cytoscape_joins.py depictio/dash/components/")
    print()
    
    print("2. 📝 Import in project_data_collections.py:")
    print("   from depictio.dash.components.depictio_cytoscape_joins import (")
    print("       create_joins_visualization_section,")
    print("       register_joins_callbacks")
    print("   )")
    print()
    
    print("3. 🏗️  Add to layout (in register_project_data_collections_page):")
    print("   # After the data collection viewer section:")
    print("   joins_section = create_joins_visualization_section()")
    print("   layout.append(joins_section)")
    print()
    
    print("4. 🔗 Register callbacks (in register_project_data_collections_page):")
    print("   register_joins_callbacks(app)")
    print()
    
    print("5. 📊 Add visibility callback:")
    print("   # Add callback to show/hide based on joins existence")
    print("   # See integration_example.py for full callback code")
    print()
    
    print("6. 🎨 Theme integration:")
    print("   # Update theme in existing theme callback")
    print("   # Add Output('depictio-cytoscape-joins', 'stylesheet')")
    print()
    
    print("7. ✅ Test integration:")
    print("   # Visit project data collections page with joins")
    print("   # Verify visualization appears and works correctly")
    print()
    
    print("🎯 Features integrated:")
    print("  - Interactive network visualization")
    print("  - Theme-aware styling")
    print("  - Selection details panel")
    print("  - Layout controls (fit view, reset)")
    print("  - Automatic show/hide based on joins")
    print()
    
    print("📋 Integration checklist:")
    print("  □ Module copied to components directory")
    print("  □ Imports added to project_data_collections.py")
    print("  □ Layout section added")
    print("  □ Callbacks registered")
    print("  □ Visibility callback implemented") 
    print("  □ Theme integration completed")
    print("  □ Testing completed")


if __name__ == "__main__":
    print_integration_steps()
    print()
    print("📖 Full integration code example:")
    print("-" * 40)
    print(INTEGRATION_CODE)