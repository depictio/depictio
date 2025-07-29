# Dash Dynamic Grid Layout Prototypes

This directory contains prototypes using `dash-dynamic-grid-layout` - a modern, actively maintained Dash component for creating draggable grid layouts. This approach provides native Dash integration and solves many of the issues we encountered with `dash-draggable`.

## 🚀 Why dash-dynamic-grid-layout?

### Advantages over dash-draggable:
- **Native Dash Component**: Built specifically for Dash applications
- **Active Maintenance**: Actively maintained and updated
- **Modern React**: Uses modern React patterns and hooks
- **Responsive Design**: Built-in responsive breakpoints
- **Better Performance**: Optimized for Dash's component model
- **UUID Preservation**: No complex mapping systems needed
- **Built-in Edit Controls**: Native support for remove buttons and resize handles

### Comparison with react-grid-layout prototypes:
- **Dash Native**: No clientside callbacks or external JS libraries
- **Better Integration**: Seamless integration with Dash callbacks
- **Easier Maintenance**: Pure Python implementation
- **Component Model**: Uses Dash's component architecture properly

## 📁 Files

### `version1_basic.py`
**Basic implementation with edit mode toggle**
- Three different component types (text, graph, interactive)
- Edit mode toggle to show/hide remove buttons and resize handles
- Layout persistence and display
- Responsive breakpoints
- UUID preservation

**To run:**
```bash
python version1_basic.py
```
**URL:** http://localhost:8083

### `version2_depictio_integration.py`
**Advanced integration with depictio's edit system**
- Integration with depictio's `enable_box_edit_mode` function
- Components have depictio's edit/duplicate/delete buttons
- Different component types (figure, table, interactive)
- Grid edit mode toggle (separate from depictio edit buttons)
- Proper component dimensions based on type
- Layout persistence and display

**To run:**
```bash
python version2_depictio_integration.py
```
**URL:** http://localhost:8084

## 🎯 Key Features

### Edit Mode Control
Both versions support edit mode toggling:
- **Grid Edit Mode**: Shows/hides remove buttons and resize handles
- **Depictio Edit Mode**: (Version 2) Shows depictio's edit controls within components

### Component Types
- **Figure Components**: Larger default size (6x4 grid units)
- **Table Components**: Larger default size (6x4 grid units)  
- **Interactive Components**: Smaller default size (5x3 grid units)

### Layout Persistence
- Real-time layout updates
- Visual display of current layout
- JSON export capability
- Responsive breakpoint handling

## 🔧 Technical Details

### Grid Configuration
```python
cols={'lg': 12, 'md': 10, 'sm': 6, 'xs': 4, 'xxs': 2}
breakpoints={'lg': 1200, 'md': 996, 'sm': 768, 'xs': 480, 'xxs': 0}
rowHeight=120  # Adjustable based on content needs
```

### Component Structure
```python
dgl.DraggableWrapper(
    children=[
        html.Div(content, style=styling)
    ],
    handleText='Move Component'
)
```

### Edit Mode Integration
```python
@app.callback(
    [Output("grid-layout", "showRemoveButton"),
     Output("grid-layout", "showResizeHandles")],
    Input("edit-mode-store", "data")
)
def update_grid_edit_mode(edit_mode_enabled):
    return edit_mode_enabled, edit_mode_enabled
```

## 🧪 Testing Checklist

### Basic Functionality
- [ ] Components load correctly
- [ ] Drag and drop works smoothly
- [ ] Resize handles function properly
- [ ] Edit mode toggle works
- [ ] Layout persistence works

### Version 1 Specific
- [ ] Three component types display correctly
- [ ] Edit mode shows/hides controls
- [ ] Layout display updates in real-time
- [ ] Responsive breakpoints work

### Version 2 Specific
- [ ] Depictio integration works
- [ ] Edit/duplicate/delete buttons appear
- [ ] Component extraction from DashboardItem works
- [ ] Fallback components work if integration fails

## 📊 Performance Comparison

| Feature | dash-draggable | react-grid-layout | dash-dynamic-grid-layout |
|---------|----------------|-------------------|--------------------------|
| Dash Native | ❌ | ❌ | ✅ |
| UUID Preservation | ⚠️ Complex | ✅ | ✅ |
| Edit Mode | ⚠️ Custom | ⚠️ Custom | ✅ Built-in |
| Responsive | ❌ | ✅ | ✅ |
| Maintenance | ❌ Stale | ✅ Active | ✅ Active |
| Performance | ⚠️ Slow | ✅ Fast | ✅ Fast |

## 🚀 Next Steps

1. **Test both versions** in browser
2. **Verify depictio integration** works correctly
3. **Customize styling** to match depictio theme
4. **Add more component types** if needed
5. **Implement in main depictio codebase**
6. **Add persistence** to backend storage
7. **Add keyboard shortcuts** for better UX

## 🔍 Browser Testing

### Console Commands
```javascript
// Check current layout
console.log(sessionStorage.getItem('dash-dynamic-grid-layout'));

// Monitor layout changes
window.addEventListener('storage', (e) => {
    if (e.key === 'dash-dynamic-grid-layout') {
        console.log('Layout changed:', e.newValue);
    }
});
```

### Developer Tools
1. Open browser developer tools (F12)
2. Check **Console** for initialization logs
3. Test **drag and drop** functionality
4. Check **Application > Session Storage** for layout data
5. Test **responsive breakpoints** by resizing window
6. **Refresh page** to verify persistence

## 💡 Implementation Notes

### For Integration into Depictio
1. Replace `dash-draggable` imports with `dash-dynamic-grid-layout`
2. Update component creation to use `DraggableWrapper`
3. Add responsive breakpoint configuration
4. Implement edit mode toggle in dashboard settings
5. Update layout persistence to use new format
6. Add theme integration for consistent styling

### Recommended Configuration
```python
# Optimal settings for depictio integration
rowHeight=100  # Good for most component types
cols={'lg': 12, 'md': 10, 'sm': 6, 'xs': 4, 'xxs': 2}
compactType='vertical'  # Better for dashboard layouts
showRemoveButton=False  # Control via edit mode
showResizeHandles=False  # Control via edit mode
```