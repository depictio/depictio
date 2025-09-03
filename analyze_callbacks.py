#!/usr/bin/env python3
"""
Comprehensive callback analysis script for depictio/dash codebase
Analyzes callback patterns, output counts, and performance implications
"""
import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Set, Tuple
import ast
import inspect
import sys

@dataclass
class CallbackInfo:
    file_path: str
    line_number: int
    function_name: str
    outputs: List[str]
    inputs: List[str]
    states: List[str]
    output_count: int
    input_count: int
    state_count: int
    complexity_score: float
    pattern_matching: bool
    has_prevent_update: bool
    callback_context_used: bool

    def __post_init__(self):
        self.complexity_score = self.calculate_complexity()

    def calculate_complexity(self) -> float:
        """Calculate complexity based on I/O counts and features"""
        base_score = (self.output_count * 2) + self.input_count + (self.state_count * 0.5)

        # Add complexity for pattern matching
        if self.pattern_matching:
            base_score *= 1.5

        # Add complexity for callback context usage
        if self.callback_context_used:
            base_score *= 1.2

        return round(base_score, 2)

def extract_callback_components(decorator_content: str) -> Dict[str, List[str]]:
    """Extract Output, Input, State components from callback decorator"""
    outputs = []
    inputs = []
    states = []

    # Look for Output, Input, State patterns
    output_pattern = r'Output\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)'
    input_pattern = r'Input\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)'
    state_pattern = r'State\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)'

    outputs.extend(re.findall(output_pattern, decorator_content))
    inputs.extend(re.findall(input_pattern, decorator_content))
    states.extend(re.findall(state_pattern, decorator_content))

    return {
        'outputs': outputs,
        'inputs': inputs,
        'states': states
    }

def analyze_callback_function(file_content: str, start_line: int) -> Dict[str, bool]:
    """Analyze callback function for complexity indicators"""
    lines = file_content.split('\n')
    function_content = ""

    # Extract function content starting from callback decorator
    in_function = False
    indent_level = None

    for i in range(start_line, len(lines)):
        line = lines[i]

        if line.strip().startswith('def ') and not in_function:
            in_function = True
            indent_level = len(line) - len(line.lstrip())
            function_content += line + '\n'
        elif in_function:
            current_indent = len(line) - len(line.lstrip())
            if line.strip() and current_indent <= indent_level and not line.strip().startswith('def'):
                break
            function_content += line + '\n'

    # Analyze function content
    has_prevent_update = 'PreventUpdate' in function_content or 'prevent_update' in function_content
    callback_context_used = 'callback_context' in function_content or 'ctx.' in function_content
    pattern_matching = 'MATCH' in function_content or 'ALL' in function_content or 'ALLSMALLER' in function_content

    return {
        'has_prevent_update': has_prevent_update,
        'callback_context_used': callback_context_used,
        'pattern_matching': pattern_matching
    }

def scan_file_for_callbacks(file_path: Path) -> List[CallbackInfo]:
    """Scan a single Python file for callback definitions"""
    callbacks = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')

        # Find all @app.callback occurrences
        for i, line in enumerate(lines):
            if '@app.callback' in line and not line.strip().startswith('#'):
                try:
                    # Extract callback decorator and function definition
                    decorator_start = i
                    decorator_end = i

                    # Find the end of the decorator (may span multiple lines)
                    paren_count = line.count('(') - line.count(')')
                    current_line = i

                    decorator_content = line

                    while paren_count > 0 and current_line < len(lines) - 1:
                        current_line += 1
                        next_line = lines[current_line]
                        decorator_content += '\n' + next_line
                        paren_count += next_line.count('(') - next_line.count(')')
                        decorator_end = current_line

                    # Find the function definition
                    func_line = decorator_end + 1
                    while func_line < len(lines) and not lines[func_line].strip().startswith('def'):
                        func_line += 1

                    if func_line >= len(lines):
                        continue

                    # Extract function name
                    func_match = re.search(r'def\s+(\w+)', lines[func_line])
                    function_name = func_match.group(1) if func_match else 'unknown'

                    # Extract callback components
                    components = extract_callback_components(decorator_content)

                    # Analyze function complexity
                    function_analysis = analyze_callback_function(content, decorator_start)

                    callback_info = CallbackInfo(
                        file_path=str(file_path),
                        line_number=decorator_start + 1,  # 1-indexed
                        function_name=function_name,
                        outputs=[f"{comp[0]}.{comp[1]}" for comp in components['outputs']],
                        inputs=[f"{comp[0]}.{comp[1]}" for comp in components['inputs']],
                        states=[f"{comp[0]}.{comp[1]}" for comp in components['states']],
                        output_count=len(components['outputs']),
                        input_count=len(components['inputs']),
                        state_count=len(components['states']),
                        complexity_score=0,  # Will be calculated in __post_init__
                        pattern_matching=function_analysis['pattern_matching'],
                        has_prevent_update=function_analysis['has_prevent_update'],
                        callback_context_used=function_analysis['callback_context_used']
                    )

                    callbacks.append(callback_info)

                except Exception as e:
                    print(f"Error analyzing callback at {file_path}:{i+1}: {e}")
                    continue

    except Exception as e:
        print(f"Error reading file {file_path}: {e}")

    return callbacks

