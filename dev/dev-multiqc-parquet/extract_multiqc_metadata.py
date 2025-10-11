#!/usr/bin/env python3
"""
Extract MultiQC general_stats_addcols metadata from modules.

This script parses MultiQC module Python files to extract all column definitions
from self.general_stats_addcols() calls and generates structured JSON metadata
for each tool.
"""

import ast
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional


class MultiQCMetadataExtractor:
    """Extract metadata from MultiQC modules."""

    def __init__(self, multiqc_path: str):
        """Initialize extractor with path to MultiQC codebase."""
        self.multiqc_path = Path(multiqc_path)
        self.modules_path = self.multiqc_path / "multiqc" / "modules"

    def find_general_stats_calls(self, module_file: Path) -> List[Dict[str, Any]]:
        """Find and parse all general_stats_addcols() calls in a module file."""
        try:
            with open(module_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {module_file}: {e}")
            return []

        calls = []

        # Parse the AST
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            print(f"Syntax error in {module_file}: {e}")
            return []

        # Find all general_stats_addcols calls
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Attribute) and
                node.func.attr == 'general_stats_addcols'):

                call_info = self.extract_call_metadata(node, content, tree)
                if call_info:
                    calls.append(call_info)

        # Also look for functions that might contain multiple calls (like bismark pattern)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                function_calls = self.extract_multiple_calls_from_function(node, tree)
                calls.extend(function_calls)

        # Remove duplicates (in case we found the same call both ways)
        seen_lines = set()
        unique_calls = []
        for call in calls:
            line_key = call['line_number']
            if line_key not in seen_lines:
                seen_lines.add(line_key)
                unique_calls.append(call)

        return unique_calls

    def extract_call_metadata(self, call_node: ast.Call, content: str, tree: ast.AST) -> Optional[Dict[str, Any]]:
        """Extract metadata from a general_stats_addcols call."""
        try:
            # Get the line number and surrounding code
            line_num = call_node.lineno
            end_line = call_node.end_lineno or line_num

            # Extract the source code for this call
            lines = content.split('\n')
            call_source = '\n'.join(lines[line_num-1:end_line])

            # Try to extract the arguments
            args = call_node.args
            kwargs = call_node.keywords

            result = {
                'line_number': line_num,
                'call_source': call_source,
                'headers': {},
                'namespace': None,
                'data_structure': None
            }

            # Set current call line for context in variable resolution
            self._current_call_line = line_num

            # Process arguments and keywords
            for i, arg in enumerate(args):
                if i == 0:  # First argument is usually data
                    result['data_structure'] = self.ast_to_string(arg)
                elif i == 1:  # Second argument is usually headers
                    headers = self.extract_headers_from_ast(arg, tree)
                    if headers is not None:  # Changed from 'if headers:' to allow empty dicts with debug info
                        result['headers'] = headers

            # Process keyword arguments
            for kw in kwargs:
                if kw.arg == 'headers':
                    headers = self.extract_headers_from_ast(kw.value, tree)
                    if headers is not None:  # Changed from 'if headers:' to allow empty dicts with debug info
                        result['headers'] = headers
                elif kw.arg == 'namespace':
                    if isinstance(kw.value, ast.Constant):
                        result['namespace'] = kw.value.value

            # Clean up context
            self._current_call_line = None

            return result

        except Exception as e:
            print(f"Error extracting call metadata: {e}")
            return None

    def extract_headers_from_ast(self, node: ast.AST, tree: ast.AST) -> Dict[str, Any]:
        """Extract column headers dictionary from AST node."""
        headers = {}

        # Add debug info about node type
        node_type = type(node).__name__

        # Handle direct dictionary
        if isinstance(node, ast.Dict):
            headers = self._extract_from_dict_node(node, tree)

        # Handle subscript access (e.g., headers["methextract"])
        elif isinstance(node, ast.Subscript):
            headers = self._extract_from_subscript(node, tree)

        # Handle variable reference (e.g., "headers" in STAR)
        elif isinstance(node, ast.Name):
            var_name = node.id
            # Try to get call line from context if available
            call_line = getattr(self, '_current_call_line', None)
            var_dict = self.find_variable_assignment(var_name, tree, call_line)

            # First try to extract from initial assignment
            initial_headers = {}
            if var_dict:
                initial_headers = self.extract_headers_from_ast(var_dict, tree)

            # Always try to extract scattered assignments as well
            containing_function = self._find_containing_function(call_line, tree) if call_line else None
            scattered_headers = {}
            if containing_function:
                scattered_headers = self._extract_direct_assignments(containing_function, var_name)

            # Combine both sources, with scattered assignments taking precedence
            headers = initial_headers.copy() if initial_headers else {}
            if scattered_headers:
                headers.update(scattered_headers)
                return headers
            elif initial_headers:
                return initial_headers
            else:
                # If still no headers found, add debug info
                headers["_debug_info"] = f"variable_name:{var_name}, call_line:{call_line}, found_function:{containing_function is not None}"

        # Handle function call (e.g., get_general_stats_headers)
        elif isinstance(node, ast.Call):
            headers = self._extract_from_function_call(node, tree)

        # Handle list comprehension or complex expression
        elif isinstance(node, ast.ListComp) or isinstance(node, ast.List):
            # For now, mark as complex pattern
            headers = {"_complex_pattern": "list_or_comprehension"}

        else:
            # Unknown node type
            headers = {"_unknown_node_type": node_type}

        return headers

    def _extract_from_subscript(self, node: ast.Subscript, tree: ast.AST) -> Dict[str, Any]:
        """Extract headers from subscript access like headers['methextract']."""
        headers = {}

        # Get the base variable name and the subscript key
        if isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant):
            base_var = node.value.id
            subscript_key = node.slice.value

            # Find the function containing the current call
            call_line = getattr(self, '_current_call_line', None)
            if call_line:
                containing_function = self._find_containing_function(call_line, tree)
                if containing_function:
                    # Look for subscript assignments within this function
                    headers = self._extract_subscript_assignments(containing_function, base_var, subscript_key)

        # Handle direct variable reference (like `headers` in kaiju)
        elif isinstance(node.value, ast.Name):
            base_var = node.value.id

            # Find the function containing the current call
            call_line = getattr(self, '_current_call_line', None)
            if call_line:
                containing_function = self._find_containing_function(call_line, tree)
                if containing_function:
                    # Look for direct assignments to the base variable within this function
                    headers = self._extract_direct_assignments(containing_function, base_var)

        return headers

    def _extract_direct_assignments(self, func_node: ast.FunctionDef, base_var: str) -> Dict[str, Any]:
        """Extract direct assignments to base_var["key"] = {...} within a function."""
        headers = {}

        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    # Handle direct subscripts like headers["% Assigned"] = {...}
                    if (isinstance(target, ast.Subscript) and
                        isinstance(target.value, ast.Name) and
                        target.value.id == base_var and
                        isinstance(target.slice, ast.Constant)):

                        column_name = target.slice.value
                        if isinstance(stmt.value, ast.Dict):
                            column_def = {}
                            for attr_key, attr_value in zip(stmt.value.keys, stmt.value.values):
                                if isinstance(attr_key, ast.Constant):
                                    attr_name = attr_key.value
                                    attr_val = self.extract_value_from_ast(attr_value)
                                    column_def[attr_name] = attr_val
                            headers[column_name] = column_def

            # Handle for loops that might build headers dynamically
            elif isinstance(stmt, ast.For):
                for loop_stmt in ast.walk(stmt):
                    if isinstance(loop_stmt, ast.Assign):
                        for target in loop_stmt.targets:
                            if (isinstance(target, ast.Subscript) and
                                isinstance(target.value, ast.Name) and
                                target.value.id == base_var):
                                # Mark as dynamic construction
                                headers["_dynamic_loop"] = "for_loop_construction"

        return headers

    def _find_containing_function(self, line_number: int, tree: ast.AST) -> Optional[ast.FunctionDef]:
        """Find the function definition that contains the given line number."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check if the line number falls within this function
                if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                    if node.lineno <= line_number <= (node.end_lineno or float('inf')):
                        return node
                elif hasattr(node, 'lineno'):
                    # For older Python versions, estimate function end
                    # Look for the next function or class to estimate boundaries
                    next_def_line = float('inf')
                    for other in ast.walk(tree):
                        if (isinstance(other, (ast.FunctionDef, ast.ClassDef)) and
                            hasattr(other, 'lineno') and
                            other.lineno > node.lineno):
                            next_def_line = min(next_def_line, other.lineno)

                    if node.lineno <= line_number < next_def_line:
                        return node
        return None

    def _extract_subscript_assignments(self, func_node: ast.FunctionDef, base_var: str, subscript_key: str) -> Dict[str, Any]:
        """Extract assignments to base_var[subscript_key] within a function."""
        headers = {}

        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    # Handle nested subscripts like headers["methextract"]["percent_cpg_meth"]
                    if (isinstance(target, ast.Subscript) and
                        isinstance(target.value, ast.Subscript) and
                        isinstance(target.value.value, ast.Name) and
                        target.value.value.id == base_var):

                        if (isinstance(target.value.slice, ast.Constant) and
                            target.value.slice.value == subscript_key and
                            isinstance(target.slice, ast.Constant)):

                            column_name = target.slice.value
                            if isinstance(stmt.value, ast.Dict):
                                column_def = {}
                                for attr_key, attr_value in zip(stmt.value.keys, stmt.value.values):
                                    if isinstance(attr_key, ast.Constant):
                                        attr_name = attr_key.value
                                        attr_val = self.extract_value_from_ast(attr_value)
                                        column_def[attr_name] = attr_val
                                headers[column_name] = column_def

                    # Handle direct subscripts like headers["% Assigned"] = {...}
                    elif (isinstance(target, ast.Subscript) and
                          isinstance(target.value, ast.Name) and
                          target.value.id == base_var and
                          isinstance(target.slice, ast.Constant)):

                        column_name = target.slice.value
                        if isinstance(stmt.value, ast.Dict):
                            column_def = {}
                            for attr_key, attr_value in zip(stmt.value.keys, stmt.value.values):
                                if isinstance(attr_key, ast.Constant):
                                    attr_name = attr_key.value
                                    attr_val = self.extract_value_from_ast(attr_value)
                                    column_def[attr_name] = attr_val
                            headers[column_name] = column_def

        return headers

    def _extract_from_dict_node(self, node: ast.Dict, tree: ast.AST) -> Dict[str, Any]:
        """Extract headers from a dictionary AST node, handling nested patterns."""
        headers = {}

        for key, value in zip(node.keys, node.values):
            # Extract key
            if isinstance(key, ast.Constant):
                key_name = key.value
            elif isinstance(key, ast.Str):
                key_name = key.s
            elif isinstance(key, ast.Call) and hasattr(key.func, 'id') and key.func.id == 'ColumnKey':
                # Handle ColumnKey("name") pattern
                if key.args and isinstance(key.args[0], ast.Constant):
                    key_name = key.args[0].value
                else:
                    key_name = self.ast_to_string(key)
            else:
                key_name = self.ast_to_string(key)

            # Extract value (column definition)
            if isinstance(value, ast.Dict):
                # Direct nested dictionary (normal case)
                col_def = {}
                for attr_key, attr_value in zip(value.keys, value.values):
                    if isinstance(attr_key, ast.Constant):
                        attr_name = attr_key.value
                        attr_val = self.extract_value_from_ast(attr_value)
                        col_def[attr_name] = attr_val
                headers[key_name] = col_def
            elif isinstance(value, ast.Call):
                # Handle function calls in values (like dict.update patterns)
                if (isinstance(value.func, ast.Attribute) and
                    value.func.attr in ['copy', 'deepcopy']):
                    # Handle dict.copy() patterns - try to resolve the original dict
                    if isinstance(value.func.value, ast.Name):
                        original_dict = self.find_variable_assignment(value.func.value.id, tree, self._current_call_line)
                        if original_dict:
                            resolved_headers = self.extract_headers_from_ast(original_dict, tree)
                            headers.update(resolved_headers)
                elif isinstance(value.func, ast.Name):
                    # Direct function call - try to resolve it
                    func_def = self.find_function_definition(value.func.id, tree)
                    if func_def:
                        resolved_headers = self.extract_headers_from_ast(func_def, tree)
                        if isinstance(resolved_headers, dict):
                            headers[key_name] = resolved_headers
                        else:
                            headers[key_name] = {"_function_call": value.func.id}
                    else:
                        headers[key_name] = {"_function_call": value.func.id}
                else:
                    headers[key_name] = {"_complex_call": self.ast_to_string(value)}
            elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
                # Handle dictionary merge patterns like dict1 | dict2
                headers[key_name] = {"_dict_merge": self.ast_to_string(value)}
            elif isinstance(value, ast.Name):
                # Variable reference in value
                var_dict = self.find_variable_assignment(value.id, tree, self._current_call_line)
                if var_dict:
                    resolved_headers = self.extract_headers_from_ast(var_dict, tree)
                    headers[key_name] = resolved_headers
                else:
                    headers[key_name] = {"_variable_ref": value.id}
            else:
                headers[key_name] = self.ast_to_string(value)

        return headers

    def _extract_from_function_call(self, node: ast.Call, tree: ast.AST) -> Dict[str, Any]:
        """Extract headers from function call patterns."""
        headers = {}

        if (isinstance(node.func, ast.Attribute) and
            node.func.attr == 'get_general_stats_headers'):
            # Look for all_headers keyword argument
            for kw in node.keywords:
                if kw.arg == 'all_headers':
                    return self.extract_headers_from_ast(kw.value, tree)
        elif isinstance(node.func, ast.Name):
            # Handle direct function call like get_general_stats_headers()
            func_name = node.func.id
            func_def = self.find_function_definition(func_name, tree)
            if func_def:
                return self.extract_headers_from_ast(func_def, tree)
            else:
                # Mark as function-based pattern we couldn't resolve
                headers = {"_function_based": func_name}
        elif isinstance(node.func, ast.Attribute):
            # Handle method calls like obj.method()
            headers = {"_method_call": self.ast_to_string(node.func)}

        return headers

    def find_variable_assignment(self, var_name: str, tree: ast.AST, call_line: int = None) -> Optional[ast.AST]:
        """Find the assignment of a variable in the AST, preferring local scope."""
        candidates = []

        # Find all assignments of this variable
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        candidates.append((node.value, node.lineno))
            elif isinstance(node, ast.AnnAssign):
                # Handle annotated assignments like "headers: Dict[str, Dict] = {...}"
                if (isinstance(node.target, ast.Name) and
                    node.target.id == var_name and
                    node.value):
                    candidates.append((node.value, node.lineno))

        if not candidates:
            return None

        # If we have call line info, prefer assignments in the same function
        if call_line:
            # Find assignments that are closest before the call line
            valid_candidates = [(val, line) for val, line in candidates if line < call_line]
            if valid_candidates:
                # Return the closest one before the call
                closest = max(valid_candidates, key=lambda x: x[1])
                return closest[0]

        # Return the first found assignment
        return candidates[0][0]

    def find_function_definition(self, func_name: str, tree: ast.AST) -> Optional[ast.AST]:
        """Find a function definition in the AST and return its body."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                # Look for return statements in the function
                for stmt in node.body:
                    if isinstance(stmt, ast.Return) and stmt.value:
                        return stmt.value
                    # Also look for variable assignments that might be returned
                    elif isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                # Check if this variable is returned later
                                for later_stmt in node.body[node.body.index(stmt)+1:]:
                                    if (isinstance(later_stmt, ast.Return) and
                                        isinstance(later_stmt.value, ast.Name) and
                                        later_stmt.value.id == target.id):
                                        return stmt.value
        return None

    def extract_multiple_calls_from_function(self, func_node: ast.FunctionDef, tree: ast.AST) -> List[Dict[str, Any]]:
        """Extract multiple general_stats_addcols calls from a single function."""
        calls = []

        for stmt in func_node.body:
            # Look for general_stats_addcols calls within the function
            for node in ast.walk(stmt):
                if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Attribute) and
                    node.func.attr == 'general_stats_addcols'):

                    call_info = self.extract_call_metadata(node, ast.unparse(tree), tree)
                    if call_info:
                        # Add context that this came from a function
                        call_info['parent_function'] = func_node.name
                        calls.append(call_info)

        return calls

    def extract_value_from_ast(self, node: ast.AST) -> Any:
        """Extract value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.List):
            return [self.extract_value_from_ast(item) for item in node.elts]
        elif isinstance(node, ast.Dict):
            result = {}
            for key, value in zip(node.keys, node.values):
                key_val = self.extract_value_from_ast(key)
                value_val = self.extract_value_from_ast(value)
                result[key_val] = value_val
            return result
        else:
            return self.ast_to_string(node)

    def ast_to_string(self, node: ast.AST) -> str:
        """Convert AST node to string representation."""
        try:
            return ast.unparse(node)
        except:
            # Fallback for older Python versions
            import astor
            return astor.to_source(node).strip()

    def extract_module_metadata(self, module_dir: Path) -> Dict[str, Any]:
        """Extract metadata from a specific module directory."""
        module_name = module_dir.name
        metadata = {
            'module_name': module_name,
            'general_stats_calls': []
        }

        # Process all Python files in the module
        for py_file in module_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            calls = self.find_general_stats_calls(py_file)

            # Add file information to each call
            for call in calls:
                call['filename'] = py_file.name
                call['file_path'] = str(py_file.relative_to(self.multiqc_path))

            if calls:
                metadata['general_stats_calls'].extend(calls)

        return metadata

    def process_modules(self, module_names: List[str] = None, process_all: bool = False) -> Dict[str, Any]:
        """Process specified modules or all modules."""
        if process_all:
            # Find all modules with general_stats_addcols usage
            module_names = self.find_modules_with_general_stats()
            print(f"Found {len(module_names)} modules with general_stats_addcols usage")
        elif module_names is None:
            # Default to our test modules
            module_names = ['fastqc', 'star', 'samtools', 'seqfu', 'fastp']

        results = {}

        for module_name in module_names:
            module_dir = self.modules_path / module_name
            if module_dir.is_dir():
                print(f"Processing module: {module_name}")
                metadata = self.extract_module_metadata(module_dir)
                # Always include results, even if no calls found (for status tracking)
                results[module_name] = metadata
            else:
                print(f"Module directory not found: {module_name}")

        return results

    def find_modules_with_general_stats(self) -> List[str]:
        """Find all modules that use general_stats_addcols."""
        modules = []

        for module_dir in self.modules_path.iterdir():
            if module_dir.is_dir() and not module_dir.name.startswith('.'):
                # Check if any Python file uses general_stats_addcols
                has_general_stats = False
                for py_file in module_dir.glob("*.py"):
                    try:
                        with open(py_file, 'r', encoding='utf-8') as f:
                            if 'general_stats_addcols' in f.read():
                                has_general_stats = True
                                break
                    except:
                        continue

                if has_general_stats:
                    modules.append(module_dir.name)

        return modules


def generate_results_table(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate a detailed results table for all modules and submodules."""
    table_data = []

    for module_name, metadata in results.items():
        if not metadata['general_stats_calls']:
            # Module with no calls found
            table_data.append({
                'module': module_name,
                'submodule': 'N/A',
                'filename': 'N/A',
                'calls': 0,
                'columns': 0,
                'status': '❌ No calls found',
                'namespace': 'N/A',
                'extraction_method': 'N/A'
            })
        else:
            # Group calls by submodule (filename)
            calls_by_file = {}
            for call in metadata['general_stats_calls']:
                filename = call['filename']
                if filename not in calls_by_file:
                    calls_by_file[filename] = []
                calls_by_file[filename].append(call)

            for filename, calls in calls_by_file.items():
                total_columns = sum(len(call.get('headers', {})) for call in calls)

                # Determine status
                if total_columns > 0:
                    status = '✅ Success'
                    extraction_method = 'AST parsing with variable tracing'
                else:
                    status = '⚠️ Calls found, no columns extracted'
                    extraction_method = 'Pattern not supported'

                # Get unique namespaces
                namespaces = list(set(call.get('namespace') or 'None' for call in calls))
                namespace_str = ', '.join(namespaces) if len(namespaces) <= 2 else f"{namespaces[0]} + {len(namespaces)-1} more"

                # Determine submodule name
                submodule = filename.replace('.py', '') if filename != f"{module_name}.py" else 'main'

                table_data.append({
                    'module': module_name,
                    'submodule': submodule,
                    'filename': filename,
                    'calls': len(calls),
                    'columns': total_columns,
                    'status': status,
                    'namespace': namespace_str,
                    'extraction_method': extraction_method
                })

    return sorted(table_data, key=lambda x: (x['module'], x['submodule']))


