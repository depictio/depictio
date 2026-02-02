"""
Image Component Utility Functions.

Provides helper functions for image URL construction, format validation,
and image component building.
"""

import mimetypes
import urllib.parse
from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html

# Supported image extensions (shared constant)
SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"]
)


def build_image_url(relative_path: str, base_s3_folder: str, api_base_url: str) -> str:
    """Build API URL for image serving."""
    full_s3_path = f"{base_s3_folder.rstrip('/')}/{relative_path}"
    encoded_path = urllib.parse.quote(full_s3_path, safe="")
    return f"{api_base_url}/depictio/api/v1/files/serve/image?s3_path={encoded_path}"


def get_image_mime_type(file_path: str) -> str:
    """Get MIME type for an image file based on extension."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def is_supported_image_format(file_path: str) -> bool:
    """Check if a file path has a supported image extension."""
    if not file_path:
        return False
    lower_path = file_path.lower()
    return any(lower_path.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)


def build_image_frame(index: str, children: Any = None, show_border: bool = False) -> dmc.Paper:
    """Build the frame/container for an image component."""
    loading_overlay = dmc.LoadingOverlay(
        id={"type": "image-loading-overlay", "index": index},
        visible=False,
        overlayProps={"radius": "sm", "blur": 2},
        loaderProps={"type": "dots", "size": "lg"},
        zIndex=10,
        style={"display": "none"},
    )

    if children:
        body = html.Div(
            children=children,
            id={"type": "image-body", "index": index},
            style={"height": "100%", "width": "100%"},
        )
        padding = "xs"
    else:
        body = dmc.Center(
            dmc.Text(
                "Configure your image gallery using the edit menu",
                size="sm",
                c="gray",
                fs="italic",
                ta="center",
            ),
            id={"type": "image-body", "index": index},
            style={"minHeight": "200px", "height": "100%", "minWidth": "200px"},
        )
        padding = "md"

    return dmc.Paper(
        children=[loading_overlay, body],
        id={"type": "image-component", "index": index},
        pos="relative",
        withBorder=show_border,
        radius="sm",
        p=padding,
        style={"width": "100%", "height": "100%", "margin": "0"},
    )


def build_image(**kwargs) -> dmc.Paper:
    """
    Build image gallery component with pattern-matching callback architecture.

    The actual image grid is populated by callbacks that fetch data and render images.
    """
    # Extract parameters with defaults
    index = kwargs.get("index")
    title = kwargs.get("title", "Image Gallery")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    image_column = kwargs.get("image_column")
    s3_base_folder = kwargs.get("s3_base_folder")
    thumbnail_size = kwargs.get("thumbnail_size", 150)
    columns = kwargs.get("columns", 4)
    max_images = kwargs.get("max_images", 20)
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    project_id = kwargs.get("project_id")

    # Handle stepper mode index suffixing
    if stepper and index and not str(index).endswith("-tmp"):
        index = f"{index}-tmp"

    # Determine indices for stores
    index_str = str(index) if index else "unknown"
    store_index = index_str if stepper else index_str.replace("-tmp", "")
    data_index = index_str.replace("-tmp", "") if stepper else store_index

    # Metadata store for dashboard save/restore
    metadata = {
        "index": data_index,
        "component_type": "image",
        "title": title,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "project_id": project_id,
        "image_column": image_column,
        "s3_base_folder": s3_base_folder,
        "thumbnail_size": thumbnail_size,
        "columns": columns,
        "max_images": max_images,
    }

    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": store_index},
        data=metadata,
    )

    # Trigger store for async rendering
    trigger_data = {
        "wf_id": wf_id,
        "dc_id": dc_id,
        "image_column": image_column,
        "s3_base_folder": s3_base_folder,
        "thumbnail_size": thumbnail_size,
        "columns": columns,
        "max_images": max_images,
        "title": title,
        "stepper": stepper,
    }

    trigger_store = dcc.Store(
        id={"type": "image-trigger", "index": index_str},
        data=trigger_data,
    )

    # Image grid with scrollable container
    grid_container = html.Div(
        dmc.SimpleGrid(
            id={"type": "image-grid", "index": index_str},
            cols=columns,
            spacing="md",
            children=[dmc.Center(dmc.Loader(type="dots", size="lg"), style={"padding": "2rem"})],
        ),
        className="image-grid-container",
        style={
            "maxHeight": "600px",
            "overflowY": "auto",
            "overflowX": "hidden",
            "minHeight": "200px",
            "padding": "4px",
        },
    )

    # Modal for full-screen image viewing
    modal = dmc.Modal(
        id={"type": "image-modal", "index": index_str},
        size="xl",
        centered=True,
        withCloseButton=True,
        children=[
            html.Img(
                id={"type": "image-modal-img", "index": index_str},
                style={
                    "maxWidth": "100%",
                    "maxHeight": "80vh",
                    "objectFit": "contain",
                    "display": "block",
                    "margin": "0 auto",
                },
            ),
            dmc.Text(
                id={"type": "image-modal-title", "index": index_str},
                ta="center",
                mt="md",
                c="dimmed",
            ),
        ],
    )

    # Assemble content
    content_children = []
    if title:
        content_children.append(dmc.Text(title, size="lg", fw="bold", mb="xs"))
    content_children.extend([grid_container, modal, store_component, trigger_store])

    image_content = dmc.Stack(content_children, gap="sm", style={"height": "100%"})

    if build_frame:
        return build_image_frame(index=index, children=image_content, show_border=stepper)

    return dmc.Paper(
        children=image_content,
        id={"type": "image-card", "index": index_str},
        withBorder=True,
        shadow="sm",
        p="md",
        radius="sm",
        style={"height": "100%", "minHeight": "300px"},
    )
