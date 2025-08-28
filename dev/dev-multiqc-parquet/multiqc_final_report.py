#!/usr/bin/env python3
"""
MultiQC Parquet Data Extraction - Final Summary Report
======================================================

This script provides the final organized report and categorization of MultiQC parquet data
that can be programmatically leveraged for building a data ingestion module.
"""

import polars as pl
import json
from typing import Dict, List, Any
from multiqc_extractor import MultiQCExtractor, DataType

def create_categorization_dict(extractor: MultiQCExtractor) -> Dict[str, Any]:
    """Create a programmatically usable categorization dictionary."""
    
    # Get extraction report
    report = extractor.extraction_report
    
    categorization = {
        "data_extraction_patterns": {
            "general_statistics": {
                "description": "General QC statistics table - easily extractable",
                "extraction_method": "filter by anchor == 'general_stats_table'",
                "structure": "tabular with sample, metric, value columns",
                "sample_count": report["general_statistics"]["sample_count"],
                "complexity": "low"
            },
            "plot_input": {
                "description": "Simple plot input data - direct tabular access",
                "extraction_method": "filter by type == 'plot_input'",
                "structure": "tabular with sample, metric, value, anchor columns",
                "anchor_count": len(report["plot_input_data"]),
                "complexity": "low"
            },
            "plot_input_row": {
                "description": "Tabular data organized by anchor (table name)",
                "extraction_method": "filter by type == 'plot_input_row', group by anchor",
                "structure": "tabular grouped by anchor/table",
                "anchor_count": len(report["row_data"]),
                "complexity": "medium"
            },
            "complex_json": {
                "description": "Nested JSON structures in plot_input_data requiring pattern analysis",
                "extraction_method": "parse plot_input_data JSON, analyze structure",
                "structure": "varied - histogram_bar, line_scatter, table_data",
                "anchor_count": len([d for d in report["plot_input_data"] if d["data_type"] in ["histogram_bar", "table_data", "line_scatter"]]),
                "complexity": "high"
            }
        },
        "anchor_categorization": {},
        "extraction_priorities": {
            "priority_1_general_stats": {
                "anchors": ["general_stats_table"],
                "method": "direct_tabular_extraction",
                "expected_yield": "high"
            },
            "priority_2_simple_tables": {
                "anchors": [],
                "method": "plot_input_row_extraction",
                "expected_yield": "high"
            },
            "priority_3_structured_json": {
                "anchors": [],
                "method": "json_pattern_extraction",
                "expected_yield": "medium"
            },
            "priority_4_plot_visualization": {
                "anchors": [],
                "method": "plot_input_extraction",
                "expected_yield": "low"
            }
        }
    }
    
    # Categorize anchors by extraction complexity and data richness
    for row_data in report["row_data"]:
        anchor = row_data["anchor"]
        sample_count = row_data["sample_count"]
        metrics_count = row_data["metadata"].get("unique_metrics", 0)
        
        if sample_count > 5 and metrics_count > 3:  # Rich tabular data
            categorization["extraction_priorities"]["priority_2_simple_tables"]["anchors"].append(anchor)
        
        categorization["anchor_categorization"][anchor] = {
            "type": "tabular",
            "complexity": "medium",
            "sample_count": sample_count,
            "metrics_count": metrics_count,
            "extraction_method": "plot_input_row_extraction"
        }
    
    # Process plot input data (now includes JSON structures)
    for plot_data in report["plot_input_data"]:
        anchor = plot_data["anchor"]
        data_type = plot_data["data_type"]
        sample_count = plot_data["sample_count"]
        
        if sample_count > 10 and data_type in ["histogram_bar", "table_data"]:
            categorization["extraction_priorities"]["priority_3_structured_json"]["anchors"].append(anchor)
        else:
            categorization["extraction_priorities"]["priority_4_plot_visualization"]["anchors"].append(anchor)
        
        categorization["anchor_categorization"][anchor] = {
            "type": "json_structured" if data_type in ["histogram_bar", "table_data", "line_scatter"] else "plot_input",
            "complexity": "high" if data_type == "line_scatter" else ("medium" if data_type in ["histogram_bar", "table_data"] else "low"),
            "data_type": data_type,
            "sample_count": sample_count,
            "extraction_method": "json_pattern_extraction" if data_type != "unknown" else "plot_input_extraction"
        }
    
    return categorization

