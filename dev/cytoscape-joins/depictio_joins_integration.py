#!/usr/bin/env python3
"""
Depictio Data Collection Joins Integration

This module provides functions to integrate the cytoscape joins visualization
with real Depictio data collections and join configurations.
"""

import asyncio
from typing import Any

import httpx
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.datacollections_endpoints.utils import generate_join_dict
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.projects import Project
from depictio.models.models.workflows import Workflow


async def fetch_project_data_collections_with_joins(project_id: str, token: str) -> dict[str, Any]:
    """
    Fetch project data collections with their join configurations.
    
    Args:
        project_id: Project ID to fetch
        token: Authentication token
        
    Returns:
        Dictionary containing project data and processed join information
    """
    try:
        # Fetch project data
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
                headers={"Authorization": f"Bearer {token}"},
                params={"project_id": project_id},
                timeout=settings.performance.api_request_timeout,
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch project {project_id}: {response.status_code}")
                return {}
                
            project_data = response.json()
            project = Project.model_validate(project_data)
            
        # Process data collections and joins
        processed_data = {
            "project": {
                "id": project_id,
                "name": project.name,
                "type": project.project_type
            },
            "data_collections": [],
            "joins": {},
            "workflows": []
        }
        
        # Process workflows and their data collections
        for workflow in project.workflows:
            workflow_data = {
                "id": str(workflow.id),
                "name": workflow.name,
                "data_collections": []
            }
            
            # Generate join dictionary for this workflow
            workflow_dict = workflow.model_dump()
            joins_dict = generate_join_dict(workflow_dict)
            processed_data["joins"].update(joins_dict)
            
            # Process data collections in this workflow
            for dc in workflow.data_collections:
                if dc.config.type.lower() == "table":  # Only process table data collections
                    # Fetch column specifications
                    try:
                        async with httpx.AsyncClient() as client:
                            specs_response = await client.get(
                                f"{API_BASE_URL}/depictio/api/v1/deltatables/specs/{dc.id}",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=settings.performance.api_request_timeout,
                            )
                            
                            columns = []
                            if specs_response.status_code == 200:
                                specs_data = specs_response.json()
                                # Extract column names from specifications
                                columns = list(specs_data.keys()) if specs_data else []
                            else:
                                logger.warning(f"Could not fetch specs for DC {dc.id}")
                                # Fallback: use keep_columns if available
                                if hasattr(dc.config.dc_specific_properties, 'keep_columns'):
                                    columns = dc.config.dc_specific_properties.keep_columns or []
                                
                    except Exception as e:
                        logger.error(f"Error fetching column specs for DC {dc.id}: {e}")
                        columns = []
                    
                    dc_data = {
                        "id": str(dc.id),
                        "name": dc.data_collection_tag,
                        "tag": dc.data_collection_tag,
                        "type": dc.config.type,
                        "metatype": dc.config.metatype,
                        "columns": columns,
                        "workflow_id": str(workflow.id),
                        "workflow_name": workflow.name,
                        "joins": []
                    }
                    
                    # Add join configuration if present
                    if dc.config.join:
                        join_config = {
                            "on_columns": dc.config.join.on_columns,
                            "how": dc.config.join.how,
                            "with_dc": dc.config.join.with_dc
                        }
                        dc_data["joins"].append(join_config)
                    
                    workflow_data["data_collections"].append(dc_data)
                    processed_data["data_collections"].append(dc_data)
            
            processed_data["workflows"].append(workflow_data)
        
        # Also handle basic projects with direct data collections
        if project.project_type == "basic" and project.data_collections:
            for dc in project.data_collections:
                if dc.config.type.lower() == "table":
                    # Similar processing for direct data collections
                    try:
                        async with httpx.AsyncClient() as client:
                            specs_response = await client.get(
                                f"{API_BASE_URL}/depictio/api/v1/deltatables/specs/{dc.id}",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=settings.performance.api_request_timeout,
                            )
                            
                            columns = []
                            if specs_response.status_code == 200:
                                specs_data = specs_response.json()
                                columns = list(specs_data.keys()) if specs_data else []
                                
                    except Exception as e:
                        logger.error(f"Error fetching column specs for DC {dc.id}: {e}")
                        columns = []
                    
                    dc_data = {
                        "id": str(dc.id),
                        "name": dc.data_collection_tag,
                        "tag": dc.data_collection_tag,
                        "type": dc.config.type,
                        "metatype": dc.config.metatype,
                        "columns": columns,
                        "workflow_id": None,
                        "workflow_name": None,
                        "joins": []
                    }
                    
                    if dc.config.join:
                        join_config = {
                            "on_columns": dc.config.join.on_columns,
                            "how": dc.config.join.how,
                            "with_dc": dc.config.join.with_dc
                        }
                        dc_data["joins"].append(join_config)
                    
                    processed_data["data_collections"].append(dc_data)
        
        return processed_data
        
    except Exception as e:
        logger.error(f"Error fetching project data collections: {e}")
        return {}


