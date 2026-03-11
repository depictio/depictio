"""Auto-generated Python wrapper for the PhyloTree Dash component."""

from dash.development.base_component import Component


class PhyloTree(Component):
    """A PhyloTree component.

    Renders an interactive phylogenetic tree using Phylocanvas 3
    (via react-phylogeny-tree). Supports 5 tree layouts:
    rectangular, circular, radial, diagonal, hierarchical.

    Keyword arguments:

    - id (string; optional):
        The ID used to identify this component in Dash callbacks.

    - newick (string; required):
        Newick format tree string.

    - treeType (string; default 'rectangular'):
        Tree layout type. One of: rectangular, circular, radial,
        diagonal, hierarchical.

    - interactive (boolean; default True):
        Enable interactive features (pan, zoom, selection, context menu).

    - showZoom (boolean; default True):
        Show zoom +/- buttons.

    - nodeSize (number; default 7):
        Node marker size.

    - fontSize (number; default 10):
        Label font size.

    - lineWidth (number; default 2):
        Branch line width.

    - showLabels (boolean; default True):
        Show leaf labels.

    - alignLabels (boolean; default False):
        Align leaf labels to tree edge.

    - selectedIds (list of strings; default []):
        Currently selected node IDs. Updated on user selection.

    - styles (dict; default {}):
        Per-node styles: {nodeId: {fillStyle: '#color', shape: 'circle'}}.

    - width (string; default '100%'):
        CSS width of the component.

    - height (string; default '100%'):
        CSS height of the component.
    """

    _children_props = []
    _base_nodes = ["children"]
    _namespace = "dash_phylotree"
    _type = "PhyloTree"

    @staticmethod
    def _prop_names():
        return [
            "id",
            "newick",
            "treeType",
            "interactive",
            "showZoom",
            "nodeSize",
            "fontSize",
            "lineWidth",
            "showLabels",
            "alignLabels",
            "selectedIds",
            "styles",
            "width",
            "height",
        ]

    @staticmethod
    def _valid_wildcard_attributes():
        return []

    available_properties = [
        "id",
        "newick",
        "treeType",
        "interactive",
        "showZoom",
        "nodeSize",
        "fontSize",
        "lineWidth",
        "showLabels",
        "alignLabels",
        "selectedIds",
        "styles",
        "width",
        "height",
    ]

    available_wildcard_properties = []

    def __init__(
        self,
        id=Component.UNDEFINED,
        newick=Component.REQUIRED,
        treeType=Component.UNDEFINED,
        interactive=Component.UNDEFINED,
        showZoom=Component.UNDEFINED,
        nodeSize=Component.UNDEFINED,
        fontSize=Component.UNDEFINED,
        lineWidth=Component.UNDEFINED,
        showLabels=Component.UNDEFINED,
        alignLabels=Component.UNDEFINED,
        selectedIds=Component.UNDEFINED,
        styles=Component.UNDEFINED,
        width=Component.UNDEFINED,
        height=Component.UNDEFINED,
        **kwargs,
    ):
        self._prop_names = self.__class__._prop_names()
        self._valid_wildcard_attributes = self.__class__._valid_wildcard_attributes()
        self.available_properties = self.__class__.available_properties
        self.available_wildcard_properties = self.__class__.available_wildcard_properties

        _explicit_args = {
            k: v
            for k, v in {
                "id": id,
                "newick": newick,
                "treeType": treeType,
                "interactive": interactive,
                "showZoom": showZoom,
                "nodeSize": nodeSize,
                "fontSize": fontSize,
                "lineWidth": lineWidth,
                "showLabels": showLabels,
                "alignLabels": alignLabels,
                "selectedIds": selectedIds,
                "styles": styles,
                "width": width,
                "height": height,
            }.items()
            if v is not Component.UNDEFINED
        }

        for k in ["newick"]:
            if k not in _explicit_args:
                raise TypeError(f"Required argument `{k}` was not specified.")

        super().__init__(**_explicit_args)
