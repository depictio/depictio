# Depictio Assets Organization

This directory contains all assets for the Depictio Dash application, organized into logical categories for better maintainability.

## Folder Structure

```
/assets/
├── css/                     # All CSS files
│   ├── main.css            # Main CSS import file
│   ├── app.css             # Application-specific CSS
│   ├── backgrounds.css     # Background/legacy CSS
│   ├── core/               # Core styling
│   │   └── typography.css  # Font definitions
│   ├── theme/              # Theme system
│   │   ├── theme-variables.css
│   │   └── auto-theme.css
│   ├── animations/         # Animation definitions
│   │   └── animations.css
│   ├── components/         # Component-specific styles
│   │   ├── auth.css
│   │   ├── draggable-grid.css
│   │   ├── layout.css
│   │   └── clipboard.css
│   ├── utilities/          # Utility classes
│   │   ├── fouc-prevention.css
│   │   ├── performance.css
│   │   └── accessibility.css
│   └── legacy/             # Backup files
├── js/                     # JavaScript files
│   ├── dashAgGridComponentFunctions.js
│   ├── debug-menu-control.js
│   └── visualization_dropdown.js
├── fonts/                  # Font files
│   └── Virgil.ttf
├── images/                 # All image assets
│   ├── logos/
│   ├── icons/
│   └── backgrounds/
├── app.css                 # Main CSS entry point (imports css/main.css)
└── backgrounds.css         # Legacy compatibility (imports css/main.css)
```

## Usage

### CSS
The main CSS files (`app.css` and `backgrounds.css`) in the root directory are maintained for backward compatibility and import the modular CSS structure.

### JavaScript
JavaScript files are organized by functionality in the `js/` directory.

### Fonts
All font files are in the `fonts/` directory with proper relative path references.

### Images
All image assets are organized in the `images/` directory by category.

## Migration
- Original files are backed up in `css/legacy/`
- All file references have been updated to new paths
- Existing imports continue to work through the main entry points