def generate_cytoscape_elements_from_depictio_data(project_data: dict[str, Any], theme: str = "light") -> list[dict]:
    """
    Generate cytoscape elements from Depictio project data.
    
    Args:
        project_data: Processed project data from fetch_project_data_collections_with_joins
        theme: "light" or "dark" theme
        
    Returns:
        List of cytoscape elements (nodes and edges)
    """
    elements = []
    data_collections = project_data.get("data_collections", [])
    joins_dict = project_data.get("joins", {})
    
    if not data_collections:
        return elements
    
    # Group data collections by workflow for better layout
    workflow_groups = {}
    standalone_dcs = []
    
    for dc in data_collections:
        workflow_id = dc.get("workflow_id")
        if workflow_id:
            if workflow_id not in workflow_groups:
                workflow_groups[workflow_id] = {
                    "name": dc.get("workflow_name", "Unknown Workflow"),
                    "data_collections": []
                }
            workflow_groups[workflow_id]["data_collections"].append(dc)
        else:
            standalone_dcs.append(dc)
    
    # Create elements for each workflow group
    workflow_counter = 0
    for workflow_id, workflow_info in workflow_groups.items():
        x_base = workflow_counter * 400
        
        # Create workflow group (optional visual grouping)
        elements.append({
            "data": {
                "id": f"workflow_group_{workflow_id}",
                "label": f"Workflow: {workflow_info['name']}",
                "type": "workflow_group"
            },
            "position": {"x": x_base + 200, "y": 30},
            "classes": "workflow-group"
        })
        
        # Create data collection groups and column nodes within this workflow
        for i, dc in enumerate(workflow_info["data_collections"]):
            dc_id = dc["id"]
            dc_name = dc["name"]
            dc_tag = dc["tag"]
            columns = dc["columns"]
            
            x_offset = x_base + (i * 250)
            y_base = 100
            
            # Create data collection group
            elements.append({
                "data": {
                    "id": f"dc_group_{dc_id}",
                    "label": f"{dc_name}\n[{dc.get('metatype', 'table')}]",
                    "parent": f"workflow_group_{workflow_id}",
                    "type": "data_collection",
                    "dc_tag": dc_tag,
                    "dc_id": dc_id
                },
                "position": {"x": x_offset, "y": y_base},
                "classes": "data-collection-group"
            })
            
            # Create column nodes
            for j, column in enumerate(columns):
                column_id = f"{dc_tag}_{column}"
                y_offset = y_base + 50 + (j * 40)
                
                # Determine if this column is part of a join
                is_join_column = any(
                    column in join.get("on_columns", [])
                    for join in dc.get("joins", [])
                )
                
                elements.append({
                    "data": {
                        "id": column_id,
                        "label": column,
                        "parent": f"dc_group_{dc_id}",
                        "type": "column",
                        "dc_tag": dc_tag,
                        "dc_name": dc_name,
                        "dc_id": dc_id,
                        "workflow_id": workflow_id,
                        "is_join_column": is_join_column
                    },
                    "position": {"x": x_offset, "y": y_offset},
                    "classes": "column-node join-column" if is_join_column else "column-node"
                })
        
        workflow_counter += 1
    
    # Handle standalone data collections (for basic projects)
    for i, dc in enumerate(standalone_dcs):
        dc_id = dc["id"]
        dc_name = dc["name"]
        dc_tag = dc["tag"]
        columns = dc["columns"]
        
        x_offset = len(workflow_groups) * 400 + (i * 250)
        y_base = 100
        
        elements.append({
            "data": {
                "id": f"dc_group_{dc_id}",
                "label": f"{dc_name}\n[{dc.get('metatype', 'table')}]",
                "type": "data_collection",
                "dc_tag": dc_tag,
                "dc_id": dc_id
            },
            "position": {"x": x_offset, "y": y_base},
            "classes": "data-collection-group"
        })
        
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}_{column}"
            y_offset = y_base + 50 + (j * 40)
            
            is_join_column = any(
                column in join.get("on_columns", [])
                for join in dc.get("joins", [])
            )
            
            elements.append({
                "data": {
                    "id": column_id,
                    "label": column,
                    "parent": f"dc_group_{dc_id}",
                    "type": "column",
                    "dc_tag": dc_tag,
                    "dc_name": dc_name,
                    "dc_id": dc_id,
                    "is_join_column": is_join_column
                },
                "position": {"x": x_offset, "y": y_offset},
                "classes": "column-node join-column" if is_join_column else "column-node"
            })
    
    # Create edges from join configurations
    edge_counter = 0
    for dc in data_collections:
        dc_tag = dc["tag"]
        
        for join in dc.get("joins", []):
            on_columns = join["on_columns"]
            join_type = join["how"]
            target_dc_tags = join["with_dc"]
            
            for target_dc_tag in target_dc_tags:
                # Find the target data collection
                target_dc = next((d for d in data_collections if d["tag"] == target_dc_tag), None)
                if not target_dc:
                    continue
                
                # Create edges between matching columns
                for col in on_columns:
                    source_node = f"{dc_tag}_{col}"
                    
                    # For now, assume same column name for joins
                    # This could be enhanced with proper column mapping
                    target_col = col
                    target_node = f"{target_dc_tag}_{target_col}"
                    
                    # Check if both nodes exist
                    source_exists = any(e["data"]["id"] == source_node for e in elements if e["data"].get("type") == "column")
                    target_exists = any(e["data"]["id"] == target_node for e in elements if e["data"].get("type") == "column")
                    
                    if source_exists and target_exists:
                        elements.append({
                            "data": {
                                "id": f"edge_{edge_counter}",
                                "source": source_node,
                                "target": target_node,
                                "label": f"{join_type}",
                                "join_type": join_type,
                                "join_column": col
                            },
                            "classes": f"join-edge join-{join_type}"
                        })
                        edge_counter += 1
    
    return elements


