#!/usr/bin/env python3
"""
MultiQC Data Export and Problem Analysis
========================================

Identifies problematic anchors and exports successfully extracted data to CSV files.
"""

import polars as pl
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
from multiqc_extractor import MultiQCExtractor, DataType

def analyze_problematic_anchors(extractor: MultiQCExtractor) -> Dict[str, Any]:
    """Analyze and categorize problematic anchors."""
    
    # Get extraction results
    plot_data = extractor.extract_plot_input_data()
    row_data = extractor.extract_plot_input_row_data()
    
    problems = {
        "json_parse_errors": [],
        "empty_extractions": [],
        "unknown_patterns": [],
        "no_samples": [],
        "analysis_summary": {}
    }
    
    # Analyze plot_input data issues
    for data in plot_data:
        metadata = data.metadata
        
        # JSON parsing errors
        if metadata.get("json_parsed") == False and "json_error" in metadata:
            problems["json_parse_errors"].append({
                "anchor": data.anchor,
                "error": metadata["json_error"],
                "rows": metadata["total_rows"]
            })
        
        # No JSON data available
        elif metadata.get("no_json_data"):
            problems["empty_extractions"].append({
                "anchor": data.anchor,
                "issue": "No plot_input_data available",
                "rows": metadata["total_rows"]
            })
        
        # Unknown patterns (parsed but couldn't extract meaningful data)
        elif data.data_type == DataType.UNKNOWN:
            problems["unknown_patterns"].append({
                "anchor": data.anchor,
                "structure_info": metadata.get("structure_info", {}),
                "rows": metadata["total_rows"]
            })
        
        # Successfully parsed but no samples extracted
        elif len(data.sample_names) == 0 and data.data_type != DataType.UNKNOWN:
            problems["no_samples"].append({
                "anchor": data.anchor,
                "data_type": data.data_type.value,
                "structure_info": metadata.get("structure_info", {}),
                "rows": metadata["total_rows"]
            })
    
    # Summary statistics
    total_anchors = len(plot_data)
    successful_anchors = len([d for d in plot_data if len(d.sample_names) > 0])
    
    problems["analysis_summary"] = {
        "total_plot_input_anchors": total_anchors,
        "successful_extractions": successful_anchors,
        "success_rate": f"{(successful_anchors/total_anchors*100):.1f}%",
        "json_parse_errors": len(problems["json_parse_errors"]),
        "empty_extractions": len(problems["empty_extractions"]),
        "unknown_patterns": len(problems["unknown_patterns"]),
        "no_samples_extracted": len(problems["no_samples"]),
        "total_tabular_anchors": len(row_data),
        "tabular_success_rate": "100%" if row_data else "0%"
    }
    
    return problems

