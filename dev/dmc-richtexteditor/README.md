# DMC RichTextEditor Prototype

This prototype tests the DMC (Dash Mantine Components) RichTextEditor to determine the correct configuration and usage patterns.

## Purpose

The main Text component in Depictio is experiencing JavaScript errors when trying to render the DMC RichTextEditor:
- "Cannot read properties of undefined (reading 'configure')" 
- "Element type is invalid: expected a string or a class/function but got: undefined"

This prototype will help identify:
1. Whether RichTextEditor is available in the current DMC version
2. The correct property names and configuration
3. Working examples for different use cases

## Running the Prototype

```bash
cd /Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dmc-richtexteditor
python app.py
```

Then open http://localhost:8051

## Tests Included

1. **Test 1: Basic Configuration** - Minimal RichTextEditor setup
2. **Test 2: With Initial Content** - RichTextEditor with pre-filled HTML content
3. **Test 3: With Toolbar Config** - Custom toolbar controls
4. **Test 4: Fallback Textarea** - DMC Textarea as alternative if RichTextEditor fails

## Troubleshooting

If RichTextEditor is not available:
- Check DMC version: The component might not be available in older versions
- Use the fallback Textarea approach
- Consider using dcc.Textarea as an alternative

## Expected Outcomes

- ✅ RichTextEditor renders correctly → Use the working configuration in main component
- ❌ RichTextEditor fails → Use Textarea fallback and investigate DMC version compatibility