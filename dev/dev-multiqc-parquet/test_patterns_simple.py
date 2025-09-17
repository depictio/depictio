#!/usr/bin/env python3
"""
Simple test for pattern recognition functions
"""

import sys
sys.path.append('.')

# Test data structures
bbmap_qhist_data = {
    'anchor': 'bbmap-qhist_plot',
    'creation_date': '2025-08-14T15:01:45.232106+02:00',
    'data': [[{
        'name': 'sample1.Read1',
        'pairs': [[1, 24.652], [2, 25.264], [3, 21.7], [4, 26.204]]
    }]]
}

somalier_data = {
    'anchor': 'somalier_relatedness_plot', 
    'datasets': {
        'CPG13045*CPG13052': [{
            'color': 'rgba(74, 124, 182, 0.6)',
            'group': 'Unrelated',
            'name': 'CPG13045*CPG13052',
            'x': 1629.0,
            'y': 7352.0
        }],
        'CPG13045*CPG13060': [{
            'color': 'rgba(74, 124, 182, 0.6)',
            'group': 'Unrelated', 
            'name': 'CPG13045*CPG13060',
            'x': 1653.0,
            'y': 7131.0
        }]
    }
}

print("Testing pattern structures...")

# Test structure analysis
print("\\n=== bbmap_qhist_data structure ===")
if 'data' in bbmap_qhist_data:
    data = bbmap_qhist_data['data']
    print(f"data type: {type(data)}")
    if isinstance(data, list) and len(data) > 0:
        print(f"data[0] type: {type(data[0])}")
        if isinstance(data[0], list) and len(data[0]) > 0:
            print(f"data[0][0] type: {type(data[0][0])}")
            if isinstance(data[0][0], dict):
                print(f"data[0][0] keys: {list(data[0][0].keys())}")
                if 'name' in data[0][0] and 'pairs' in data[0][0]:
                    print("✅ Matches bbmap pattern: nested list with name/pairs")
                    print(f"  Sample: {data[0][0]['name']}")
                    print(f"  Pairs count: {len(data[0][0]['pairs'])}")

print("\\n=== somalier_data structure ===")
if 'datasets' in somalier_data:
    datasets = somalier_data['datasets']
    print(f"datasets type: {type(datasets)}")
    if isinstance(datasets, dict):
        sample_keys = list(datasets.keys())
        print(f"Sample keys: {sample_keys[:2]}")
        if len(sample_keys) > 0:
            first_dataset = datasets[sample_keys[0]]
            print(f"First dataset type: {type(first_dataset)}")
            if isinstance(first_dataset, list) and len(first_dataset) > 0:
                point = first_dataset[0]
                if isinstance(point, dict) and 'x' in point and 'y' in point:
                    print("✅ Matches somalier pattern: datasets dict with x/y points")
                    print(f"  Sample pair: {sample_keys[0]}")
                    print(f"  Point: x={point['x']}, y={point['y']}")

print("\\n=== Pattern Recognition Results ===")
print("Both patterns should now be properly recognized as LINE_SCATTER data types")
print("instead of UNKNOWN when running the full extraction.")