def export_successful_data_to_csv(extractor: MultiQCExtractor, output_dir: str):
    """Export all successfully extracted data to CSV files."""
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    export_summary = {
        "general_statistics": None,
        "plot_input_data": [],
        "tabular_data": [],
        "files_created": []
    }
    
    print("Exporting successfully extracted data to CSV...")
    
    # 1. Export General Statistics
    print("  - Exporting general statistics...")
    general_stats = extractor.extract_general_statistics()
    if general_stats.data_points:
        df_data = []
        for point in general_stats.data_points:
            df_data.append({
                "sample": point["sample"],
                "metric": point["metric"],
                "value": point["value"],
                "value_type": point["value_type"],
                "formatted_value": point["formatted_value"]
            })
        
        df = pl.DataFrame(df_data)
        csv_file = output_path / "general_statistics.csv"
        df.write_csv(csv_file)
        export_summary["files_created"].append(str(csv_file))
        export_summary["general_statistics"] = {
            "file": str(csv_file),
            "rows": len(df),
            "samples": df.select("sample").n_unique(),
            "metrics": df.select("metric").n_unique()
        }
        print(f"    ✅ Saved: {csv_file} ({len(df)} rows)")
    
    # 2. Export Plot Input Data (successful extractions only)
    print("  - Exporting plot input data...")
    plot_data = extractor.extract_plot_input_data()
    successful_plot_data = [d for d in plot_data if len(d.sample_names) > 0]
    
    for data in successful_plot_data:
        if data.data_points:
            df_data = []
            
            # Convert data points to flat structure for CSV
            for point in data.data_points:
                row = {
                    "anchor": data.anchor,
                    "data_type": data.data_type.value,
                    "sample": point.get("sample", ""),
                    "metric": point.get("metric", ""),
                    "value": point.get("value", ""),
                    "type": point.get("type", "")
                }
                
                # Add additional fields based on data type
                if "x" in point:
                    row["x"] = point["x"]
                if "y" in point:
                    row["y"] = point["y"]
                if "index" in point:
                    row["index"] = point["index"]
                
                df_data.append(row)
            
            if df_data:
                # Handle mixed data types by converting everything to string first
                for row in df_data:
                    for key, value in row.items():
                        if value is not None:
                            row[key] = str(value)
                        else:
                            row[key] = ""
                
                df = pl.DataFrame(df_data)
                safe_anchor = data.anchor.replace("/", "_").replace(":", "_")
                csv_file = output_path / f"plot_input_{safe_anchor}.csv"
                df.write_csv(csv_file)
                export_summary["files_created"].append(str(csv_file))
                export_summary["plot_input_data"].append({
                    "anchor": data.anchor,
                    "file": str(csv_file),
                    "rows": len(df),
                    "samples": len(data.sample_names),
                    "data_type": data.data_type.value
                })
                print(f"    ✅ Saved: {csv_file} ({len(df)} rows)")
    
    # 3. Export Tabular Data
    print("  - Exporting tabular data...")
    row_data = extractor.extract_plot_input_row_data()
    
    for data in row_data:
        if data.data_points and len(data.sample_names) > 0:
            df_data = []
            
            for point in data.data_points:
                df_data.append({
                    "anchor": data.anchor,
                    "sample": point.get("sample", ""),
                    "metric": point.get("metric", ""),
                    "value": point.get("value", ""),
                    "value_type": point.get("value_type", ""),
                    "formatted_value": point.get("formatted_value", ""),
                    "dt_anchor": point.get("dt_anchor", ""),
                    "section_key": point.get("section_key", "")
                })
            
            if df_data:
                # Handle mixed data types by converting everything to string first
                for row in df_data:
                    for key, value in row.items():
                        if value is not None:
                            row[key] = str(value)
                        else:
                            row[key] = ""
                
                df = pl.DataFrame(df_data)
                safe_anchor = data.anchor.replace("/", "_").replace(":", "_")
                csv_file = output_path / f"tabular_{safe_anchor}.csv"
                df.write_csv(csv_file)
                export_summary["files_created"].append(str(csv_file))
                export_summary["tabular_data"].append({
                    "anchor": data.anchor,
                    "file": str(csv_file),
                    "rows": len(df),
                    "samples": len(data.sample_names),
                    "metrics": data.metadata.get("unique_metrics", 0)
                })
                print(f"    ✅ Saved: {csv_file} ({len(df)} rows)")
    
    return export_summary

