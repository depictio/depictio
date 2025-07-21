#!/usr/bin/env python3
"""
Debug component serialization differences between Dash versions
"""

import uuid
import dash
from dash import html
import dash_draggable
import json
import pprint


def generate_unique_index():
    return str(uuid.uuid4())


def debug_component_creation():
    print(f"=== Dash {dash.__version__} Component Creation Debug ===")

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"Creating components with IDs: {box_id1}, {box_id2}")

    # Create individual components first
    child1 = html.Div(
        id=box_id1,
        children=[html.H3("Component 1"), html.P(f"ID: {box_id1}")],
    )

    child2 = html.Div(
        id=box_id2,
        children=[html.H3("Component 2"), html.P(f"ID: {box_id2}")],
    )

    print(f"Child 1 ID: {child1.id}")
    print(f"Child 2 ID: {child2.id}")

    # Create layout
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    print(f"Layout before ResponsiveGridLayout:")
    pprint.pprint(layout)

    # Create ResponsiveGridLayout
    grid = dash_draggable.ResponsiveGridLayout(
        id="test-grid",
        children=[child1, child2],
        layouts=layout,
        isDraggable=True,
        isResizable=True,
        save=False,
    )

    print(f"Grid ID: {grid.id}")
    print(f"Grid children count: {len(grid.children)}")

    # Check children after grid creation
    for i, child in enumerate(grid.children):
        print(f"Child {i} after grid creation: id={child.id if hasattr(child, 'id') else 'NO ID'}")

    print(f"Grid layouts after creation:")
    pprint.pprint(grid.layouts)

    # Check if we can access the to_plotly_json method
    try:
        serialized = grid.to_plotly_json()
        print(f"Serialization successful")

        # Look at the props
        props = serialized.get("props", {})
        print(f"Serialized props keys: {list(props.keys())}")

        # Check children in serialized form
        serialized_children = props.get("children", [])
        print(f"Serialized children count: {len(serialized_children)}")

        for i, child in enumerate(serialized_children):
            if isinstance(child, dict):
                child_props = child.get("props", {})
                child_id = child_props.get("id", "NO ID")
                print(f"Serialized child {i}: id={child_id}")
            else:
                print(f"Serialized child {i}: not a dict - {type(child)}")

        # Check layouts in serialized form
        serialized_layouts = props.get("layouts", {})
        print(f"Serialized layouts:")
        for breakpoint, items in serialized_layouts.items():
            print(f"  {breakpoint}:")
            for j, item in enumerate(items):
                print(f"    Item {j}: {item}")

    except Exception as e:
        print(f"Serialization failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_component_creation()
