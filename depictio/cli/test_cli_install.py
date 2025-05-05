#!/usr/bin/env python
"""
Test script to verify the CLI package installation.
This script imports the CLI modules to ensure they can be found.
"""

import importlib.util
import sys


def check_module(module_name):
    """Check if a module can be imported"""
    try:
        importlib.import_module(module_name)
        print(f"✅ Successfully imported {module_name}")
        return True
    except ImportError as e:
        print(f"❌ Failed to import {module_name}: {e}")
        return False


def main():
    """Test CLI package installation"""
    print("Testing CLI package installation...")

    # List of modules to check
    modules = [
        "depictio.cli.depictio_cli",
        "depictio.cli.cli.commands.config",
        "depictio.cli.cli.commands.data",
        "depictio.cli.cli.utils.api_calls",
    ]

    success = all(check_module(module) for module in modules)

    if success:
        print(
            "\nAll modules imported successfully! The CLI package is correctly installed."
        )
        return 0
    else:
        print(
            "\nSome modules failed to import. Please check the CLI package installation."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
