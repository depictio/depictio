#!/usr/bin/env python3
"""
Check versions of key packages
"""

import sys


def check_version(package_name):
    try:
        package = __import__(package_name)
        version = getattr(package, "__version__", "Unknown")
        print(f"{package_name}: {version}")
        return True
    except ImportError:
        print(f"{package_name}: NOT INSTALLED")
        return False


def main():
    print("Checking package versions...")
    print("=" * 40)

    packages = [
        "dash",
        "dash_mantine_components",
        "plotly",
        "polars",
    ]

    for package in packages:
        check_version(package)

    print("\nPython version:", sys.version)

    # Try to import and check DMC components
    print("\nTesting DMC imports...")
    try:
        import dash_mantine_components as dmc

        print("✓ DMC imported successfully")

        # Check if RangeSlider is available
        if hasattr(dmc, "RangeSlider"):
            print("✓ RangeSlider is available")
        else:
            print("✗ RangeSlider is NOT available")

        # Check if Slider is available
        if hasattr(dmc, "Slider"):
            print("✓ Slider is available")
        else:
            print("✗ Slider is NOT available")

    except Exception as e:
        print(f"✗ DMC import failed: {e}")


if __name__ == "__main__":
    main()
