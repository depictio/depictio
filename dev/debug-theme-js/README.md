# Debug Theme JavaScript Issues

This debug app isolates theme switching JavaScript to identify and fix:

1. **"Cannot read properties of undefined (reading 'apply')" error**
2. **NavLink icon theming issues**
3. **Theme toggle icon inversion problems**

## Usage

```bash
cd dev/debug-theme-js
python debug_theme_js.py
```

Open http://127.0.0.1:8051 and check browser console for detailed debugging output.

## What to Test

1. **Switch themes** using the toggle
2. **Check console logs** for JavaScript errors
3. **Verify NavLink icon behavior**:
   - Active NavLinks should keep their colors (orange, teal, etc.)
   - Inactive NavLinks should use black/white based on theme

## Debug Output

The app provides extensive console logging for:
- Theme callback execution
- NavLink detection
- Icon detection and styling
- Style operation safety checks
- Error stack traces