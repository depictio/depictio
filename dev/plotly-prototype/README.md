# Plotly Code Prototype

A secure Python/Plotly code execution environment that leverages the figure component builder logic from depictio/dash.

## Features

### 🔒 Security Features
- **Secure Code Execution**: Only allows safe Python/Plotly operations
- **AST-based Validation**: Code is parsed and validated before execution
- **Restricted Imports**: Only pandas, plotly, numpy, datetime, and math modules allowed
- **No File System Access**: Cannot read/write files or execute system commands
- **No Network Operations**: Cannot make HTTP requests or network calls
- **Injection Protection**: Prevents code injection vulnerabilities

### 📊 Data & Visualization
- **Multiple Sample Datasets**: Scatter, time series, bar chart, and histogram data
- **Real-time Plot Generation**: Instant visualization updates
- **Code Examples Library**: Pre-built examples for common plot types
- **Interactive UI**: Modern, responsive interface with Dash Mantine Components

### 💻 Developer Experience
- **Syntax Highlighting**: Monospace font for code readability
- **Error Messages**: Clear feedback on security violations and execution errors
- **Data Preview**: Toggle-able dataset preview with shape and column information
- **Theme Support**: Consistent styling with depictio theme system

## Files

### Core Files
- `plotly_prototype_app.py` - Main Dash application
- `secure_code_executor.py` - Security validation and code execution engine
- `plotly_code_prototype.py` - Simple version (legacy)

### Security Architecture

#### SecureCodeValidator
- Validates Python code using AST parsing
- Blocks dangerous patterns (file I/O, network, system calls)
- Restricts imports to safe modules only
- Prevents access to dangerous Python features

#### SecureCodeExecutor
- Executes validated code in restricted environment
- Provides safe globals (df, pd, px, go, np)
- Captures and returns Plotly figures
- Comprehensive error handling

## Usage

### Setup
```bash
# Navigate to plotly-prototype directory
cd dev/plotly-prototype/

# Install dependencies
pip install -r requirements.txt

# Or install manually:
pip install dash dash-mantine-components plotly pandas numpy dash-ace
```

### Running the App
```python
# In Python console or script
from plotly_prototype_app import main
app = main()
app.run_server(debug=True)
```

### Example Code Patterns

#### Basic Scatter Plot
```python
fig = px.scatter(df, x='x', y='y', 
                 color='category', 
                 size='size',
                 title='Interactive Scatter Plot')
```

#### Time Series
```python
fig = px.line(df, x='date', y='value', 
              color='category',
              title='Time Series Line Chart')
```

#### Custom Styling
```python
fig = px.scatter(df, x='x', y='y', color='category')
fig.update_layout(
    title='Custom Styled Plot',
    xaxis_title='X Axis',
    yaxis_title='Y Axis',
    font=dict(size=14),
    plot_bgcolor='rgba(0,0,0,0)'
)
```

#### Data Processing
```python
# Pandas operations are allowed
df_grouped = df.groupby('category').agg({
    'sales': 'sum',
    'profit': 'mean'
}).reset_index()

fig = px.bar(df_grouped, x='category', y='sales',
            title='Aggregated Sales by Category')
```

## Security Details

### Allowed Operations
- **Pandas**: DataFrame operations, groupby, merge, pivot, etc.
- **Plotly Express**: All px.* functions (scatter, line, bar, etc.)
- **Plotly Graph Objects**: Figure, Scatter, Bar, Line, etc.
- **Numpy**: Array operations, math functions, statistics
- **Python Builtins**: Safe functions like len, str, int, float, etc.

### Blocked Operations
- **File I/O**: open(), file(), input()
- **System Calls**: os.system(), subprocess, etc.
- **Network**: requests, urllib, socket
- **Code Execution**: eval(), exec(), compile()
- **Introspection**: globals(), locals(), getattr()
- **Imports**: Any module not in allowed list

### Validation Process
1. **Pattern Matching**: Regex patterns detect dangerous code
2. **AST Parsing**: Code is parsed into Abstract Syntax Tree
3. **Node Validation**: Each AST node is checked for safety
4. **Import Validation**: Only whitelisted modules allowed
5. **Execution**: Code runs in restricted environment

## Sample Datasets

### Scatter Dataset
- **x, y**: Numeric coordinates
- **category**: Categorical grouping (A, B)
- **size**: Point sizes for bubble charts
- **color_val**: Numeric values for color mapping

### Time Series Dataset
- **date**: Date range (100 days)
- **value**: Cumulative random walk
- **category**: Product categories
- **sales**: Random sales values

### Bar Chart Dataset
- **category**: Product categories
- **sales**: Sales amounts
- **profit**: Profit values
- **region**: Geographic regions

### Histogram Dataset
- **values**: Normal distribution (mean=100, std=15)
- **group**: Random grouping (Group 1, 2, 3)

## Integration with Depictio

The prototype leverages depictio's figure component architecture:

### Imported Utilities
- `render_figure()` - Core figure rendering function
- `get_available_visualizations()` - Visualization discovery
- Theme integration patterns
- Parameter validation patterns

### Design Patterns
- **Component Architecture**: Modular design following depictio patterns
- **State Management**: Consistent state handling
- **Error Handling**: User-friendly error messages
- **Theme Support**: CSS variable integration

## Extending the Prototype

### Adding New Datasets
```python
# In create_sample_datasets()
datasets['new_dataset'] = pd.DataFrame({
    'column1': [1, 2, 3],
    'column2': ['A', 'B', 'C']
})
```

### Adding Code Examples
```python
# In create_code_examples()
examples['New Example'] = '''
fig = px.scatter(df, x='col1', y='col2')
fig.update_layout(title='New Example')
'''
```

### Security Customization
```python
# In SecureCodeValidator.ALLOWED_MODULES
'new_module': {
    'alias': ['function1', 'function2']
}
```

## Troubleshooting

### Common Issues
1. **"Import not allowed"**: Module not in whitelist
2. **"Security violation"**: Code contains dangerous patterns
3. **"No figure found"**: Code doesn't create a Plotly figure
4. **"Execution error"**: Python runtime error

### Debug Tips
- Use print() statements for debugging (allowed)
- Check dataset columns with dataset preview
- Start with simple examples and build complexity
- Review error messages for specific security violations

## Development Notes

### Performance Considerations
- DataFrame operations are performed on copies
- AST parsing adds validation overhead
- Execution is sandboxed for security
- Large datasets may impact performance

### Future Enhancements
- More visualization types
- Custom dataset upload
- Code sharing/saving
- Advanced security features
- Performance optimizations

## Security Disclaimer

This prototype is designed for educational and development purposes. While it implements comprehensive security measures, it should not be used in production environments without additional security review and testing.