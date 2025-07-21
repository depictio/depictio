"""
Test script for security features of the Plotly code prototype
"""

import pandas as pd

# Import from same directory
from secure_code_executor import SecureCodeExecutor, SecureCodeValidator


def test_security_features():
    """Test various security features"""

    # Create test DataFrame
    df = pd.DataFrame(
        {"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10], "category": ["A", "B", "A", "B", "A"]}
    )

    # Initialize executor
    executor = SecureCodeExecutor(df)
    validator = SecureCodeValidator()

    print("🔒 Testing Security Features")
    print("=" * 50)

    # Test cases: (description, code, should_pass)
    test_cases = [
        # Valid cases
        ("Valid scatter plot", "fig = px.scatter(df, x='x', y='y')", True),
        ("Valid line plot", "fig = px.line(df, x='x', y='y', color='category')", True),
        (
            "Valid pandas operations",
            "df_new = df.groupby('category').mean(); fig = px.bar(df_new, x=df_new.index, y='x')",
            True,
        ),
        (
            "Valid numpy operations",
            "import numpy as np; fig = px.scatter(df, x='x', y=np.log(df['y']))",
            True,
        ),
        # Invalid cases - dangerous imports
        ("Import os", "import os; fig = px.scatter(df, x='x', y='y')", False),
        ("Import sys", "import sys; fig = px.scatter(df, x='x', y='y')", False),
        ("Import subprocess", "import subprocess; fig = px.scatter(df, x='x', y='y')", False),
        ("Import requests", "import requests; fig = px.scatter(df, x='x', y='y')", False),
        ("Import socket", "import socket; fig = px.scatter(df, x='x', y='y')", False),
        # Invalid cases - dangerous functions
        ("Use eval", "eval('print(\"test\")'); fig = px.scatter(df, x='x', y='y')", False),
        ("Use exec", "exec('print(\"test\")'); fig = px.scatter(df, x='x', y='y')", False),
        ("Use open", "open('test.txt', 'w'); fig = px.scatter(df, x='x', y='y')", False),
        ("Use __import__", "__import__('os'); fig = px.scatter(df, x='x', y='y')", False),
        ("Use globals", "globals(); fig = px.scatter(df, x='x', y='y')", False),
        # Invalid cases - dangerous attributes
        ("Access __globals__", "df.__globals__; fig = px.scatter(df, x='x', y='y')", False),
        ("Access __builtins__", "df.__builtins__; fig = px.scatter(df, x='x', y='y')", False),
        ("Access __code__", "test.__code__; fig = px.scatter(df, x='x', y='y')", False),
        # Invalid cases - system operations
        ("System call", "os.system('ls'); fig = px.scatter(df, x='x', y='y')", False),
        (
            "File operations",
            "with open('test.txt', 'w') as f: f.write('test'); fig = px.scatter(df, x='x', y='y')",
            False,
        ),
        # Edge cases
        ("No figure created", "x = 1 + 1", False),
        ("Syntax error", "fig = px.scatter(df, x='x', y='y'", False),
        ("Invalid column", "fig = px.scatter(df, x='nonexistent', y='y')", False),
    ]

    passed = 0
    failed = 0

    for description, code, should_pass in test_cases:
        print(f"\n📝 Testing: {description}")
        print(f"Code: {code[:60]}{'...' if len(code) > 60 else ''}")

        # Test validation
        is_valid, error_msg = validator.validate_code(code)

        # Test execution
        success, result, exec_error = executor.execute_code(code)

        expected_result = should_pass
        actual_result = success

        if actual_result == expected_result:
            print(f"✅ PASS - {'Allowed' if success else 'Blocked'}")
            passed += 1
        else:
            print(
                f"❌ FAIL - Expected: {'Pass' if expected_result else 'Fail'}, Got: {'Pass' if actual_result else 'Fail'}"
            )
            if not success:
                print(f"   Error: {exec_error}")
            failed += 1

    print(f"\n📊 Results: {passed} passed, {failed} failed")
    print(f"Success rate: {passed / (passed + failed) * 100:.1f}%")

    return passed, failed


def test_allowed_operations():
    """Test that allowed operations work correctly"""

    print("\n🎯 Testing Allowed Operations")
    print("=" * 50)

    df = pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 5],
            "y": [2, 4, 6, 8, 10],
            "category": ["A", "B", "A", "B", "A"],
            "value": [10, 20, 30, 40, 50],
        }
    )

    executor = SecureCodeExecutor(df)

    # Test various allowed operations
    allowed_operations = [
        ("Scatter plot", "fig = px.scatter(df, x='x', y='y', color='category')"),
        ("Line plot", "fig = px.line(df, x='x', y='y')"),
        ("Bar plot", "fig = px.bar(df, x='category', y='value')"),
        ("Histogram", "fig = px.histogram(df, x='y')"),
        ("Box plot", "fig = px.box(df, x='category', y='value')"),
        (
            "Pandas groupby",
            "df_agg = df.groupby('category').mean(); fig = px.bar(df_agg, x=df_agg.index, y='x')",
        ),
        ("Numpy operations", "import numpy as np; fig = px.scatter(df, x='x', y=np.sqrt(df['y']))"),
        (
            "Custom styling",
            "fig = px.scatter(df, x='x', y='y'); fig.update_layout(title='Test Plot')",
        ),
        (
            "Multiple traces",
            "import plotly.graph_objects as go; fig = go.Figure(); fig.add_trace(go.Scatter(x=df['x'], y=df['y'], mode='markers'))",
        ),
        (
            "Date operations",
            "from datetime import datetime; fig = px.scatter(df, x='x', y='y', title=str(datetime.now()))",
        ),
    ]

    for description, code in allowed_operations:
        print(f"\n📝 Testing: {description}")
        success, result, error = executor.execute_code(code)

        if success:
            print("✅ SUCCESS - Figure created")
        else:
            print(f"❌ FAILED - {error}")


def test_environment_info():
    """Test environment information"""

    print("\n🔍 Testing Environment Info")
    print("=" * 50)

    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    executor = SecureCodeExecutor(df)

    env_info = executor.get_safe_environment_info()

    print(f"Available modules: {env_info['available_modules']}")
    print(f"DataFrame shape: {env_info['dataframe_shape']}")
    print(f"DataFrame columns: {env_info['dataframe_columns']}")
    print(f"Restricted builtins: {len(env_info['restricted_builtins'])} functions")


def main():
    """Run all tests"""
    print("🚀 Security Test Suite for Plotly Code Prototype")
    print("=" * 60)

    try:
        # Test security features
        passed, failed = test_security_features()

        # Test allowed operations
        test_allowed_operations()

        # Test environment info
        test_environment_info()

        print("\n🎉 All tests completed!")
        print(f"Overall security validation: {'PASS' if failed == 0 else 'NEEDS REVIEW'}")

    except Exception as e:
        print(f"❌ Test suite failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
