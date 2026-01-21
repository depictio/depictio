# Code Mode Visualization Examples

This guide provides 15 different Plotly Express visualization commands for the penguin dataset, demonstrating various chart types and data preprocessing patterns.

## Dataset Schema

The penguin dataset contains the following columns:
- `individual_id` (text) - Penguin identifier
- `bill_length_mm` (float) - Bill length measurement
- `bill_depth_mm` (float) - Bill depth measurement
- `flipper_length_mm` (float) - Flipper length measurement
- `body_mass_g` (float) - Body mass in grams
- `depictio_run_id` (text) - Run identifier
- `aggregation_time` (text) - Timestamp

## Basic Visualizations

### 1. Simple Scatter Plot
```python
fig = px.scatter(df.to_pandas(), x='bill_length_mm', y='flipper_length_mm', title='Bill vs Flipper Length')
```

### 2. Scatter with Color Encoding
```python
# Color by body mass to show relationships
fig = px.scatter(df.to_pandas(),
                 x='bill_length_mm',
                 y='flipper_length_mm',
                 color='body_mass_g',
                 title='Bill vs Flipper Length (colored by body mass)',
                 labels={'bill_length_mm': 'Bill Length (mm)',
                         'flipper_length_mm': 'Flipper Length (mm)',
                         'body_mass_g': 'Body Mass (g)'})
```

### 3. Scatter with Size Encoding
```python
# Size by body mass, good for multivariate analysis
fig = px.scatter(df.to_pandas(),
                 x='bill_length_mm',
                 y='bill_depth_mm',
                 size='body_mass_g',
                 title='Bill Dimensions (sized by body mass)',
                 labels={'bill_length_mm': 'Bill Length (mm)',
                         'bill_depth_mm': 'Bill Depth (mm)'})
```

### 4. 3D Scatter Plot
```python
# 3D visualization of three continuous variables
fig = px.scatter_3d(df.to_pandas(),
                    x='bill_length_mm',
                    y='bill_depth_mm',
                    z='flipper_length_mm',
                    color='body_mass_g',
                    title='3D Penguin Measurements')
```

## Distribution Analysis

### 5. Box Plot
```python
# Compare distributions across runs
fig = px.box(df.to_pandas(),
             x='depictio_run_id',
             y='body_mass_g',
             title='Body Mass Distribution by Run',
             labels={'body_mass_g': 'Body Mass (g)',
                     'depictio_run_id': 'Run ID'})
```

### 6. Violin Plot
```python
# More detailed distribution visualization
fig = px.violin(df.to_pandas(),
                y='flipper_length_mm',
                x='depictio_run_id',
                box=True,
                title='Flipper Length Distribution by Run',
                labels={'flipper_length_mm': 'Flipper Length (mm)'})
```

### 7. Histogram
```python
# Distribution of a single measurement
fig = px.histogram(df.to_pandas(),
                   x='bill_length_mm',
                   nbins=30,
                   title='Bill Length Distribution',
                   labels={'bill_length_mm': 'Bill Length (mm)'})
```

### 8. Scatter with Marginal Distributions
```python
# 2D distribution with marginal histograms
fig = px.scatter(df.to_pandas(),
                 x='bill_length_mm',
                 y='flipper_length_mm',
                 marginal_x='histogram',
                 marginal_y='histogram',
                 title='Bill vs Flipper with Marginal Distributions')
```

## Advanced Visualizations

### 9. Density Heatmap
```python
# 2D density visualization
fig = px.density_heatmap(df.to_pandas(),
                         x='bill_length_mm',
                         y='flipper_length_mm',
                         nbinsx=20,
                         nbinsy=20,
                         title='Density Heatmap: Bill vs Flipper Length')
```

### 10. Parallel Coordinates
```python
# Show relationships across all numeric dimensions
df_pd = df.to_pandas()
fig = px.parallel_coordinates(df_pd,
                              dimensions=['bill_length_mm', 'bill_depth_mm',
                                         'flipper_length_mm', 'body_mass_g'],
                              title='Parallel Coordinates: All Measurements')
```

### 11. Scatter Matrix
```python
# Pairwise scatter plots for all numeric columns
fig = px.scatter_matrix(df.to_pandas(),
                        dimensions=['bill_length_mm', 'bill_depth_mm',
                                   'flipper_length_mm', 'body_mass_g'],
                        title='Pairwise Relationships: All Measurements')
```

### 12. Contour Plot
```python
# Contour density visualization
fig = px.density_contour(df.to_pandas(),
                         x='bill_length_mm',
                         y='flipper_length_mm',
                         title='Density Contours: Bill vs Flipper')
```

## Preprocessing Examples

### 13. Data Filtering
```python
# Filter and visualize
df_modified = df.filter(pl.col('body_mass_g') > 4000)
fig = px.scatter(df_modified.to_pandas(),
                 x='bill_length_mm',
                 y='flipper_length_mm',
                 title='Large Penguins Only (>4000g)')
```

### 14. Data Aggregation
```python
# Group by run and calculate mean
df_modified = (df.group_by('depictio_run_id')
                 .agg([pl.mean('bill_length_mm').alias('avg_bill_length'),
                       pl.mean('flipper_length_mm').alias('avg_flipper_length')]))
fig = px.bar(df_modified.to_pandas(),
             x='depictio_run_id',
             y='avg_bill_length',
             title='Average Bill Length by Run')
```

### 15. Hierarchical Visualization
```python
# Create hierarchical grouping
df_modified = df.with_columns([
    (pl.col('body_mass_g') // 500 * 500).alias('mass_group')
])
fig = px.sunburst(df_modified.to_pandas(),
                  path=['depictio_run_id', 'mass_group'],
                  values='body_mass_g',
                  title='Hierarchical Body Mass Distribution')
```

## Usage Tips

### Pattern Requirements
- All commands must follow: `fig = px.function(...)`
- For preprocessing, define `df_modified` variable
- Use `df.to_pandas()` for Plotly Express (requires pandas DataFrame)
- Polars operations (filter, group_by, with_columns) work on `df` directly

### Common Plotly Express Functions
- `px.scatter()` - 2D scatter plots
- `px.scatter_3d()` - 3D scatter plots
- `px.scatter_matrix()` - Pairwise scatter plots
- `px.line()` - Line charts
- `px.bar()` - Bar charts
- `px.box()` - Box plots
- `px.violin()` - Violin plots
- `px.histogram()` - Histograms
- `px.density_heatmap()` - 2D density heatmaps
- `px.density_contour()` - Contour density plots
- `px.parallel_coordinates()` - Parallel coordinates
- `px.sunburst()` - Hierarchical sunburst charts

### Polars Preprocessing
- `df.filter()` - Filter rows
- `df.group_by().agg()` - Aggregate data
- `df.with_columns()` - Add/modify columns
- `pl.col()` - Reference column
- `pl.mean()`, `pl.sum()`, `pl.count()` - Aggregation functions

## Background Execution

As of the latest update, code execution runs in the background using Celery workers. This means:

- ✅ UI remains responsive during code execution
- ✅ Loading spinner shows automatically
- ✅ You can edit code, scroll, or navigate while execution runs
- ✅ Data loading and figure generation don't block the dashboard

**Requirements**: Celery worker must be running (automatically started in development mode).