def print_results_table(table_data: List[Dict[str, Any]]):
    """Print a formatted results table."""
    print("\n" + "="*120)
    print("MULTIQC MODULE EXTRACTION RESULTS")
    print("="*120)

    # Print header
    header = f"{'Module':<15} {'Submodule':<15} {'Calls':<6} {'Cols':<5} {'Status':<25} {'Namespace':<20} {'Method':<15}"
    print(header)
    print("-" * 120)

    # Group by module for better readability
    current_module = None
    module_totals = {}

    for row in table_data:
        if row['module'] != current_module:
            if current_module is not None:
                # Print module total
                totals = module_totals[current_module]
                print(f"{'  └─ TOTAL':<15} {'':<15} {totals['calls']:<6} {totals['columns']:<5} {'':<25} {'':<20} {'':<15}")
                print()
            current_module = row['module']
            module_totals[current_module] = {'calls': 0, 'columns': 0}

        # Print row
        is_first_submodule = row == next(r for r in table_data if r['module'] == row['module'])
        module_display = row['module'] if is_first_submodule else '  ├─'

        print(f"{module_display:<15} "
              f"{row['submodule']:<15} {row['calls']:<6} {row['columns']:<5} {row['status']:<25} "
              f"{row['namespace']:<20} {row['extraction_method']:<15}")

        # Update totals
        module_totals[current_module]['calls'] += row['calls']
        module_totals[current_module]['columns'] += row['columns']

    # Print final module total
    if current_module:
        totals = module_totals[current_module]
        print(f"{'  └─ TOTAL':<15} {'':<15} {totals['calls']:<6} {totals['columns']:<5} {'':<25} {'':<20} {'':<15}")

    print("\n" + "="*120)

    # Print overall summary
    total_modules = len(set(row['module'] for row in table_data))
    total_submodules = len(table_data)
    total_calls = sum(row['calls'] for row in table_data)
    total_columns = sum(row['columns'] for row in table_data)
    successful_submodules = len([row for row in table_data if row['columns'] > 0])

    print("OVERALL SUMMARY:")
    print(f"  Modules processed: {total_modules}")
    print(f"  Submodules found: {total_submodules}")
    print(f"  Total calls: {total_calls}")
    print(f"  Total columns extracted: {total_columns}")
    print(f"  Successful extractions: {successful_submodules}/{total_submodules} ({successful_submodules/total_submodules*100:.1f}%)")


