#!/usr/bin/env python3

import polars as pl
import json
from multiqc_extractor import MultiQCExtractor

def investigate_plot_input_rows():
    """Investigate plot_input_row data for DataTables."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    anchor = "deeptools_coverage_metrics_table"
    
    print("=" * 80)
    print(f"INVESTIGATING PLOT_INPUT_ROW DATA: {anchor}")
    print("=" * 80)
    
    # Get plot_input_row data
    plot_input_rows = extractor.df.filter(
        (pl.col("anchor") == anchor) & 
        (pl.col("type") == "plot_input_row")
    )
    
    print(f"Found {plot_input_rows.shape[0]} plot_input_row entries")
    
    # Look at the structure
    print(f"Columns: {plot_input_rows.columns}")
    
    # Sample some rows
    sample_data = plot_input_rows.head(5).to_dicts()
    for i, row in enumerate(sample_data):
        print(f"\n--- Row {i+1} ---")
        print(f"Sample: {row['sample']}")
        print(f"Metric: {row['metric']}")
        print(f"Value: {row['val_raw']}")
        print(f"Section group: {row.get('sgroup', 'N/A')}")
    
    # Get unique samples and metrics  
    unique_samples = plot_input_rows.select('sample').unique().to_series().to_list()
    unique_metrics = plot_input_rows.select('metric').unique().to_series().to_list()
    
    print(f"\n--- SUMMARY ---")
    print(f"Unique samples: {len(unique_samples)} - {unique_samples}")
    print(f"Unique metrics: {len(unique_metrics)} - {unique_metrics}")
    
    # Check if this data can be extracted
    if len(unique_samples) > 0 and len(unique_metrics) > 0:
        print(f"✅ EXTRACTABLE! {plot_input_rows.shape[0]} data points found")
        
        # Show sample extraction
        data_points = []
        for row in sample_data:
            if row['val_raw'] is not None:
                data_points.append({
                    "sample": row['sample'],
                    "metric": row['metric'], 
                    "value": row['val_raw'],
                    "type": "datatable_cell"
                })
        
        print(f"Sample extracted data points:")
        for dp in data_points:
            print(f"  {dp}")
    else:
        print(f"❌ NOT EXTRACTABLE")
    
    print(f"\n" + "=" * 60)
    print("CHECKING OTHER DATATABLE ANCHORS")
    print("=" * 60)
    
    # Check other DataTable anchors
    other_datatable_anchors = [
        "fastqc_top_overrepresented_sequences_table",
        "checkm-first-table", 
        "samtools-ampliconclip-pct-table",
        "dragen-cov-metrics-own-section-wgs-table",
        "cellranger-atac-stats-table2"
    ]
    
    extractable_count = 0
    
    for anchor in other_datatable_anchors:
        plot_input_rows = extractor.df.filter(
            (pl.col("anchor") == anchor) & 
            (pl.col("type") == "plot_input_row")
        )
        
        row_count = plot_input_rows.shape[0]
        unique_samples = plot_input_rows.select('sample').unique().shape[0] if row_count > 0 else 0
        unique_metrics = plot_input_rows.select('metric').unique().shape[0] if row_count > 0 else 0
        
        print(f"{anchor}:")
        print(f"  Rows: {row_count}, Samples: {unique_samples}, Metrics: {unique_metrics}")
        
        if row_count > 0 and unique_samples > 0 and unique_metrics > 0:
            extractable_count += 1
            print(f"  ✅ EXTRACTABLE")
        else:
            print(f"  ❌ NOT EXTRACTABLE")
    
    print(f"\n--- FINAL SUMMARY ---")
    print(f"DataTables checked: {len(other_datatable_anchors) + 1}")
    print(f"Extractable DataTables: {extractable_count + 1}")

if __name__ == "__main__":
    investigate_plot_input_rows()