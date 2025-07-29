#!/usr/bin/env python3
"""
Simple runner for the Mantine AppShell debug prototype
Uses authentication from depictio/.depictio/admin_config.yaml
"""

import asyncio
import sys
from pathlib import Path

# Add the depictio package to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from mantine_appshell_debug import main
    print("🏃 Running Mantine AppShell Debug...")
    asyncio.run(main())
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the correct directory")
except KeyboardInterrupt:
    print("\n👋 Interrupted by user")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()