def generate_extraction_code_templates(categorization: Dict[str, Any]) -> Dict[str, str]:
    """Generate code templates for each extraction pattern."""
    
    templates = {
        "general_statistics": '''
def extract_general_statistics(df: pl.DataFrame) -> pl.DataFrame:
    """Extract general statistics table."""
    return df.filter(pl.col("anchor") == "general_stats_table").select([
        "sample", "metric", "val_raw", "val_raw_type", "val_fmt"
    ])
        ''',
        
        "plot_input_row": '''
def extract_table_data(df: pl.DataFrame, anchor: str) -> pl.DataFrame:
    """Extract tabular data for a specific anchor."""
    return df.filter(
        (pl.col("type") == "plot_input_row") & 
        (pl.col("anchor") == anchor)
    ).select([
        "sample", "metric", "val_raw", "val_raw_type", "val_fmt", 
        "dt_anchor", "section_key"
    ])
        ''',
        
        "json_extraction": '''
def extract_json_data(df: pl.DataFrame, anchor: str) -> List[Dict[str, Any]]:
    """Extract and parse JSON structured data."""
    import json
    
    plot_df = df.filter(
        (pl.col("type") == "plot_input") & 
        (pl.col("anchor") == anchor)
    )
    
    if plot_df.shape[0] == 0:
        return []
    
    plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
    if not plot_data_raw:
        return []
    
    try:
        parsed_data = json.loads(plot_data_raw)
        
        # Extract actual data (handle MultiQC structure)
        if isinstance(parsed_data, dict) and 'data' in parsed_data:
            actual_data = parsed_data['data']
        else:
            actual_data = parsed_data
        
        # Process based on structure
        extracted_points = []
        
        if isinstance(actual_data, dict):
            # Sample-keyed data
            for sample, value in actual_data.items():
                if not sample.startswith('_'):
                    if isinstance(value, dict):
                        for metric, metric_value in value.items():
                            extracted_points.append({
                                "sample": sample,
                                "metric": metric,
                                "value": metric_value
                            })
                    else:
                        extracted_points.append({
                            "sample": sample,
                            "value": value
                        })
        
        elif isinstance(actual_data, list):
            # Handle different list structures
            for item in actual_data:
                if isinstance(item, dict):
                    if 'pairs' in item:  # Plotly series
                        sample = item.get('name', 'unknown')
                        for pair in item['pairs']:
                            if len(pair) >= 2:
                                extracted_points.append({
                                    "sample": sample,
                                    "x": pair[0],
                                    "y": pair[1]
                                })
                    else:
                        # Regular dict items
                        for sample, value in item.items():
                            if not sample.startswith('_'):
                                extracted_points.append({
                                    "sample": sample,
                                    "value": value
                                })
        
        return extracted_points
    
    except json.JSONDecodeError:
        return []
        '''
    }
    
    return templates

def main():
    """Generate comprehensive MultiQC extraction report and templates."""
    
    # Initialize extractor
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    # Extract all data
    report = extractor.extract_all_data(max_row_anchors=50)
    
    # Create categorization
    categorization = create_categorization_dict(extractor)
    
    # Generate code templates
    templates = generate_extraction_code_templates(categorization)
    
    print("="*80)
    print("MULTIQC PARQUET EXTRACTION - FINAL REPORT")
    print("="*80)
    
    print(f"\n📊 DATASET OVERVIEW")
    print(f"   • Total rows: {extractor.df.shape[0]:,}")
    print(f"   • Total columns: {extractor.df.shape[1]}")
    print(f"   • Unique samples: {categorization['data_extraction_patterns']['general_statistics']['sample_count']:,}")
    
    print(f"\n🎯 EXTRACTION PRIORITIES")
    for priority, details in categorization["extraction_priorities"].items():
        anchor_count = len(details["anchors"])
        if anchor_count > 0:
            print(f"   • {priority}: {anchor_count} anchors ({details['expected_yield']} yield)")
            print(f"     Method: {details['method']}")
            if anchor_count <= 5:
                print(f"     Examples: {details['anchors'][:5]}")
    
    print(f"\n📈 DATA TYPE DISTRIBUTION")
    type_counts = report["summary"]["data_type_distribution"]
    for data_type, count in type_counts.items():
        print(f"   • {data_type}: {count} anchors")
    
    print(f"\n🔍 HIGH-VALUE EXTRACTION TARGETS")
    high_value_anchors = []
    
    # Find high-value tabular data
    for anchor, details in categorization["anchor_categorization"].items():
        if (details["type"] == "tabular" and 
            details.get("sample_count", 0) > 5 and 
            details.get("metrics_count", 0) > 5):
            high_value_anchors.append((anchor, details))
    
    # Find high-value JSON data from plot_input_data
    for plot_data in report["plot_input_data"]:
        anchor = plot_data["anchor"]
        if (plot_data["sample_count"] > 10 and 
            plot_data["data_type"] in ["histogram_bar", "table_data"]):
            high_value_anchors.append((anchor, {
                "type": "json_structured", 
                "sample_count": plot_data["sample_count"],
                "data_type": plot_data["data_type"]
            }))
    
    for anchor, details in high_value_anchors[:10]:  # Top 10
        print(f"   • {anchor}")
        print(f"     └─ {details['sample_count']} samples, {details['type']} type")
    
    print(f"\n💾 SAVING COMPREHENSIVE REPORT")
    
    # Save full categorization
    categorization_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_categorization.json"
    with open(categorization_path, 'w') as f:
        json.dump(categorization, f, indent=2, default=str)
    print(f"   • Categorization: {categorization_path}")
    
    # Save code templates
    templates_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_extraction_templates.py"
    with open(templates_path, 'w') as f:
        f.write('"""\nMultiQC Data Extraction Templates\n"""\n\nimport polars as pl\nimport json\nfrom typing import Dict, List, Any\n\n')
        for template_name, template_code in templates.items():
            f.write(f"# {template_name.upper()} EXTRACTION\n")
            f.write(template_code)
            f.write("\n\n")
    print(f"   • Code templates: {templates_path}")
    
    print(f"\n✅ ANALYSIS COMPLETE")
    print(f"   • {len(categorization['anchor_categorization'])} anchors categorized")
    print(f"   • {len(high_value_anchors)} high-value targets identified")
    print(f"   • Ready for programmatic extraction module development")
    
    return categorization, templates

if __name__ == "__main__":
    categorization, templates = main()