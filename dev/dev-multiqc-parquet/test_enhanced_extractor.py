#!/usr/bin/env python3

from multiqc_extractor import MultiQCExtractor, DataType

def test_enhanced_extractor():
    """Test the enhanced extractor with DataTable support."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    
    print("=" * 80)
    print("TESTING ENHANCED MULTIQC EXTRACTOR")
    print("=" * 80)
    
    # Initialize extractor
    extractor = MultiQCExtractor(parquet_path)
    
    # Test plot_input extraction
    print("\n--- PLOT_INPUT EXTRACTION ---")
    plot_data = extractor.extract_plot_input_data()
    plot_successful = [d for d in plot_data if len(d.sample_names) > 0]
    plot_unsuccessful = [d for d in plot_data if len(d.sample_names) == 0]
    
    print(f"Total plot_input anchors: {len(plot_data)}")
    print(f"Successful: {len(plot_successful)}")
    print(f"Unsuccessful: {len(plot_unsuccessful)}")
    
    # Test DataTable extraction
    print("\n--- DATATABLE EXTRACTION ---") 
    datatable_data = extractor.extract_plot_input_row_data()
    datatable_successful = [d for d in datatable_data if len(d.sample_names) > 0]
    datatable_unsuccessful = [d for d in datatable_data if len(d.sample_names) == 0]
    
    print(f"Total DataTable anchors: {len(datatable_data)}")
    print(f"Successful: {len(datatable_successful)}")
    print(f"Unsuccessful: {len(datatable_unsuccessful)}")
    
    # Combined results
    print("\n--- COMBINED RESULTS ---")
    all_data = plot_data + datatable_data
    all_successful = plot_successful + datatable_successful
    all_unsuccessful = plot_unsuccessful + datatable_unsuccessful
    
    print(f"Total anchors processed: {len(all_data)}")
    print(f"Total successful: {len(all_successful)} ({len(all_successful)/len(all_data)*100:.1f}%)")
    print(f"Total unsuccessful: {len(all_unsuccessful)} ({len(all_unsuccessful)/len(all_data)*100:.1f}%)")
    
    # Sample successful DataTable extractions
    print("\n--- SAMPLE DATATABLE EXTRACTIONS ---")
    for i, data in enumerate(datatable_successful[:3]):
        print(f"\n{i+1}. {data.anchor}")
        print(f"   Data type: {data.data_type.value}")
        print(f"   Samples: {len(data.sample_names)} - {data.sample_names[:3]}")
        print(f"   Data points: {len(data.data_points)}")
        if data.data_points:
            print(f"   Sample data point: {data.data_points[0]}")
    
    # Check if previously unsuccessful anchors are now successful
    print("\n--- PREVIOUSLY UNSUCCESSFUL ANCHORS STATUS ---")
    previously_unsuccessful = [
        "deeptools_coverage_metrics_table",
        "fastqc_top_overrepresented_sequences_table", 
        "checkm-first-table",
        "samtools-ampliconclip-pct-table",
        "dragen-cov-metrics-own-section-wgs-table"
    ]
    
    now_successful = 0
    for anchor in previously_unsuccessful:
        found_data = None
        for data in all_successful:
            if data.anchor == anchor:
                found_data = data
                break
        
        if found_data:
            now_successful += 1
            print(f"✅ {anchor}: {len(found_data.sample_names)} samples, {len(found_data.data_points)} data points")
        else:
            print(f"❌ {anchor}: Still unsuccessful")
    
    print(f"\nRecovered {now_successful}/{len(previously_unsuccessful)} previously unsuccessful anchors")
    
    return all_successful, all_unsuccessful

if __name__ == "__main__":
    test_enhanced_extractor()