# Automated Theme Detection for Depictio

## Overview

Depictio now features an intelligent automated theme detection system that automatically adapts to your computer's theme preference (light/dark mode) and provides manual override options.

## Features

### 🔄 Automatic Detection
- **System Sync**: Automatically detects and applies your computer's light/dark theme preference
- **Real-time Updates**: Dynamically updates when you change your system theme
- **Fallback**: Gracefully falls back to light theme if system preference can't be detected

### 👤 Manual Override
- **Theme Switch**: Toggle between light and dark themes manually
- **Persistent**: Remembers your manual choice across browser sessions
- **Override Protection**: Prevents automatic updates when you've made a manual selection

### 🔄 Reset to Auto
- **Auto Button**: One-click reset to automatic theme detection
- **Re-sync**: Immediately syncs with current system preference
- **Clean State**: Removes manual override and re-enables automatic updates

## How It Works

### CSS-Based Detection
The system uses CSS media queries for optimal performance:

```css
/* Automatic dark theme detection */
@media (prefers-color-scheme: dark) {
    :root {
        --app-bg-color: var(--depictio-bg-dark);
        --app-text-color: var(--depictio-text-dark);
        --app-surface-color: var(--depictio-surface-dark);
        --app-border-color: var(--depictio-border-dark);
    }
}
```

### JavaScript Enhancement
JavaScript adds intelligence for:
- Manual override tracking
- Real-time system theme change detection
- Smooth transitions between themes
- Local storage persistence

## User Interface

### Theme Controls Location
The theme controls are located in the sidebar:
- **Theme Switch**: Toggle between light/dark
- **Auto Button**: Reset to automatic detection

### Visual Indicators
- **Switch Position**: Shows current theme (moon = light, sun = dark)
- **Auto Button**: Visible when you can reset to automatic mode
- **Smooth Transitions**: All theme changes are animated

## Technical Implementation

### Files Structure
```
depictio/dash/assets/
├── backgrounds.css      # CSS variables and media queries
├── auto-theme.css      # Additional auto-theme utilities
└── app.css             # Main application styles

depictio/dash/
├── theme_utils.py      # Theme detection and callbacks
└── layouts/sidebar.py  # Theme controls UI
```

### Key Components

1. **CSS Variables**: Dynamic theme colors via CSS custom properties
2. **Media Queries**: `prefers-color-scheme` detection
3. **Local Storage**: Theme preference persistence
4. **Event Listeners**: Real-time system theme change detection
5. **Override Tracking**: Manual vs automatic theme state

## Usage Examples

### For Users
1. **Automatic**: Theme matches your computer automatically
2. **Manual Light**: Click theme switch to force light theme
3. **Manual Dark**: Click theme switch to force dark theme
4. **Back to Auto**: Click "🔄 Auto" button to re-enable automatic detection

### For Developers
```python
from depictio.dash.theme_utils import create_theme_controls

# Use the complete theme control group
theme_controls = create_theme_controls()

# Or individual components
theme_switch = create_theme_switch()
auto_button = create_auto_theme_button()
```

## Browser Compatibility

- **Chrome/Edge**: Full support
- **Firefox**: Full support
- **Safari**: Full support
- **Mobile**: Full support on modern browsers

## Benefits

### Performance
- **CSS-First**: Leverages browser's native theme detection
- **No JavaScript Dependency**: Basic theming works without JavaScript
- **Smooth Transitions**: GPU-accelerated CSS transitions

### User Experience
- **Zero Configuration**: Works out of the box
- **Respects Preferences**: Honors user's system settings
- **Manual Control**: Override when needed
- **Persistent**: Remembers choices

### Developer Experience
- **Simple Integration**: Easy to add to components
- **CSS Variables**: Clean, maintainable theming
- **Extensible**: Easy to add new themes
- **Type Safe**: Full TypeScript support

## Future Enhancements

- **Custom Themes**: Support for user-defined color schemes
- **Schedule-Based**: Automatic theme switching based on time
- **High Contrast**: Accessibility-focused theme variants
- **Theme Sync**: Cross-device theme synchronization
