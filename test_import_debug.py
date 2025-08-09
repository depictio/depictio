#!/usr/bin/env python3
"""
Test file for debugging import sorting - placed in root to avoid exclusions.
"""

# Deliberately unsorted imports to test ruff behavior
import datetime
from typing import Dict, List

import dash_cytoscape as cyto
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from dash import html  # This should be with other dash imports
from depictio.dash.colors import colors

print("Test file with deliberately bad import sorting")
