# RangeSlider Prototypes

This directory contains prototypes for testing DMC RangeSlider components with depictio integration.

## Version 4 Features

### version4_basic_rangeslider.py
- **DMC 2.0+ RangeSlider components** with null value handling
- **Theme compatibility** (light/dark mode support)
- **Custom color personalization** support
- **Linear/Log10 scale selection**
- **Configurable marks** (3-10 marks)
- **Proper value validation** and cleaning
- **Interactive testing** interface

### Key Improvements Over Previous Versions
- Fixed `defaultValue` error by using only `value` property
- Enhanced null value handling for database-stored nulls
- Added DMC-specific persistence properties
- Improved mark generation with user-configurable count
- Better error handling and logging

### Usage

```bash
# Method 1: Run the prototype directly
cd /Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev_rangeslider_prototypes/
python version4_basic_rangeslider.py

# Method 2: Use the run script
./run_prototype.sh

# Method 3: Run tests first, then prototype
python test_prototype.py
python version4_basic_rangeslider.py
```

Navigate to `http://localhost:8086` to test the prototype.

### Testing Scenarios

1. **Null Value Handling**: Test with null values from database
2. **Scale Selection**: Test linear vs log10 scale switching
3. **Color Customization**: Test custom color application
4. **Mark Configuration**: Test different mark counts (3-10)
5. **Value Persistence**: Test user interaction persistence
6. **Range Validation**: Test min/max validation and clamping

### Integration Points

- Uses utilities from `/depictio/dash/modules/interactive_component/utils.py`
- Follows DMC 2.0+ component standards
- Theme-aware styling with CSS variables
- Compatible with depictio's edit system architecture

### Port Assignment

- **Port 8086**: version4_basic_rangeslider.py