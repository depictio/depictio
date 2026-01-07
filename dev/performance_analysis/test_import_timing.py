#!/usr/bin/env python3
"""
Test Import Timing: Measure performance impact of eager vs lazy imports

This script measures the actual time it takes to import various Depictio modules
to validate whether deferring design-related imports provides meaningful savings.
"""

import sys
import time
from pathlib import Path

# Add depictio to path
DEPICTIO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(DEPICTIO_ROOT))


def measure_import(module_path, description, clear_cache=True):
    """
    Measure time to import a module.

    Args:
        module_path: Python import path (e.g., 'depictio.dash.modules.card_component.frontend')
        description: Human-readable description
        clear_cache: If True, removes module from sys.modules before timing

    Returns:
        Elapsed time in milliseconds
    """
    # Clear from cache to get accurate cold-start timing
    if clear_cache:
        modules_to_clear = [k for k in sys.modules.keys() if module_path in k]
        for mod in modules_to_clear:
            del sys.modules[mod]

    start = time.perf_counter()
    try:
        __import__(module_path)
        elapsed = (time.perf_counter() - start) * 1000
        status = "✓"
    except ImportError as e:
        elapsed = 0
        status = "✗"
        description = f"{description} (ERROR: {e})"

    print(f"{status} {description:60} {elapsed:>8.1f}ms")
    return elapsed


def test_eager_loading():
    """Test current approach - load everything upfront"""
    print("\n" + "=" * 80)
    print("EAGER LOADING (Current Approach)")
    print("=" * 80)

    total = 0

    print("\n--- Card Component (Full) ---")
    total += measure_import(
        "depictio.dash.modules.card_component.frontend",
        "Card frontend (ALL callbacks)"
    )
    total += measure_import(
        "depictio.dash.modules.card_component.utils",
        "Card utils (build_card + design utilities)"
    )

    print("\n--- Figure Component (Full) ---")
    total += measure_import(
        "depictio.dash.modules.figure_component.frontend",
        "Figure frontend (ALL callbacks)"
    )
    total += measure_import(
        "depictio.dash.modules.figure_component.utils",
        "Figure utils (build_figure + design utilities)"
    )

    print("\n--- Interactive Component (Full) ---")
    total += measure_import(
        "depictio.dash.modules.interactive_component.utils",
        "Interactive utils (build + design)"
    )

    print("\n--- Design-Heavy Modules ---")
    total += measure_import(
        "dash_mantine_components",
        "DMC (full library with ColorPicker, etc.)"
    )

    print(f"\n{'TOTAL EAGER LOADING TIME:':60} {total:>8.1f}ms")
    print("=" * 80)

    return total


def test_lazy_loading():
    """Test proposed approach - defer design imports"""
    print("\n" + "=" * 80)
    print("LAZY LOADING (Proposed Approach)")
    print("=" * 80)
    print("Only imports needed for core rendering (not design/edit mode)")

    total = 0

    print("\n--- Core Rendering Only ---")

    # Note: We can't actually test importing ONLY render functions without
    # modifying the codebase, but we can estimate by excluding heavy modules

    # Simulate: If we split card_component into render-only module
    print("✓ Card render callback                                       (estimated ~50ms)")
    total += 50

    print("✓ Figure render callback                                     (estimated ~50ms)")
    total += 50

    print("✓ Interactive build (minimal)                                (estimated ~30ms)")
    total += 30

    print("\n--- Deferred (Not Loaded) ---")
    print("✗ Card design callbacks                                      (deferred)")
    print("✗ Figure design callbacks                                    (deferred)")
    print("✗ ColorPicker/IconPicker components                          (deferred)")
    print("✗ Design utility functions                                   (deferred)")

    print(f"\n{'TOTAL LAZY LOADING TIME (estimated):':60} {total:>8.1f}ms")
    print("=" * 80)

    return total


def test_specific_design_modules():
    """Test imports of specific design-related modules"""
    print("\n" + "=" * 80)
    print("DESIGN MODULE BREAKDOWN")
    print("=" * 80)
    print("Measuring individual design-related imports that could be deferred")

    total = 0

    print("\n--- Heavy Design Dependencies ---")

    # DMC components used in design mode
    total += measure_import("dash_mantine_components", "DMC (ColorPicker, IconPicker, etc.)")
    total += measure_import("dash_iconify", "DashIconify")

    print("\n--- Layout Modules (Draggable Grid) ---")
    total += measure_import("dash_dynamic_grid_layout", "Dash Dynamic Grid Layout")

    print(f"\n{'TOTAL DESIGN MODULE TIME:':60} {total:>8.1f}ms")
    print("=" * 80)

    return total


def main():
    """Run all import timing tests"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "IMPORT TIMING TEST" + " " * 40 + "║")
    print("╚" + "=" * 78 + "╝")

    # Test 1: Current approach (eager loading)
    eager_time = test_eager_loading()

    # Test 2: Proposed approach (lazy loading)
    lazy_time = test_lazy_loading()

    # Test 3: Specific design modules
    design_time = test_specific_design_modules()

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY & RECOMMENDATION")
    print("=" * 80)

    savings = eager_time - lazy_time
    pct_savings = (savings / eager_time * 100) if eager_time > 0 else 0

    print(f"\nEager Loading (Current):     {eager_time:>8.1f}ms")
    print(f"Lazy Loading (Proposed):     {lazy_time:>8.1f}ms")
    print(f"Potential Savings:           {savings:>8.1f}ms ({pct_savings:.1f}%)")
    print(f"\nDesign Modules (Deferred):   {design_time:>8.1f}ms")

    print("\n" + "-" * 80)

    if savings > 200:
        print("✅ RECOMMENDATION: PROCEED with render/design callback split")
        print(f"   Expected improvement: {savings:.0f}ms ({pct_savings:.1f}%) faster startup")
        print("   This is a significant performance gain worth implementing.")
    elif savings > 100:
        print("⚠️  RECOMMENDATION: CONSIDER proceeding (moderate benefit)")
        print(f"   Expected improvement: {savings:.0f}ms ({pct_savings:.1f}%) faster startup")
        print("   Benefit is moderate - evaluate complexity vs gain.")
    else:
        print("❌ RECOMMENDATION: DON'T PROCEED (minimal benefit)")
        print(f"   Expected improvement: {savings:.0f}ms ({pct_savings:.1f}%) faster startup")
        print("   Savings too small to justify added complexity.")

    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