def analyze_dash_callbacks() -> List[CallbackInfo]:
    """Scan all Python files in depictio/dash for callbacks"""
    dash_path = Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash")
    all_callbacks = []

    if not dash_path.exists():
        print(f"Error: {dash_path} does not exist")
        return all_callbacks

    # Find all Python files
    python_files = list(dash_path.rglob("*.py"))
    print(f"Scanning {len(python_files)} Python files in {dash_path}")

    for py_file in python_files:
        callbacks = scan_file_for_callbacks(py_file)
        all_callbacks.extend(callbacks)
        if callbacks:
            print(f"Found {len(callbacks)} callbacks in {py_file.relative_to(dash_path)}")

    return all_callbacks

def generate_analysis_report(callbacks: List[CallbackInfo]) -> str:
    """Generate comprehensive analysis report"""
    # Sort by various criteria
    by_output_count = sorted(callbacks, key=lambda c: c.output_count, reverse=True)
    by_complexity = sorted(callbacks, key=lambda c: c.complexity_score, reverse=True)
    by_total_io = sorted(callbacks, key=lambda c: c.output_count + c.input_count + c.state_count, reverse=True)

    report = []
    report.append("=" * 80)
    report.append("COMPREHENSIVE DASH CALLBACK ANALYSIS REPORT")
    report.append("=" * 80)

    report.append(f"\nOVERVIEW:")
    report.append(f"Total callbacks found: {len(callbacks)}")
    report.append(f"Files analyzed: {len(set(c.file_path for c in callbacks))}")

    # Summary statistics
    total_outputs = sum(c.output_count for c in callbacks)
    total_inputs = sum(c.input_count for c in callbacks)
    total_states = sum(c.state_count for c in callbacks)

    report.append(f"Total outputs: {total_outputs}")
    report.append(f"Total inputs: {total_inputs}")
    report.append(f"Total states: {total_states}")
    report.append(f"Average outputs per callback: {total_outputs/len(callbacks):.1f}")
    report.append(f"Average complexity score: {sum(c.complexity_score for c in callbacks)/len(callbacks):.1f}")

    # Pattern analysis
    pattern_matching_count = sum(1 for c in callbacks if c.pattern_matching)
    context_usage_count = sum(1 for c in callbacks if c.callback_context_used)
    prevent_update_count = sum(1 for c in callbacks if c.has_prevent_update)

    report.append(f"\nPATTERN ANALYSIS:")
    report.append(f"Callbacks using pattern matching: {pattern_matching_count} ({pattern_matching_count/len(callbacks)*100:.1f}%)")
    report.append(f"Callbacks using callback_context: {context_usage_count} ({context_usage_count/len(callbacks)*100:.1f}%)")
    report.append(f"Callbacks with PreventUpdate: {prevent_update_count} ({prevent_update_count/len(callbacks)*100:.1f}%)")

    # Top callbacks by output count
    report.append(f"\n" + "=" * 80)
    report.append("TOP 25 CALLBACKS BY OUTPUT COUNT")
    report.append("=" * 80)

    for i, callback in enumerate(by_output_count[:25], 1):
        relative_path = Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash"))
        report.append(f"\n{i:2d}. {callback.function_name}")
        report.append(f"    File: {relative_path}:{callback.line_number}")
        report.append(f"    Outputs: {callback.output_count}, Inputs: {callback.input_count}, States: {callback.state_count}")
        report.append(f"    Complexity Score: {callback.complexity_score}")
        report.append(f"    Features: {'Pattern' if callback.pattern_matching else ''} {'Context' if callback.callback_context_used else ''} {'PreventUpdate' if callback.has_prevent_update else ''}")

        if callback.output_count > 1:
            report.append(f"    Output targets: {', '.join(callback.outputs[:3])}{'...' if len(callback.outputs) > 3 else ''}")

    # Performance impact analysis
    report.append(f"\n" + "=" * 80)
    report.append("PERFORMANCE IMPACT ANALYSIS")
    report.append("=" * 80)

    high_output_callbacks = [c for c in callbacks if c.output_count >= 4]
    complex_callbacks = [c for c in callbacks if c.complexity_score >= 10]

    report.append(f"\nHIGH OUTPUT COUNT CALLBACKS (≥4 outputs): {len(high_output_callbacks)}")
    report.append(f"These callbacks are most likely to cause performance issues due to:")
    report.append(f"- Extensive context serialization/deserialization")
    report.append(f"- Multiple DOM updates in single transaction")
    report.append(f"- Increased memory usage for callback queuing")

    for callback in high_output_callbacks[:10]:
        relative_path = Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash"))
        report.append(f"  • {callback.function_name} ({callback.output_count} outputs) - {relative_path}:{callback.line_number}")

    report.append(f"\nCOMPLEX CALLBACKS (complexity ≥10): {len(complex_callbacks)}")
    for callback in complex_callbacks[:10]:
        relative_path = Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash"))
        report.append(f"  • {callback.function_name} (score: {callback.complexity_score}) - {relative_path}:{callback.line_number}")

    # File-based analysis
    report.append(f"\n" + "=" * 80)
    report.append("FILE-BASED CALLBACK DISTRIBUTION")
    report.append("=" * 80)

    file_stats = {}
    for callback in callbacks:
        relative_path = str(Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash")))
        if relative_path not in file_stats:
            file_stats[relative_path] = {'count': 0, 'total_outputs': 0, 'avg_complexity': 0, 'callbacks': []}

        file_stats[relative_path]['count'] += 1
        file_stats[relative_path]['total_outputs'] += callback.output_count
        file_stats[relative_path]['callbacks'].append(callback)

    # Calculate averages
    for file_path, stats in file_stats.items():
        stats['avg_complexity'] = sum(c.complexity_score for c in stats['callbacks']) / len(stats['callbacks'])

    # Sort by callback count
    sorted_files = sorted(file_stats.items(), key=lambda x: x[1]['count'], reverse=True)

    report.append(f"\nTOP FILES BY CALLBACK COUNT:")
    for i, (file_path, stats) in enumerate(sorted_files[:15], 1):
        report.append(f"{i:2d}. {file_path}")
        report.append(f"    Callbacks: {stats['count']}, Total outputs: {stats['total_outputs']}")
        report.append(f"    Avg complexity: {stats['avg_complexity']:.1f}")

    # Recommendations
    report.append(f"\n" + "=" * 80)
    report.append("OPTIMIZATION RECOMMENDATIONS")
    report.append("=" * 80)

    report.append(f"\n1. HIGH-PRIORITY OPTIMIZATIONS:")
    report.append(f"   - Focus on callbacks with ≥5 outputs (context serialization overhead)")
    report.append(f"   - Consider splitting multi-output callbacks into smaller, focused ones")
    report.append(f"   - Use background callbacks for heavy computations")

    report.append(f"\n2. ARCHITECTURE IMPROVEMENTS:")
    report.append(f"   - Implement component-level rendering patterns")
    report.append(f"   - Use clientside callbacks for simple UI state changes")
    report.append(f"   - Consider dcc.Store optimization (avoid heavy objects)")

    report.append(f"\n3. PATTERN MATCHING OPTIMIZATION:")
    report.append(f"   - {pattern_matching_count} callbacks use pattern matching")
    report.append(f"   - These may benefit from more targeted input/output patterns")

    critical_callbacks = [c for c in by_output_count[:10]]
    report.append(f"\n4. CRITICAL CALLBACKS TO REVIEW:")
    for callback in critical_callbacks:
        relative_path = Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash"))
        report.append(f"   - {callback.function_name}: {callback.output_count} outputs, complexity {callback.complexity_score}")
        report.append(f"     Location: {relative_path}:{callback.line_number}")

    return '\n'.join(report)

def main():
    print("Starting comprehensive callback analysis...")
    callbacks = analyze_dash_callbacks()

    if not callbacks:
        print("No callbacks found!")
        return

    print(f"\nAnalysis complete. Found {len(callbacks)} callbacks total.")

    # Generate and save report
    report = generate_analysis_report(callbacks)

    with open('callback_analysis_report.txt', 'w') as f:
        f.write(report)

    print("Report saved to callback_analysis_report.txt")
    print("\n" + "="*50)
    print("SUMMARY OF FINDINGS:")
    print("="*50)

    # Quick summary for immediate review
    by_output_count = sorted(callbacks, key=lambda c: c.output_count, reverse=True)
    print(f"Total callbacks: {len(callbacks)}")
    print(f"Max outputs in single callback: {by_output_count[0].output_count} ({by_output_count[0].function_name})")
    print(f"Callbacks with ≥4 outputs: {len([c for c in callbacks if c.output_count >= 4])}")
    print(f"Callbacks with ≥5 outputs: {len([c for c in callbacks if c.output_count >= 5])}")

    print(f"\nTop 5 callbacks by output count:")
    for i, callback in enumerate(by_output_count[:5], 1):
        relative_path = Path(callback.file_path).relative_to(Path("/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio/dash"))
        print(f"{i}. {callback.function_name}: {callback.output_count} outputs ({relative_path})")

if __name__ == "__main__":
    main()
