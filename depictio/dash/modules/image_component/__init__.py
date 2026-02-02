"""
Image Component Module.

Provides an interactive image gallery component for displaying images from data collections
in a grid layout with full-screen modal viewing capability.

Module Structure:
    callbacks/__init__.py - Lazy loading coordinator
    callbacks/core.py - Core rendering callbacks (always loaded)
    callbacks/design.py - Design/edit mode callbacks (lazy loaded)
    callbacks/edit.py - Edit save callbacks (lazy loaded)
    design_ui.py - Design UI creation (lazy loaded)
    utils.py - Utility functions
"""