def get_enhanced_cytoscape_stylesheet(theme: str = "light") -> list[dict]:
    """
    Get enhanced cytoscape stylesheet with Depictio-specific styling.
    
    Args:
        theme: "light" or "dark" theme
        
    Returns:
        List of cytoscape style dictionaries
    """
    # Import Depictio colors
    from depictio.dash.colors import colors as depictio_colors
    
    # Theme-specific colors
    if theme == "light":
        bg_color = "#ffffff"
        text_color = "#212529"
        border_color = "#dee2e6"
        group_bg = "#f8f9fa"
        node_bg = "#e3f2fd"
        node_border = depictio_colors["blue"]
        join_edge = depictio_colors["orange"]
        workflow_bg = "#fff3e0"
    else:
        bg_color = "#121212"
        text_color = "#ffffff"
        border_color = "#404040"
        group_bg = "#1e1e1e"
        node_bg = "#263238"
        node_border = depictio_colors["blue"]
        join_edge = depictio_colors["orange"]
        workflow_bg = "#2d2d2d"
    
    return [
        # Workflow group styling
        {
            "selector": ".workflow-group",
            "style": {
                "background-color": workflow_bg,
                "border-color": border_color,
                "border-width": 1,
                "border-style": "dashed",
                "label": "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "color": text_color,
                "font-size": "16px",
                "font-weight": "bold",
                "padding": "15px",
                "shape": "round-rectangle",
                "width": "350px",
                "height": "auto",
                "opacity": 0.3
            }
        },
        
        # Data collection group styling
        {
            "selector": ".data-collection-group",
            "style": {
                "background-color": group_bg,
                "border-color": border_color,
                "border-width": 2,
                "border-style": "solid",
                "label": "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "color": text_color,
                "font-size": "14px",
                "font-weight": "bold",
                "padding": "10px",
                "shape": "round-rectangle",
                "width": "180px",
                "height": "auto"
            }
        },
        
        # Regular column nodes
        {
            "selector": ".column-node",
            "style": {
                "background-color": node_bg,
                "border-color": node_border,
                "border-width": 1,
                "border-style": "solid",
                "label": "data(label)",
                "color": text_color,
                "text-valign": "center",
                "text-halign": "center",
                "font-size": "11px",
                "width": "140px",
                "height": "25px",
                "shape": "round-rectangle"
            }
        },
        
        # Join column nodes (highlighted)
        {
            "selector": ".join-column",
            "style": {
                "border-width": 2,
                "border-color": join_edge,
                "background-color": f"{join_edge}20",  # Semi-transparent
                "font-weight": "bold"
            }
        },
        
        # Join edges
        {
            "selector": ".join-edge",
            "style": {
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "target-arrow-color": join_edge,
                "line-color": join_edge,
                "line-style": "solid",
                "width": 3,
                "label": "data(label)",
                "font-size": "10px",
                "color": text_color,
                "text-rotation": "autorotate",
                "text-margin-y": -15,
                "text-background-color": bg_color,
                "text-background-opacity": 0.8,
                "text-background-padding": "2px"
            }
        },
        
        # Different join types
        {
            "selector": ".join-inner",
            "style": {
                "line-style": "solid",
                "width": 4
            }
        },
        
        {
            "selector": ".join-left",
            "style": {
                "line-style": "dashed",
                "width": 3
            }
        },
        
        {
            "selector": ".join-right", 
            "style": {
                "line-style": "dotted",
                "width": 3
            }
        },
        
        {
            "selector": ".join-outer",
            "style": {
                "line-style": "solid",
                "width": 2,
                "line-cap": "round"
            }
        },
        
        # Hover effects
        {
            "selector": ".column-node:hover",
            "style": {
                "border-width": 3,
                "scale": 1.1
            }
        },
        
        # Selected styling
        {
            "selector": ":selected",
            "style": {
                "border-width": 4,
                "border-color": depictio_colors["pink"],
                "scale": 1.2
            }
        }
    ]


# Example usage function
async def create_joins_visualization_data(project_id: str, token: str, theme: str = "light") -> dict[str, Any]:
    """
    Create complete data structure for cytoscape joins visualization.
    
    Args:
        project_id: Project ID to visualize
        token: Authentication token
        theme: Theme for styling
        
    Returns:
        Dictionary with elements, stylesheet, and metadata
    """
    # Fetch project data
    project_data = await fetch_project_data_collections_with_joins(project_id, token)
    
    if not project_data:
        return {
            "elements": [],
            "stylesheet": get_enhanced_cytoscape_stylesheet(theme),
            "metadata": {"error": "Failed to fetch project data"}
        }
    
    # Generate cytoscape elements
    elements = generate_cytoscape_elements_from_depictio_data(project_data, theme)
    stylesheet = get_enhanced_cytoscape_stylesheet(theme)
    
    return {
        "elements": elements,
        "stylesheet": stylesheet,
        "metadata": {
            "project": project_data["project"],
            "data_collections_count": len(project_data["data_collections"]),
            "workflows_count": len(project_data["workflows"]),
            "joins_count": len([dc for dc in project_data["data_collections"] if dc.get("joins")])
        }
    }