# Installation Note for Enhanced Code Editor

## Quick Setup

To get the enhanced Python code editor with syntax highlighting working, you need to install `dash-ace`:

```bash
pip install dash-ace
```

## Features Added

### ✅ **Professional Code Editor**
- **Syntax Highlighting**: Full Python syntax highlighting with the GitHub theme
- **Line Numbers**: Visible line numbers for better code navigation
- **Auto-completion**: Smart code completion for Python
- **Live Auto-completion**: Real-time suggestions as you type
- **Code Snippets**: Built-in Python code snippets
- **Active Line Highlighting**: Current line is highlighted
- **Professional Fonts**: Uses Fira Code, JetBrains Mono, or Monaco

### ✅ **Improved Layout**
- **Full-Width Design**: Code editor and plot take full width of the container
- **Larger Code Area**: 400px height for comfortable coding
- **Larger Plot Area**: 700px height for better visualization
- **Stacked Layout**: Code editor on top, visualization below
- **Collapsible Dataset Info**: Accordion-style dataset information at the bottom

### ✅ **Code Editor Features**
- **macOS-style Window**: Colored window controls (red, yellow, green)
- **File Tab**: Shows "main.py" with Python and UTF-8 indicators
- **Dark Theme**: Professional dark theme for reduced eye strain
- **Tab Support**: 4-space tabs with soft tabs enabled
- **No Line Wrap**: Horizontal scrolling for long lines

## Fallback
If `dash-ace` is not installed, the app automatically falls back to an enhanced textarea with:
- Monospace fonts
- Dark theme styling
- Proper sizing
- Code-like appearance

## To Install dash-ace

```bash
# Using pip
pip install dash-ace

# Or using the requirements file
pip install -r requirements.txt
```

After installation, restart the app to see the enhanced code editor with full Python syntax highlighting!