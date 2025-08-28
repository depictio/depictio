#!/usr/bin/env python3
"""
Test script for new extraction patterns
"""

import json
from multiqc_extractor import MultiQCExtractor

def test_pattern_recognition():
    """Test if the new patterns are recognized correctly."""
    
    # Test data structures from the examples
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
        'creation_date': '2025-08-14T15:01:45.232106+02:00',
        'datasets': {
            'CPG13045*CPG13052': [{
                'color': 'rgba(74, 124, 182, 0.6)',
                'group': 'Unrelated',
                'marker_line_width': 0,
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
    
    print("Testing pattern recognition...")
    
    # Create a minimal extractor instance without loading parquet
    import polars as pl
    from multiqc_extractor import DataType
    
    class MockExtractor:
        def __init__(self):
            self.df = None
            
        def _analyze_json_structure(self, data):
            # Copy the method from MultiQCExtractor
            from multiqc_extractor import MultiQCExtractor
            temp_extractor = type('temp', (), {})()
            temp_extractor._analyze_json_structure = MultiQCExtractor._analyze_json_structure.__get__(temp_extractor)
            return temp_extractor._analyze_json_structure(data)
            
        def _extract_samples_from_json(self, data, data_type):
            # Copy the method from MultiQCExtractor
            from multiqc_extractor import MultiQCExtractor
            temp_extractor = type('temp', (), {})()
            temp_extractor._extract_samples_from_json = MultiQCExtractor._extract_samples_from_json.__get__(temp_extractor)
            return temp_extractor._extract_samples_from_json(data, data_type)
    
    extractor = MockExtractor()
    
    # Test bbmap pattern recognition
    bbmap_type, bbmap_info = extractor._analyze_json_structure(bbmap_qhist_data)
    print(f"bbmap-qhist_plot: {bbmap_type.value}")
    print(f"  Structure info: {bbmap_info}")
    
    # Test somalier pattern recognition  
    somalier_type, somalier_info = extractor._analyze_json_structure(somalier_data)
    print(f"somalier_relatedness_plot: {somalier_type.value}")
    print(f"  Structure info: {somalier_info}")
    
    # Test extraction from bbmap data
    bbmap_samples, bbmap_points = extractor._extract_samples_from_json(bbmap_qhist_data, bbmap_type)
    print(f"\\nbbmap extraction:")
    print(f"  Samples: {bbmap_samples}")
    print(f"  Data points: {len(bbmap_points)}")
    if bbmap_points:
        print(f"  First point: {bbmap_points[0]}")
    
    # Test extraction from somalier data
    somalier_samples, somalier_points = extractor._extract_samples_from_json(somalier_data, somalier_type)
    print(f"\\nsomalier extraction:")
    print(f"  Samples: {somalier_samples}")
    print(f"  Data points: {len(somalier_points)}")
    if somalier_points:
        print(f"  First point: {somalier_points[0]}")
    
    return bbmap_type, somalier_type

if __name__ == "__main__":
    test_pattern_recognition()