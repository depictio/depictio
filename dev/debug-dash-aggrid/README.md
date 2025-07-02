# AG Grid Debug App

## Purpose
This debug app isolates and reproduces the AG Grid issues from `projectwise_user_management.py`:
- `Cannot read properties of undefined (reading 'is_loading')` error
- Crashes during component initialization
- Callback loop problems

## What it tests
1. **Different permission states**: Admin, Owner, Viewer, Empty grid
2. **AG Grid initialization**: Exact same props as the problematic component
3. **Cell value changes**: Callback handling that was causing loops
4. **Loading states**: To identify what `is_loading` property is missing

## How to run

```bash
cd /Users/tweber/Gits/workspaces/depictio-workspace/depictio
python dev/debug-dash-aggrid/debug_app.py
```

Then open: http://localhost:8052

## What to look for

### In the browser console:
- Any `Cannot read properties of undefined (reading 'is_loading')` errors
- Any `node.className.includes is not a function` errors
- AG Grid internal errors

### In the terminal:
- Detailed logging of callback executions
- Column definition creation
- Grid option changes
- Cell value change events

## Debugging steps:
1. **Test initial load** - Does it crash immediately?
2. **Test permission changes** - Click Admin/Owner/Viewer buttons
3. **Test empty grid** - Does empty data cause issues?
4. **Test cell editing** - Try changing checkbox values
5. **Monitor console** - Look for specific error patterns

## Expected behavior:
- Grid should load without crashes
- Permission buttons should update grid state
- Cell changes should be logged without loops
- No `is_loading` related errors

## If issues persist:
- Add more AG Grid properties (loading, loadingOverlayComponent, etc.)
- Compare with working table_component examples
- Test different dash-ag-grid configurations
- Check Dash version compatibility