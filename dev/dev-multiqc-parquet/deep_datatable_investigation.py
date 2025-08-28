#!/usr/bin/env python3

import polars as pl
import json
from multiqc_extractor import MultiQCExtractor

def deep_investigate_datatables():
    """Deep investigation of DataTable structure and data location."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    # Check one DataTable in detail
    anchor = "deeptools_coverage_metrics_table"
    
    print("=" * 80)
    print(f"DEEP INVESTIGATION: {anchor}")
    print("=" * 80)
    
    # Get ALL data related to this anchor
    all_anchor_data = extractor.df.filter(pl.col("anchor") == anchor)
    print(f"Total rows for this anchor: {all_anchor_data.shape[0]}")
    print(f"Available types: {all_anchor_data.select('type').unique().to_series().to_list()}")
    
    for row in all_anchor_data.to_dicts():
        print(f"\n--- Row: {row['type']} ---")
        
        if row['type'] == 'plot_input':
            plot_data_raw = row['plot_input_data']
            if plot_data_raw:
                try:
                    raw_json = json.loads(plot_data_raw)
                    print(f"plot_input keys: {list(raw_json.keys())}")
                    
                    if 'dt' in raw_json:
                        dt = raw_json['dt']
                        print(f"dt keys: {list(dt.keys())}")
                        
                        # Investigate section_by_id
                        if 'section_by_id' in dt:
                            sections = dt['section_by_id']
                            print(f"section_by_id type: {type(sections)}")
                            if isinstance(sections, dict):
                                print(f"section_by_id keys: {list(sections.keys())}")
                                for section_key, section_data in list(sections.items())[:2]:
                                    print(f"  Section '{section_key}': {type(section_data)}")
                                    if isinstance(section_data, dict):
                                        print(f"    Keys: {list(section_data.keys())[:5]}")
                        
                        # Investigate headers_in_order  
                        if 'headers_in_order' in dt:
                            headers = dt['headers_in_order']
                            print(f"headers_in_order: {headers}")
                            
                except json.JSONDecodeError as e:
                    print(f"JSON parse error: {e}")
        
        elif row['type'] == 'general_stats_table':
            print(f"general_stats sample: {row['sample']}")
            print(f"general_stats metric: {row['metric']}")  
            print(f"general_stats value: {row['val_raw']}")
    
    print(f"\n" + "=" * 60)
    print("CHECKING IF DATA IS IN GENERAL_STATS_TABLE")
    print("=" * 60)
    
    # Check if the datatable data is actually stored as general_stats_table rows
    general_stats_rows = extractor.df.filter(
        (pl.col("anchor") == anchor) & 
        (pl.col("type") == "general_stats_table")
    )
    
    if general_stats_rows.shape[0] > 0:
        print(f"Found {general_stats_rows.shape[0]} general_stats rows for this anchor!")
        
        # Sample some rows
        sample_rows = general_stats_rows.head(10).to_dicts()
        for row in sample_rows:
            print(f"  Sample: {row['sample']}, Metric: {row['metric']}, Value: {row['val_raw']}")
        
        # Get unique samples and metrics
        unique_samples = general_stats_rows.select('sample').unique().to_series().to_list()
        unique_metrics = general_stats_rows.select('metric').unique().to_series().to_list()
        
        print(f"\nUnique samples: {len(unique_samples)} - {unique_samples[:5]}")
        print(f"Unique metrics: {len(unique_metrics)} - {unique_metrics[:5]}")
        
        print(f"✅ DATA FOUND IN GENERAL_STATS! {general_stats_rows.shape[0]} data points")
    else:
        print("❌ No general_stats data found for this anchor")
    
    print(f"\n" + "=" * 60) 
    print("CHECKING OTHER DATATABLES")
    print("=" * 60)
    
    # Check a few more DataTable anchors
    other_datatable_anchors = [
        "fastqc_top_overrepresented_sequences_table",
        "checkm-first-table", 
        "samtools-ampliconclip-pct-table"
    ]
    
    for anchor in other_datatable_anchors:
        general_stats_count = extractor.df.filter(
            (pl.col("anchor") == anchor) & 
            (pl.col("type") == "general_stats_table")
        ).shape[0]
        
        print(f"{anchor}: {general_stats_count} general_stats rows")

if __name__ == "__main__":
    deep_investigate_datatables()