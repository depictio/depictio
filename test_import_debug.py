#!/usr/bin/env python3
"""
Test file for debugging import sorting - placed in root to avoid exclusions.
"""

# Deliberately unsorted imports to test ruff behavior
import os
import sys

t = 1
os.environ["TEST_ENV_VAR"] = "test_value"
sys.path.append("/tmp")
