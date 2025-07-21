#!/usr/bin/env python3
"""
Minimal test to identify ID serialization differences between Dash v2 and v3
"""

import uuid
import sys
import dash
from dash import html, Input, Output, callback
import dash_draggable
import json


def generate_unique_index():
    return str(uuid.uuid4())


def run_test(dash_version):
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    print(f"\n=== Testing with Dash {dash_version} ===")
    print(f"UUID 1: {uuid1}")
    print(f"UUID 2: {uuid2}")

    # Test ID format
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"Box ID 1: {box_id1}")
    print(f"Box ID 2: {box_id2}")

    # Test layout structure
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    print(f"Layout structure:")
    print(json.dumps(layout, indent=2))

    # Test children structure
    children = [
        html.Div(
            id=box_id1,
            children=[html.H3("Component 1"), html.P(f"ID: {box_id1}")],
        ),
        html.Div(
            id=box_id2,
            children=[html.H3("Component 2"), html.P(f"ID: {box_id2}")],
        ),
    ]

    print(f"Children IDs: {[child.id for child in children]}")

    # Test component creation
    try:
        grid = dash_draggable.ResponsiveGridLayout(
            id="test-grid",
            children=children,
            layouts=layout,
            isDraggable=True,
            isResizable=True,
            save=False,
        )
        print(f"✓ ResponsiveGridLayout created successfully")
        print(f"  Grid ID: {grid.id}")
        print(f"  Grid children count: {len(grid.children) if grid.children else 0}")
        print(f"  Grid layouts: {grid.layouts}")

        # Test if component can be serialized
        try:
            serialized = grid.to_plotly_json()
            print(f"✓ Component serialization successful")
            print(f"  Serialized props keys: {list(serialized.get('props', {}).keys())}")
        except Exception as e:
            print(f"✗ Component serialization failed: {e}")

    except Exception as e:
        print(f"✗ ResponsiveGridLayout creation failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print(f"Dash version: {dash.__version__}")
    print(f"dash-draggable version: {dash_draggable.__version__}")

    run_test(dash.__version__)
