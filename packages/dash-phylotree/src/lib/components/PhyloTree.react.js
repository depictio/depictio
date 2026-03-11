import React, { Component, createRef } from 'react';
import PropTypes from 'prop-types';

/**
 * PhyloTree is a Dash component that wraps react-phylogeny-tree
 * (Phylocanvas 3) for interactive phylogenetic tree visualization.
 *
 * Supports 5 tree layouts: rectangular, circular, radial, diagonal, hierarchical.
 * All props are JSON-serializable for Dash compatibility.
 */
class PhyloTree extends Component {
    constructor(props) {
        super(props);
        this.canvasRef = createRef();
        this.treeInstance = null;
        this.containerRef = createRef();
    }

    componentDidMount() {
        this._createTree();
    }

    componentDidUpdate(prevProps) {
        const {
            newick,
            treeType,
            nodeSize,
            fontSize,
            lineWidth,
            showLabels,
            alignLabels,
            styles,
        } = this.props;

        // Re-create tree if newick source changed
        if (prevProps.newick !== newick) {
            this._destroyTree();
            this._createTree();
            return;
        }

        if (!this.treeInstance) return;

        // Update tree type
        if (prevProps.treeType !== treeType) {
            this.treeInstance.setTreeType(treeType);
        }

        // Update visual state properties
        const stateUpdate = {};
        if (prevProps.nodeSize !== nodeSize) stateUpdate.nodeSize = nodeSize;
        if (prevProps.fontSize !== fontSize) stateUpdate.fontSize = fontSize;
        if (prevProps.lineWidth !== lineWidth) stateUpdate.lineWidth = lineWidth;
        if (prevProps.showLabels !== showLabels) {
            stateUpdate.renderLeafLabels = showLabels;
            stateUpdate.showLabels = showLabels;
        }
        if (prevProps.alignLabels !== alignLabels) {
            stateUpdate.alignLabels = alignLabels;
        }

        if (Object.keys(stateUpdate).length > 0) {
            this.treeInstance.setState(stateUpdate);
        }

        // Update node styles
        if (prevProps.styles !== styles && styles) {
            this.treeInstance.setStyles(styles);
        }
    }

    componentWillUnmount() {
        this._destroyTree();
    }

    _createTree() {
        const canvas = this.canvasRef.current;
        if (!canvas) return;

        const {
            newick,
            treeType,
            interactive,
            nodeSize,
            fontSize,
            lineWidth,
            showLabels,
            alignLabels,
            styles,
            setProps,
        } = this.props;

        if (!newick) return;

        // Size canvas to container
        const container = canvas.parentElement;
        if (container) {
            canvas.width = container.clientWidth;
            canvas.height = container.clientHeight;
        }

        // Dynamically import phylocanvas tree creator
        // react-phylogeny-tree uses @mkoliba/phylogeny-tree under the hood
        const { createTree } = require('@mkoliba/phylogeny-tree/index');

        const options = {
            source: newick,
            type: treeType || 'rectangular',
            nodeSize: nodeSize || 7,
            fontSize: fontSize || 10,
            lineWidth: lineWidth || 2,
            renderLeafLabels: showLabels !== false,
            showLabels: showLabels !== false,
            alignLabels: alignLabels || false,
            haloWidth: 2,
            highlightedStyle: '#34B6C7',
            haloStyle: '#34B6C7',
        };

        // Build plugins list
        const plugins = [];

        if (interactive) {
            try {
                const contextMenuPlugin =
                    require('@mkoliba/phylogeny-tree-plugin-context-menu/index').default ||
                    require('@mkoliba/phylogeny-tree-plugin-context-menu/index');
                const interactionsPlugin =
                    require('@mkoliba/phylogeny-tree-plugin-interactions/index').default ||
                    require('@mkoliba/phylogeny-tree-plugin-interactions/index');
                plugins.push(contextMenuPlugin, interactionsPlugin);
            } catch (e) {
                console.warn('Could not load phylocanvas interaction plugins:', e);
            }
        }

        // Selection plugin: sends selectedIds back to Dash via setProps
        if (setProps) {
            plugins.push(function onSelectPlugin(tree, decorate) {
                decorate('selectNode', function (delegate, args) {
                    delegate.apply(this, args);
                    const selectedIds = tree.state.selectedIds || [];
                    setProps({ selectedIds: [...selectedIds] });
                });
            });
        }

        try {
            this.treeInstance = createTree(canvas, options, plugins);

            // Apply initial styles if provided
            if (styles && this.treeInstance) {
                this.treeInstance.setStyles(styles);
            }
        } catch (e) {
            console.error('Failed to create phylogenetic tree:', e);
        }
    }

