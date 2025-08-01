#!/usr/bin/env python3
"""
Test script for the Depictio Cytoscape Joins Integration

Run this to test the integration with real Depictio data.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from depictio_joins_integration import (
    create_joins_visualization_data,
    fetch_project_data_collections_with_joins,
)


async def test_integration():
    """Test the integration with sample data."""
    
    # Replace with actual project ID and token for testing
    # You can get these from your development environment
    project_id = "646b0f3c1e4a2d7f8e5b8c9a"  # Sample project ID
    token = "your-auth-token-here"  # Replace with real token
    
    print("🔍 Testing Depictio Cytoscape Joins Integration")
    print(f"Project ID: {project_id}")
    print()
    
    try:
        # Test fetching project data
        print("1. Fetching project data collections...")
        project_data = await fetch_project_data_collections_with_joins(project_id, token)
        
        if not project_data:
            print("❌ Failed to fetch project data")
            print("Make sure you have:")
            print("- Valid project ID")
            print("- Valid authentication token")
            print("- Running Depictio API server")
            return
        
        print(f"✅ Successfully fetched project: {project_data['project']['name']}")
        print(f"   - Type: {project_data['project']['type']}")
        print(f"   - Data Collections: {len(project_data['data_collections'])}")
        print(f"   - Workflows: {len(project_data['workflows'])}")
        print()
        
        # Display data collections info
        print("2. Data Collections Overview:")
        for dc in project_data['data_collections']:
            joins_count = len(dc.get('joins', []))
            columns_count = len(dc.get('columns', []))
            workflow_info = f" (Workflow: {dc.get('workflow_name', 'N/A')})" if dc.get('workflow_name') else ""
            print(f"   - {dc['name']}: {columns_count} columns, {joins_count} joins{workflow_info}")
        print()
        
        # Test cytoscape visualization generation
        print("3. Generating cytoscape visualization...")
        viz_data = await create_joins_visualization_data(project_id, token, "light")
        
        if viz_data.get('metadata', {}).get('error'):
            print(f"❌ Error: {viz_data['metadata']['error']}")
            return
        
        elements_count = len(viz_data['elements'])
        nodes_count = len([e for e in viz_data['elements'] if 'source' not in e['data']])
        edges_count = len([e for e in viz_data['elements'] if 'source' in e['data']])
        
        print(f"✅ Successfully generated visualization:")
        print(f"   - Total elements: {elements_count}")
        print(f"   - Nodes: {nodes_count}")
        print(f"   - Edges: {edges_count}")
        print(f"   - Stylesheet rules: {len(viz_data['stylesheet'])}")
        print()
        
        # Display join relationships
        print("4. Join Relationships Found:")
        joins_found = [e for e in viz_data['elements'] if e['data'].get('join_type')]
        if joins_found:
            for join in joins_found:
                source = join['data']['source']
                target = join['data']['target']
                join_type = join['data']['join_type']
                column = join['data'].get('join_column', 'unknown')
                print(f"   - {source} --[{join_type}]--> {target} (on: {column})")
        else:
            print("   - No join relationships found")
        print()
        
        print("🎉 Integration test completed successfully!")
        print()
        print("Next steps:")
        print("- Update project_id and token with real values")
        print("- Run the full prototype with: python cytoscape_joins_prototype.py")
        print("- Integrate into the main Depictio interface")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()


def print_sample_usage():
    """Print sample usage information."""
    print("📖 Sample Usage in Depictio Interface:")
    print()
    print("```python")
    print("# In your Dash callback:")
    print("@callback(")
    print("    Output('cytoscape-joins', 'elements'),")
    print("    Input('project-selector', 'value')")
    print(")")
    print("async def update_joins_visualization(project_id):")
    print("    if not project_id:")
    print("        return []")
    print("    ")
    print("    # Get auth token from session")
    print("    token = get_current_user_token()")
    print("    ")
    print("    # Generate visualization data")
    print("    viz_data = await create_joins_visualization_data(")
    print("        project_id, token, theme='light'")
    print("    )")
    print("    ")
    print("    return viz_data['elements']")
    print("```")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--usage":
        print_sample_usage()
    else:
        # Run the test
        asyncio.run(test_integration())