def create_problem_analysis_report(problems: Dict[str, Any], output_dir: str):
    """Create detailed reports of problematic anchors."""
    
    output_path = Path(output_dir)
    
    # Create problem summary JSON
    problems_file = output_path / "problematic_anchors_analysis.json"
    with open(problems_file, 'w') as f:
        json.dump(problems, f, indent=2, default=str)
    
    # Create human-readable problem report
    report_file = output_path / "PROBLEMATIC_ANCHORS_REPORT.md"
    with open(report_file, 'w') as f:
        f.write("# MultiQC Problematic Anchors Analysis\n\n")
        
        summary = problems["analysis_summary"]
        f.write("## Summary\n\n")
        f.write(f"- **Total anchors processed**: {summary['total_plot_input_anchors']}\n")
        f.write(f"- **Successful extractions**: {summary['successful_extractions']} ({summary['success_rate']})\n")
        f.write(f"- **JSON parse errors**: {summary['json_parse_errors']}\n")
        f.write(f"- **Empty extractions**: {summary['empty_extractions']}\n")
        f.write(f"- **Unknown patterns**: {summary['unknown_patterns']}\n")
        f.write(f"- **No samples extracted**: {summary['no_samples_extracted']}\n\n")
        
        # JSON Parse Errors
        if problems["json_parse_errors"]:
            f.write("## JSON Parse Errors\n\n")
            f.write("These anchors have malformed JSON that couldn't be parsed:\n\n")
            for error in problems["json_parse_errors"]:
                f.write(f"- **{error['anchor']}**: {error['error']}\n")
        
        # Empty Extractions
        if problems["empty_extractions"]:
            f.write("\n## Empty Extractions\n\n")
            f.write("These anchors have no plot_input_data available:\n\n")
            for empty in problems["empty_extractions"]:
                f.write(f"- **{empty['anchor']}**: {empty['issue']}\n")
        
        # Unknown Patterns
        if problems["unknown_patterns"]:
            f.write("\n## Unknown Patterns\n\n")
            f.write("These anchors were parsed successfully but don't match known data patterns:\n\n")
            for unknown in problems["unknown_patterns"][:20]:  # Limit to first 20
                f.write(f"- **{unknown['anchor']}**: {unknown['structure_info'].get('raw_type', 'unknown')}\n")
        
        # No Samples Extracted
        if problems["no_samples"]:
            f.write("\n## No Samples Extracted\n\n")
            f.write("These anchors have recognizable patterns but no samples were extracted:\n\n")
            for no_samples in problems["no_samples"]:
                f.write(f"- **{no_samples['anchor']}** ({no_samples['data_type']}): {no_samples['structure_info']}\n")
    
    return problems_file, report_file

def main():
    """Main execution function."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    output_dir = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/extracted_data"
    
    print("="*80)
    print("MULTIQC DATA EXPORT AND PROBLEM ANALYSIS")
    print("="*80)
    
    # Initialize extractor
    print("Initializing MultiQC extractor...")
    extractor = MultiQCExtractor(parquet_path)
    
    # Analyze problems
    print("\nAnalyzing problematic anchors...")
    problems = analyze_problematic_anchors(extractor)
    
    # Export successful data
    print("\nExporting successful extractions...")
    export_summary = export_successful_data_to_csv(extractor, output_dir)
    
    # Create problem reports
    print("\nCreating problem analysis reports...")
    problems_file, report_file = create_problem_analysis_report(problems, output_dir)
    
    print("\n" + "="*80)
    print("EXPORT SUMMARY")
    print("="*80)
    
    # Summary statistics
    summary = problems["analysis_summary"]
    print(f"\n📊 EXTRACTION RESULTS")
    print(f"   • Success rate: {summary['success_rate']}")
    print(f"   • Successful anchors: {summary['successful_extractions']}/{summary['total_plot_input_anchors']}")
    
    print(f"\n📁 FILES CREATED")
    print(f"   • CSV files: {len(export_summary['files_created'])}")
    print(f"   • General statistics: {export_summary['general_statistics']['rows'] if export_summary['general_statistics'] else 0} rows")
    print(f"   • Plot input data: {len(export_summary['plot_input_data'])} files")
    print(f"   • Tabular data: {len(export_summary['tabular_data'])} files")
    
    print(f"\n❌ PROBLEM CATEGORIES")
    print(f"   • JSON parse errors: {summary['json_parse_errors']}")
    print(f"   • Empty extractions: {summary['empty_extractions']}")
    print(f"   • Unknown patterns: {summary['unknown_patterns']}")
    print(f"   • No samples extracted: {summary['no_samples_extracted']}")
    
    print(f"\n📋 REPORTS GENERATED")
    print(f"   • Problem analysis: {problems_file}")
    print(f"   • Human-readable report: {report_file}")
    print(f"   • Data export directory: {output_dir}")
    
    # Show top successful extractions
    print(f"\n🎯 TOP SUCCESSFUL EXTRACTIONS")
    successful_plot = sorted(export_summary['plot_input_data'], key=lambda x: x['samples'], reverse=True)
    for item in successful_plot[:5]:
        print(f"   • {item['anchor']}: {item['samples']} samples ({item['rows']} rows)")
    
    return export_summary, problems

if __name__ == "__main__":
    export_summary, problems = main()