    _destroyTree() {
        if (this.treeInstance) {
            try {
                this.treeInstance.destroy();
            } catch (e) {
                // Ignore destroy errors
            }
            this.treeInstance = null;
        }
    }

    render() {
        const { id, width, height, showZoom } = this.props;

        const containerStyle = {
            width: width || '100%',
            height: height || '100%',
            position: 'relative',
            overflow: 'hidden',
        };

        return (
            <div id={id} ref={this.containerRef} style={containerStyle}>
                <canvas
                    ref={this.canvasRef}
                    style={{ position: 'absolute', top: 0, left: 0 }}
                />
                {showZoom && (
                    <div
                        style={{
                            position: 'absolute',
                            bottom: 10,
                            right: 10,
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 4,
                            zIndex: 10,
                        }}
                    >
                        <button
                            onClick={() => {
                                if (this.treeInstance) {
                                    this.treeInstance.transform(0, 0, 1);
                                }
                            }}
                            style={{
                                width: 32,
                                height: 32,
                                fontSize: 18,
                                cursor: 'pointer',
                                border: '1px solid #ccc',
                                borderRadius: 4,
                                background: '#fff',
                            }}
                        >
                            +
                        </button>
                        <button
                            onClick={() => {
                                if (this.treeInstance) {
                                    this.treeInstance.transform(0, 0, -1);
                                }
                            }}
                            style={{
                                width: 32,
                                height: 32,
                                fontSize: 18,
                                cursor: 'pointer',
                                border: '1px solid #ccc',
                                borderRadius: 4,
                                background: '#fff',
                            }}
                        >
                            −
                        </button>
                    </div>
                )}
            </div>
        );
    }
}

PhyloTree.defaultProps = {
    treeType: 'rectangular',
    interactive: true,
    showZoom: true,
    nodeSize: 7,
    fontSize: 10,
    lineWidth: 2,
    showLabels: true,
    alignLabels: false,
    selectedIds: [],
    styles: {},
    width: '100%',
    height: '100%',
};

PhyloTree.propTypes = {
    /**
     * The ID used to identify this component in Dash callbacks.
     */
    id: PropTypes.string,

    /**
     * Newick format tree string.
     */
    newick: PropTypes.string.isRequired,

    /**
     * Tree layout type: rectangular, circular, radial, diagonal, hierarchical.
     */
    treeType: PropTypes.oneOf([
        'rectangular',
        'circular',
        'radial',
        'diagonal',
        'hierarchical',
    ]),

    /**
     * Enable interactive features (pan, zoom, selection, context menu).
     */
    interactive: PropTypes.bool,

    /**
     * Show zoom +/- buttons.
     */
    showZoom: PropTypes.bool,

    /**
     * Node marker size.
     */
    nodeSize: PropTypes.number,

    /**
     * Label font size.
     */
    fontSize: PropTypes.number,

    /**
     * Branch line width.
     */
    lineWidth: PropTypes.number,

    /**
     * Show leaf labels.
     */
    showLabels: PropTypes.bool,

    /**
     * Align leaf labels to tree edge.
     */
    alignLabels: PropTypes.bool,

    /**
     * Currently selected node IDs. Updated on user selection.
     */
    selectedIds: PropTypes.arrayOf(PropTypes.string),

    /**
     * Per-node styles: {nodeId: {fillStyle: '#color', shape: 'circle'}}.
     */
    styles: PropTypes.object,

    /**
     * CSS width of the component.
     */
    width: PropTypes.string,

    /**
     * CSS height of the component.
     */
    height: PropTypes.string,

    /**
     * Dash-assigned callback that should be called to report property changes
     * to Dash, to make them available for callbacks.
     */
    setProps: PropTypes.func,
};

export default PhyloTree;
