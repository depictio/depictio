#!/usr/bin/env python3
"""
Test to examine component serialization and ID handling differences
"""

import uuid
import dash
from dash import html
import dash_draggable
import json
import pprint

def generate_unique_index():
    return str(uuid.uuid4())

def test_serialization():
    print(f"=== Dash {dash.__version__} Component Serialization Test ===")
    
    # Generate UUIDs
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    custom_id1 = f"box-{uuid1}"
    custom_id2 = f"box-{uuid2}"
    
    print(f"UUID 1: {uuid1}")
    print(f"UUID 2: {uuid2}")
    print(f"Custom ID 1: {custom_id1}")
    print(f"Custom ID 2: {custom_id2}")
    
    # Create children with custom IDs
    children = [
        html.Div(
            id=custom_id1,
            children=[html.H3("Component 1"), html.P(f"ID: {custom_id1}")],
        ),
        html.Div(
            id=custom_id2,
            children=[html.H3("Component 2"), html.P(f"ID: {custom_id2}")],
        )
    ]
    
    # Create layout with custom IDs
    layout = {
        "lg": [
            {"i": custom_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": custom_id2, "x": 6, "y": 0, "w": 6, "h": 4}
        ]
    }
    
    print("\n=== BEFORE ResponsiveGridLayout Creation ===")
    print("Children IDs:")
    for i, child in enumerate(children):
        print(f"  Child {i}: id = {child.id}")
    
    print("\nLayout:")
    pprint.pprint(layout)
    
    # Create ResponsiveGridLayout
    grid = dash_draggable.ResponsiveGridLayout(
        id="test-grid",
        children=children,
        layouts=layout,
        isDraggable=True,
        isResizable=True,
        save=False
    )
    
    print("\n=== AFTER ResponsiveGridLayout Creation ===")
    print(f"Grid ID: {grid.id}")
    print(f"Grid children count: {len(grid.children) if grid.children else 0}")
    
    if grid.children:
        print("Grid children IDs:")
        for i, child in enumerate(grid.children):
            if hasattr(child, 'id'):
                print(f"  Child {i}: id = {child.id}")
            else:
                print(f"  Child {i}: no id attribute")
    
    print("\nGrid layouts:")
    pprint.pprint(grid.layouts)
    
    print("\n=== Component Serialization ===")
    try:
        serialized = grid.to_plotly_json()
        print("Serialization successful!")
        
        # Check serialized children
        serialized_children = serialized.get('props', {}).get('children', [])
        print(f"Serialized children count: {len(serialized_children)}")
        
        for i, child in enumerate(serialized_children):
            if isinstance(child, dict) and 'props' in child:
                child_id = child['props'].get('id', 'NO ID')
                print(f"  Serialized child {i}: id = {child_id}")
            else:
                print(f"  Serialized child {i}: unexpected format")
        
        # Check serialized layouts
        serialized_layouts = serialized.get('props', {}).get('layouts', {})
        print("\nSerialized layouts:")
        for breakpoint, layout_list in serialized_layouts.items():
            print(f"  {breakpoint}:")
            for item in layout_list:
                print(f"    Item ID: {item.get('i', 'NO ID')}")
        
        # Save serialized data for comparison
        with open(f"serialized_dash_{dash.__version__.replace('.', '_')}.json", 'w') as f:
            json.dump(serialized, f, indent=2)
        print(f"\nSerialized data saved to serialized_dash_{dash.__version__.replace('.', '_')}.json")
        
    except Exception as e:
        print(f"Serialization failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_serialization()