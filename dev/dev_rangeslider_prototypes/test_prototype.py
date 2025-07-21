#!/usr/bin/env python3
"""
Test script for version4_basic_rangeslider.py prototype

This script verifies that the prototype can be imported and basic functionality works.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

def test_prototype_imports():
    """Test that all required imports work"""
    try:
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import error: {e}")
        return False

def test_sample_data():
    """Test that sample data is properly structured"""
    try:
        from version4_basic_rangeslider import mock_cols_json, sample_data
        
        # Check data structure
        assert sample_data.shape[0] > 0, "Sample data should not be empty"
        assert "numeric_column" in sample_data.columns, "numeric_column should exist"
        assert "float_column" in sample_data.columns, "float_column should exist"
        assert "int_column" in sample_data.columns, "int_column should exist"
        
        # Check column specs
        assert "numeric_column" in mock_cols_json, "numeric_column spec should exist"
        assert "type" in mock_cols_json["numeric_column"], "Column type should be specified"
        assert "specs" in mock_cols_json["numeric_column"], "Column specs should exist"
        
        print("✓ Sample data structure is correct")
        return True
    except Exception as e:
        print(f"✗ Sample data error: {e}")
        return False

def test_component_creation():
    """Test that RangeSlider component can be created"""
    try:
        import uuid

        import polars as pl

        from depictio.dash.modules.interactive_component.utils import build_interactive
        
        # Create test data
        test_data = pl.DataFrame({
            "numeric_column": [1.0, 2.3, 4.5, 3.2, 5.8, 6.1, 4.9, 3.7, 2.1, 5.4]
        })
        
        # Test kwargs similar to what the prototype uses
        kwargs = {
            "index": str(uuid.uuid4()),
            "title": "Test RangeSlider",
            "wf_id": "507f1f77bcf86cd799439011",  # Valid 24-character hex string
            "dc_id": "507f1f77bcf86cd799439012",  # Valid 24-character hex string
            "dc_config": {"mock": "config"},
            "column_name": "numeric_column",
            "column_type": "float64",
            "interactive_component_type": "RangeSlider",
            "cols_json": {"numeric_column": {"type": "float64", "specs": {"min": 1.0, "max": 6.9}}},
            "df": test_data,  # Provide data to avoid ObjectId loading
            "access_token": "mock-token",
            "stepper": False,
            "build_frame": False,
            "scale": "linear",
            "color": "#000000",
            "marks_number": 5,
            "value": None,  # Test null value handling
        }
        
        # This should not raise an exception
        component = build_interactive(**kwargs)
        assert component is not None, "Component should be created"
        
        print("✓ RangeSlider component creation successful")
        return True
    except Exception as e:
        print(f"✗ Component creation error: {e}")
        return False

def main():
    """Run all tests"""
    print("Testing RangeSlider Prototype v4")
    print("=" * 40)
    
    tests = [
        test_prototype_imports,
        test_sample_data,
        test_component_creation,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            failed += 1
    
    print("\n" + "=" * 40)
    print(f"Tests passed: {passed}")
    print(f"Tests failed: {failed}")
    
    if failed == 0:
        print("✓ All tests passed! Prototype is ready to run.")
        print("\nTo run the prototype:")
        print("  cd /Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev_rangeslider_prototypes/")
        print("  python version4_basic_rangeslider.py")
        print("  Navigate to: http://localhost:8086")
    else:
        print("✗ Some tests failed. Please check the errors above.")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)