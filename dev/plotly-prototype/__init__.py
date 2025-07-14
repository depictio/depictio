"""
Plotly Code Prototype Package

A secure Python/Plotly code execution environment that leverages 
the figure component builder logic from depictio/dash.

This package provides:
- Secure code execution with comprehensive validation
- Real-time Plotly visualization generation
- Modern Dash interface with DMC components
- Multiple sample datasets for testing
"""

__version__ = "1.0.0"
__author__ = "Depictio Team"
__description__ = "Secure Plotly code execution prototype"

# Main exports
from .secure_code_executor import SecureCodeExecutor, SecureCodeValidator
from .plotly_prototype_app import create_app, main

__all__ = [
    "SecureCodeExecutor",
    "SecureCodeValidator", 
    "create_app",
    "main"
]