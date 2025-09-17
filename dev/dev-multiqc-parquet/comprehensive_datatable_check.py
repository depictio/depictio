#!/usr/bin/env python3

import polars as pl
from multiqc_extractor import MultiQCExtractor

def comprehensive_datatable_check():
    """Comprehensive check of all DataTable anchors."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    
    print("=" * 80)
    print("COMPREHENSIVE DATATABLE ANALYSIS")
    print("=" * 80)
    
    # Load data directly to understand the structure
    df = pl.read_parquet(parquet_path)
    
    # Get all anchors that have plot_input_row data
    all_plot_input_row_anchors = df.filter(pl.col("type") == "plot_input_row").select("anchor").unique().to_series().to_list()
    
    print(f"Total anchors with plot_input_row data: {len(all_plot_input_row_anchors)}")
    
    # Test extractor
    extractor = MultiQCExtractor(parquet_path)
    datatable_data = extractor.extract_plot_input_row_data()
    extracted_anchors = [data.anchor for data in datatable_data]
    
    print(f"Anchors extracted by extractor: {len(extracted_anchors)}")
    print(f"Difference: {len(all_plot_input_row_anchors) - len(extracted_anchors)} anchors not extracted")
    
    # Find which anchors are missing
    missing_anchors = [a for a in all_plot_input_row_anchors if a not in extracted_anchors]
    
    print(f"\n--- MISSING ANCHORS ({len(missing_anchors)}) ---")
    for anchor in missing_anchors[:10]:  # Show first 10
        print(f"  {anchor}")
    
    # Debug a few missing anchors
    print(f"\n--- DEBUGGING MISSING ANCHORS ---")
    for anchor in missing_anchors[:3]:
        print(f"\n🔍 {anchor}:")
        
        anchor_data = df.filter(
            (pl.col("anchor") == anchor) & 
            (pl.col("type") == "plot_input_row")
        ).head(3)
        
        for row in anchor_data.to_dicts():
            sample = row['sample']
            metric = row['metric']
            value = row['val_raw']
            print(f"  Sample: '{sample}' (length: {len(sample) if sample else 0})")
            print(f"  Metric: '{metric}' (length: {len(metric) if metric else 0})")
            print(f"  Value: {value} (type: {type(value)})")
            
            # Check if sample and metric have values
            has_sample = sample is not None and str(sample).strip() != '' and str(sample) != 'nan'
            has_metric = metric is not None and str(metric).strip() != '' and str(metric) != 'nan'
            print(f"  Has valid sample: {has_sample}")
            print(f"  Has valid metric: {has_metric}")
            print()
    
    # Check extraction logic on one missing anchor manually
    print(f"\n--- MANUAL EXTRACTION TEST ---")
    if missing_anchors:
        test_anchor = missing_anchors[0]
        print(f"Testing: {test_anchor}")
        
        anchor_df = df.filter(
            (pl.col("anchor") == test_anchor) & 
            (pl.col("type") == "plot_input_row")
        )
        
        samples = []
        data_points = []
        
        for row in anchor_df.to_dicts():
            sample = row['sample']
            metric = row['metric'] 
            value = row['val_raw']
            
            print(f"Row: sample='{sample}', metric='{metric}', value={value}")
            
            if sample and metric:  # Same logic as in extractor
                if sample not in samples:
                    samples.append(sample)
                
                data_points.append({
                    "sample": sample,
                    "metric": metric,
                    "value": value,
                    "type": "datatable_cell"
                })
        
        print(f"Manual extraction result: {len(samples)} samples, {len(data_points)} data points")
        if samples:
            print(f"Samples: {samples[:3]}")
        if data_points:
            print(f"Sample data point: {data_points[0]}")

if __name__ == "__main__":
    comprehensive_datatable_check()