def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(description='Extract MultiQC general_stats_addcols metadata')
    parser.add_argument('--all', action='store_true', help='Process all modules with general_stats_addcols')
    parser.add_argument('--modules', nargs='+', help='Specific modules to process',
                       default=['fastqc', 'star', 'samtools', 'seqfu', 'fastp'])
    args = parser.parse_args()

    multiqc_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/multiqc_latest"

    # Initialize extractor
    extractor = MultiQCMetadataExtractor(multiqc_path)

    print("Extracting metadata from MultiQC modules...")
    if args.all:
        results = extractor.process_modules(process_all=True)
    else:
        results = extractor.process_modules(args.modules)

    # Generate detailed results table
    table_data = generate_results_table(results)

    # Print detailed table
    print_results_table(table_data)

    # Save results
    output_file = Path(__file__).parent / "multiqc_metadata_extraction.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Save table data as well
    table_file = Path(__file__).parent / "multiqc_extraction_table.json"
    with open(table_file, 'w', encoding='utf-8') as f:
        json.dump(table_data, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {output_file}")
    print(f"Table data saved to: {table_file}")

    # Generate summary report for backward compatibility
    summary = {}
    for module_name, metadata in results.items():
        files_with_calls = len(set(call['filename'] for call in metadata['general_stats_calls'])) if metadata['general_stats_calls'] else 0
        total_columns = sum(len(call.get('headers', {})) for call in metadata['general_stats_calls'])
        column_keys = []
        for call in metadata['general_stats_calls']:
            for col_key in call.get('headers', {}):
                column_keys.append(f"{call['filename']}:{call['line_number']}:{col_key}")

        summary[module_name] = {
            'total_calls': len(metadata['general_stats_calls']),
            'total_columns': total_columns,
            'files_with_calls': files_with_calls,
            'column_keys': column_keys
        }

    summary_file = Path(__file__).parent / "multiqc_metadata_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()