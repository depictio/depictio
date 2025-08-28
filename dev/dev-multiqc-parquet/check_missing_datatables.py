#!/usr/bin/env python3

import polars as pl
from multiqc_extractor import MultiQCExtractor

def check_missing_datatables():
    """Check why some expected DataTables are not showing up in extraction."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    # Expected DataTable anchors from our investigation
    expected_datatables = [
        "fastqc_top_overrepresented_sequences_table",
        "checkm-first-table", 
        "dragen-cov-metrics-own-section-wgs-table",
        "cellranger-atac-stats-table2"
    ]
    
    print("=" * 80)
    print("INVESTIGATING MISSING DATATABLE EXTRACTIONS")
    print("=" * 80)
    
    # Get actual DataTable extraction results
    datatable_data = extractor.extract_plot_input_row_data()
    extracted_anchors = [data.anchor for data in datatable_data]
    
    print(f"Total DataTable anchors extracted: {len(datatable_data)}")
    print(f"First 10 extracted anchors: {extracted_anchors[:10]}")
    
    print(f"\n--- CHECKING EXPECTED ANCHORS ---")
    
    for anchor in expected_datatables:
        print(f"\n🔍 {anchor}:")
        
        # Check if it has plot_input_row data
        plot_input_rows = extractor.df.filter(
            (pl.col("anchor") == anchor) & 
            (pl.col("type") == "plot_input_row")
        )
        
        row_count = plot_input_rows.shape[0]
        print(f"  plot_input_row entries: {row_count}")
        
        if row_count > 0:
            # Check if it was extracted
            if anchor in extracted_anchors:
                extracted_data = None
                for data in datatable_data:
                    if data.anchor == anchor:
                        extracted_data = data
                        break
                print(f"  ✅ EXTRACTED: {len(extracted_data.sample_names)} samples, {len(extracted_data.data_points)} data points")
            else:
                print(f"  ❌ NOT EXTRACTED despite having data")
                
                # Debug why it wasn't extracted
                sample_data = plot_input_rows.head(3).to_dicts()
                for i, row in enumerate(sample_data):
                    sample = row['sample']
                    metric = row['metric']
                    value = row['val_raw']
                    print(f"    Row {i+1}: sample='{sample}', metric='{metric}', value={value} (type: {type(value)})")
        else:
            print(f"  ❌ NO plot_input_row data found")
            
            # Check what types of data this anchor does have
            all_anchor_data = extractor.df.filter(pl.col("anchor") == anchor)
            if all_anchor_data.shape[0] > 0:
                types = all_anchor_data.select('type').unique().to_series().to_list()
                print(f"    Available types: {types}")
            else:
                print(f"    Anchor not found in data at all")
    
    print(f"\n--- SUMMARY ---")
    found_in_extraction = len([a for a in expected_datatables if a in extracted_anchors])
    print(f"Expected DataTables found in extraction: {found_in_extraction}/{len(expected_datatables)}")

if __name__ == "__main__":
    check_missing_datatables()