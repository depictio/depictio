# Background Animation Prototype

A dedicated prototype for testing and refining background animation systems for Depictio dashboards.

## Features

- **Smooth Triangle Animations**: Based on the refined patterns from the existing auth page system
- **Performance Levels**: Three performance modes (low, medium, high) with automatic adaptation
- **Theme Support**: Light and dark theme compatibility
- **Real-time Controls**: Live switching between themes and performance levels
- **Responsive Design**: Mobile-friendly with reduced complexity on smaller screens

## Running the Prototype

```bash
cd dev/background-animation
python app.py
```

The prototype will be available at `http://localhost:8051`

## Key Components

### Background Effects System (`background_effects.py`)
- Triangle particle generation with Depictio brand colors
- Grid-based distribution for even coverage
- Performance-aware particle counts
- SVG-based triangle rendering with 2:1 aspect ratio

### Animation Patterns (`assets/style.css`)
- 6 different animation patterns based on existing smooth movements
- Small translation distances (10-60px) for refined movement
- Smooth rotation combinations
- Performance-based duration scaling

### Interactive Controls
- **Theme Switching**: Test light/dark theme compatibility
- **Performance Modes**: Switch between low/medium/high performance
- **Live Preview**: See changes immediately without reloading

## Animation Patterns

The system uses 6 refined animation patterns:

1. **Pattern 0**: Circular motion with 90° rotation steps
2. **Pattern 1**: Counter-clockwise movement with negative rotation
3. **Pattern 2**: Gentle arc movement with 45° rotation
4. **Pattern 3**: Extended horizontal movement 
5. **Pattern 4**: Vertical emphasis with 120° rotation steps
6. **Pattern 5**: Compact movement with 60° rotation steps

## Performance Optimization

- **Low**: 15 particles, 25s duration, 0.15 opacity
- **Medium**: 25 particles, 18s duration, 0.25 opacity  
- **High**: 35 particles, 14s duration, 0.35 opacity

## Development Notes

This prototype replicates the smooth, refined animations from the existing auth page system but adapted for dashboard use. The key insight is using small translation distances with smooth rotation combinations rather than large, jarring movements.

The system is designed to be:
- GPU-efficient with proper CSS transforms
- Accessible with reduced motion support
- Responsive with mobile optimizations
- Theme-aware with proper color filtering