# Cytoscape Data Collection Joins Visualization Prototype

This prototype demonstrates a network visualization of data collection joins using Dash Cytoscape, designed to be integrated into the Depictio data collections management interface.

## Features

### 🎯 Core Functionality
- **Network Visualization**: Each data collection appears as a grouped cluster
- **Column Representation**: Individual columns within data collections are shown as nodes
- **Join Visualization**: Edges connect joined columns across different data collections
- **Interactive Interface**: Click, drag, zoom, and explore the relationship graph

### 🎨 Theme Support
- **Light/Dark Modes**: Fully theme-aware styling compatible with Depictio's theme system
- **Dynamic Switching**: Toggle between themes without losing layout or selections
- **Consistent Colors**: Uses theme-appropriate colors for nodes, edges, and backgrounds

### 🔧 Interactive Controls
- **Theme Toggle**: Switch between light and dark modes
- **Reset Layout**: Restore nodes to their original positions
- **Fit to View**: Auto-center and scale the graph to fit the viewport
- **Node Selection**: Click nodes to see detailed information

## Data Structure

The prototype expects data collections in this format:

```python
{
    "id": "dc1",
    "name": "Users", 
    "tag": "users_table",
    "columns": ["user_id", "name", "email", "department_id"],
    "joins": [
        {
            "on_columns": ["department_id"],
            "how": "left",
            "with_dc": ["departments_table"]
        }
    ]
}
```

## Visual Elements

### Data Collection Groups
- **Representation**: Rounded rectangles containing column nodes
- **Styling**: Theme-appropriate background and borders
- **Labels**: Show both display name and technical tag

### Column Nodes  
- **Representation**: Smaller rounded rectangles within data collection groups
- **Interaction**: Hover effects and selection highlighting
- **Information**: Display column name and parent data collection details

### Join Edges
- **Representation**: Curved arrows connecting related columns
- **Labels**: Show join type (inner, left, right, outer)
- **Styling**: Theme-aware colors with clear visual hierarchy

## Integration Notes

### Extending for Real Data
To integrate with real Depictio data:

1. **Data Source**: Replace `SAMPLE_DATA_COLLECTIONS` with API calls to fetch real project data collections
2. **Join Logic**: Enhance column matching logic to handle complex join mappings  
3. **Delta Table Info**: Integrate with delta table specifications for accurate column information
4. **User Permissions**: Add authentication and permission checks for data access

### API Integration Points
- `depictio/api/v1/endpoints/datacollections_endpoints/routes.py` - Column specifications
- `depictio/api/v1/endpoints/datacollections_endpoints/utils.py` - Join relationship logic
- `depictio/models/models/data_collections.py` - Data collection and join models

### UI Integration 
- Add as a new tab/section in the project data collections management interface
- Use existing Depictio theme system and color palette
- Integrate with existing project authentication and routing

## Running the Prototype

```bash
cd dev/cytoscape-joins
python cytoscape_joins_prototype.py
```

Visit `http://localhost:8051` to see the visualization.

## Next Steps

1. **Real Data Integration**: Connect to actual project data collections via API
2. **Enhanced Join Logic**: Support complex column mappings and multiple join types  
3. **Layout Algorithms**: Add automatic layout options (hierarchical, circular, etc.)
4. **Export Features**: Allow exporting the graph as images or data
5. **Performance**: Optimize for large numbers of data collections and columns
6. **Accessibility**: Add keyboard navigation and screen reader support

## Technical Details

- **Frontend**: Dash + Dash Cytoscape + Dash Mantine Components
- **Styling**: Theme-aware CSS with dark/light mode support
- **Layout**: Preset positioning with manual override capabilities
- **Interactions**: Node selection, drag-and-drop, zoom/pan
- **Responsive**: Adapts to different screen sizes