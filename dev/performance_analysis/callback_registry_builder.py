#!/usr/bin/env python3
"""
Callback Registry Builder
Parses Python source files to extract Dash callback definitions and build a registry
for mapping network requests to source code locations.
"""

import ast
import json
from pathlib import Path
from typing import Any


class CallbackRegistryBuilder:
    """Build a registry of Dash callbacks from Python source files"""

    def __init__(self, dash_dir="../../depictio/dash"):
        self.dash_dir = Path(__file__).parent / dash_dir
        self.registry = {}
        self.stats = {"files_parsed": 0, "callbacks_found": 0, "errors": 0}

    def build_registry(self, output_file="callback_registry.json"):
        """Walk through all Python files and extract callbacks"""
        print(f"🔍 Scanning {self.dash_dir} for callbacks...")
        print("=" * 80)

        for py_file in self.dash_dir.rglob("*.py"):
            try:
                self.parse_file(py_file)
                self.stats["files_parsed"] += 1
            except Exception as e:
                print(f"⚠️  Error parsing {py_file.name}: {e}")
                self.stats["errors"] += 1

        # Save registry
        output_path = Path(__file__).parent / output_file
        with open(output_path, "w") as f:
            json.dump(self.registry, f, indent=2, default=str)

        # Print statistics
        print("\n" + "=" * 80)
        print("📊 REGISTRY BUILD STATISTICS")
        print("=" * 80)
        print(f"Files parsed: {self.stats['files_parsed']}")
        print(f"Callbacks found: {self.stats['callbacks_found']}")
        print(f"Errors: {self.stats['errors']}")
        print(f"\n💾 Registry saved to: {output_path}")
        print(f"   Registry size: {len(self.registry)} unique callback patterns")

        return self.registry

    def parse_file(self, file_path):
        """Parse a Python file for @app.callback or @callback decorators"""
        try:
            with open(file_path) as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            # Skip files with syntax errors
            return

        # Walk the AST to find function definitions with callback decorators
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                callback_info = self.extract_callback_info(node, file_path, content)
                if callback_info:
                    # Build multiple pattern keys for flexible matching
                    patterns = self.build_pattern_keys(callback_info)
                    for pattern in patterns:
                        self.registry[pattern] = callback_info
                    self.stats["callbacks_found"] += 1

    def extract_callback_info(self, func_node, file_path, source_content):
        """Extract callback decorator information from a function node"""
        for decorator in func_node.decorator_list:
            if self.is_callback_decorator(decorator):
                # Extract inputs and outputs from decorator arguments
                inputs = []
                outputs = []

                # Parse decorator arguments
                if isinstance(decorator, ast.Call):
                    # app.callback(...) style
                    for arg in decorator.args:
                        io_info = self.parse_io_arg(arg)
                        if io_info:
                            if io_info["type"] == "Output":
                                outputs.append(io_info)
                            elif io_info["type"] == "Input":
                                inputs.append(io_info)

                # Get function docstring
                docstring = ast.get_docstring(func_node)
                if docstring:
                    # Take only first line/sentence for brevity
                    docstring = docstring.split("\n")[0].strip()
                    if len(docstring) > 100:
                        docstring = docstring[:97] + "..."

                return {
                    "function": func_node.name,
                    "file": str(file_path.relative_to(Path(__file__).parent.parent)),
                    "line": func_node.lineno,
                    "inputs": inputs,
                    "outputs": outputs,
                    "docstring": docstring or "",
                }

        return None

    def is_callback_decorator(self, decorator):
        """Check if decorator is a Dash callback"""
        if isinstance(decorator, ast.Call):
            # app.callback(...) or callback(...)
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr in ["callback", "clientside_callback"]
            elif isinstance(decorator.func, ast.Name):
                return decorator.func.id in ["callback", "clientside_callback"]
        elif isinstance(decorator, ast.Attribute):
            # @app.callback without ()
            return decorator.attr == "callback"
        elif isinstance(decorator, ast.Name):
            # @callback without ()
            return decorator.id == "callback"
        return False

    def parse_io_arg(self, arg):
        """Parse Input/Output/State argument from decorator"""
        if not isinstance(arg, ast.Call):
            return None

        # Get the IO type (Input, Output, State)
        io_type = None
        if isinstance(arg.func, ast.Name):
            io_type = arg.func.id

        if io_type not in ["Input", "Output", "State"]:
            return None

        # Extract component ID and property
        comp_id = None
        prop = None

        if len(arg.args) >= 1:
            # First arg is component ID
            comp_id = self.extract_value(arg.args[0])
        if len(arg.args) >= 2:
            # Second arg is property
            prop = self.extract_value(arg.args[1])

        if comp_id and prop:
            return {"type": io_type, "id": comp_id, "property": prop}

        return None

    def extract_value(self, node):
        """Extract value from AST node (string, dict, etc.)"""
        if isinstance(node, ast.Constant):
            # Python 3.8+
            return node.value
        elif isinstance(node, ast.Str):
            # Python 3.7
            return node.s
        elif isinstance(node, ast.Dict):
            # Pattern-matching ID like {"type": "button", "index": MATCH}
            # Return simplified representation
            keys = [self.extract_value(k) for k in node.keys]
            return {k: "PATTERN" for k in keys if k}  # Simplified pattern marker
        elif isinstance(node, ast.Name):
            # Variable name (like MATCH, ALL)
            return node.id
        else:
            return str(node)[:30]  # Fallback: convert to string (truncated)

    def build_pattern_keys(self, callback_info):
        """Build multiple pattern keys for flexible matching"""
        patterns = []

        # Pattern 1: Simple output-based key (most common)
        if callback_info["outputs"]:
            output_ids = []
            for out in callback_info["outputs"]:
                comp_id = out["id"]
                prop = out["property"]
                # Simplify complex IDs
                if isinstance(comp_id, dict):
                    comp_id = "pattern"
                output_ids.append(f"{comp_id}.{prop}")
            patterns.append("→".join(sorted(output_ids)))

        # Pattern 2: Input+Output combination
        if callback_info["inputs"] and callback_info["outputs"]:
            input_str = self.build_io_string(callback_info["inputs"])
            output_str = self.build_io_string(callback_info["outputs"])
            patterns.append(f"{input_str}→{output_str}")

        # Pattern 3: Just function name (fallback)
        patterns.append(callback_info["function"])

        return patterns

    def build_io_string(self, io_list):
        """Build simplified string representation of inputs/outputs"""
        parts = []
        for io in io_list[:5]:  # Limit to first 5 for brevity
            comp_id = io["id"]
            prop = io["property"]

            # Simplify pattern-matching IDs
            if isinstance(comp_id, dict):
                comp_id = "pattern"
            elif isinstance(comp_id, str) and len(comp_id) > 30:
                comp_id = comp_id[:27] + "..."

            parts.append(f"{comp_id}.{prop}")

        if len(io_list) > 5:
            parts.append(f"+{len(io_list)-5}more")

        return "+".join(parts)


def main():
    print("\n" + "=" * 80)
    print("DASH CALLBACK REGISTRY BUILDER")
    print("=" * 80 + "\n")

    builder = CallbackRegistryBuilder()
    registry = builder.build_registry()

    # Show sample entries
    print("\n" + "=" * 80)
    print("📋 SAMPLE REGISTRY ENTRIES")
    print("=" * 80)

    for i, (pattern, info) in enumerate(list(registry.items())[:10], 1):
        print(f"\n{i}. Pattern: {pattern}")
        print(f"   Function: {info['function']}()")
        print(f"   File: {info['file']}:{info['line']}")
        if info["docstring"]:
            print(f"   Doc: {info['docstring']}")
        print(f"   Inputs: {len(info['inputs'])} | Outputs: {len(info['outputs'])}")

    if len(registry) > 10:
        print(f"\n   ... and {len(registry) - 10} more entries")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
