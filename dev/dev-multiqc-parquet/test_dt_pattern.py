#!/usr/bin/env python3
"""
Test the enhanced dt.section_by_id.*.rows_by_sgroup pattern extraction
"""

import sys
sys.path.append('.')
from multiqc_extractor import MultiQCExtractor
import json

def test_dt_pattern():
    """Test the DataTable pattern extraction with the provided examples."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    # Test anchors from user examples
    test_anchors = [
        'fastqc_top_overrepresented_sequences_table',
        'samtools-stats-dp', 
        'gatk_ask_stats'
    ]
    
    print("Testing enhanced dt.section_by_id.*.rows_by_sgroup pattern extraction")
    print("="*80)
    
    for anchor in test_anchors:
        print(f"\n🔍 Testing anchor: {anchor}")
        
        # Get raw data
        anchor_data = extractor.df.filter(
            (extractor.df["anchor"] == anchor) & 
            (extractor.df["type"] == "plot_input")
        )
        
        if anchor_data.shape[0] == 0:
            print(f"   ❌ No data found for {anchor}")
            continue
            
        # Extract plot_input_data JSON
        row = anchor_data.to_dicts()[0]
        plot_input_data_str = row.get("plot_input_data")
        
        if not plot_input_data_str:
            print(f"   ❌ No plot_input_data for {anchor}")
            continue
            
        try:
            plot_input_data = json.loads(plot_input_data_str)
        except:
            print(f"   ❌ Invalid JSON for {anchor}")
            continue
            
        # Test the extraction
        data_type, structure_info = extractor._analyze_json_structure(plot_input_data)
        samples, data_points = extractor._extract_samples_from_json(plot_input_data, data_type)
        
        print(f"   📊 Data type: {data_type.value}")
        print(f"   👥 Samples found: {len(samples)}")
        print(f"   📈 Data points: {len(data_points)}")
        
        if samples:
            print(f"   🏷️  Sample names (first 5): {samples[:5]}")
            
        if data_points:
            print(f"   📋 Sample data point: {data_points[0]}")
            
        if len(samples) > 0 and len(data_points) > 0:
            print(f"   ✅ SUCCESS: Extracted data successfully!")
        else:
            print(f"   ❌ FAILED: No samples/data extracted")
            print(f"   🔧 Structure info: {structure_info}")

if __name__ == "__main__":
    test_dt_pattern()