"""
EXTREME Stress Test - ASYNC VERSION with 1GB Dataframes and Real Plots

This implementation uses massive 1GB+ dataframes with actual scatter plots
to stress test the async performance benefits. Each component renders real
Plotly visualizations from huge datasets.

WARNING: This will use significant CPU and memory!
"""

import asyncio
import time
import random
import numpy as np
import psutil
from datetime import datetime, timedelta
from typing import List, Dict, Any

from dash import Dash, html, dcc, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import polars as pl


# Initialize Dash app
app = Dash(__name__, 
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
    ],
    assets_folder="/tmp/dash_assets_async",  # Use separate assets folder to prevent conflicts
    assets_url_path="/async_assets/"  # Use separate URL path for assets
)
server = app.server


def generate_massive_dataframe(rows: int, cols: int, name: str) -> pl.DataFrame:
    """Generate a massive 1GB+ polars dataframe for extreme stress testing"""
    print(f"🔥 GENERATING MASSIVE {name} dataframe: {rows:,} rows × {cols} columns...")
    start = time.time()
    
    # Generate realistic high-volume data with polars
    np.random.seed(42)  # For reproducible results
    
    # Generate base timestamp column
    start_date = datetime(2020, 1, 1)
    timestamps = [start_date + timedelta(seconds=i) for i in range(rows)]
    
    base_data = {
        'timestamp': timestamps,
        'value_1': np.random.normal(100, 25, rows),
        'value_2': np.random.exponential(50, rows),
        'category': np.random.choice(['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'], rows),
        'price': np.random.lognormal(4, 1, rows),  # Realistic price distribution
        'volume': np.random.randint(1, 10000, rows),
        'user_id': np.random.randint(1000, 100000, rows),
        'session_duration': np.random.gamma(2, 30, rows),
    }
    
    # Add many more columns to reach 1GB+ size
    for i in range(cols - len(base_data)):
        if i % 4 == 0:
            base_data[f'metric_{i}'] = np.random.random(rows)
        elif i % 4 == 1:
            base_data[f'sensor_{i}'] = np.random.normal(0, 1, rows)
        elif i % 4 == 2:
            base_data[f'feature_{i}'] = np.random.exponential(1, rows)
        else:
            base_data[f'signal_{i}'] = np.random.uniform(-10, 10, rows)
    
    # Create polars dataframe
    df = pl.DataFrame(base_data)
    
    # Calculate actual memory usage (estimated)
    memory_mb = df.estimated_size('mb')
    memory_gb = memory_mb / 1024
    elapsed = time.time() - start
    
    # Get system memory info
    mem_info = get_memory_info()
    
    print(f"✅ Generated {name}: {memory_gb:.2f}GB ({memory_mb:.0f}MB) in {elapsed:.2f}s")
    print(f"   📊 System Memory: {mem_info['system_free_gb']:.1f}GB free / {mem_info['system_total_gb']:.1f}GB total ({100-mem_info['system_usage_percent']:.1f}% free)")
    print(f"   🔥 Process Memory: {mem_info['process_memory_gb']:.2f}GB ({mem_info['process_memory_mb']:.0f}MB)")
    
    return df


class ExtremeAsyncComponentLoader:
    """Handles massive dataframe processing with async loading"""
    
    def __init__(self):
        self.results = {}
    
    async def load_massive_sales_data(self) -> Dict[str, Any]:
        """Load and process massive sales dataset - ~1.2GB"""
        print("🚀 Starting ASYNC massive sales analysis...")
        start_time = time.time()
        
        # Simulate network delay
        await asyncio.sleep(0.5)
        
        # Generate massive dataframe (1.2M rows, 50 columns ≈ 1.2GB)
        df = generate_massive_dataframe(1200000, 50, "Sales Data")
        
        # Heavy processing with real calculations
        await asyncio.sleep(0.1)
        
        # Sample data for plotting (can't plot 1M+ points efficiently)
        plot_sample = df.sample(n=5000)  # Sample for visualization
        
        # Real aggregations on full dataset using polars
        daily_sales = df.with_columns(
            pl.col('timestamp').dt.date().alias('date')
        ).group_by('date').agg([
            pl.col('price').sum().alias('sum'),
            pl.col('price').mean().alias('mean'),
            pl.col('price').count().alias('count')
        ])
        
        category_performance = df.group_by('category').agg([
            pl.col('price').sum().alias('sum'),
            pl.col('price').mean().alias('mean')
        ])
        
        sales_data = {
            'plot_x': plot_sample['value_1'].to_list(),
            'plot_y': plot_sample['price'].to_list(),
            'plot_color': plot_sample['category'].to_list(),
            'total_records': len(df),
            'total_sales': df['price'].sum(),
            'avg_price': df['price'].mean(),
            'daily_stats': daily_sales.tail(30).to_dict(as_series=False),
            'category_stats': category_performance.to_dict(as_series=False),
            'memory_gb': df.estimated_size('mb') / 1024
        }
        
        load_time = time.time() - start_time
        print(f"✅ ASYNC massive sales analysis completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_sales',
            'title': 'Massive Sales Analysis',
            'data': sales_data,
            'raw_df': df,  # Include raw dataframe for dynamic queries
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    async def load_massive_user_data(self) -> Dict[str, Any]:
        """Load and process massive user dataset - ~0.8GB"""
        print("🚀 Starting ASYNC massive user analytics...")
        start_time = time.time()
        
        await asyncio.sleep(0.3)
        
        # Generate massive dataframe (800K rows, 40 columns ≈ 0.8GB)
        df = generate_massive_dataframe(800000, 40, "User Data")
        
        await asyncio.sleep(0.1)
        
        # Sample for plotting
        plot_sample = df.sample(n=4000)
        
        # Real analytics on full dataset using polars
        user_segments = df.group_by('category').agg([
            pl.col('session_duration').mean().alias('mean'),
            pl.col('session_duration').std().alias('std'),
            pl.col('session_duration').count().alias('count')
        ])
        
        hourly_activity = df.with_columns(
            pl.col('timestamp').dt.hour().alias('hour')
        ).group_by('hour').agg(pl.len().alias('count'))
        
        user_data = {
            'plot_x': plot_sample['session_duration'].to_list(),
            'plot_y': plot_sample['value_1'].to_list(),
            'plot_color': plot_sample['category'].to_list(),
            'total_users': len(df),
            'avg_session': df['session_duration'].mean(),
            'user_segments': user_segments.to_dict(as_series=False),
            'hourly_pattern': hourly_activity.to_dict(as_series=False),
            'memory_gb': df.estimated_size('mb') / 1024
        }
        
        load_time = time.time() - start_time
        print(f"✅ ASYNC massive user analytics completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_users',
            'title': 'Massive User Analytics',
            'data': user_data,
            'raw_df': df,  # Include raw dataframe for dynamic queries
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    async def load_massive_financial_data(self) -> Dict[str, Any]:
        """Load and process massive financial dataset - ~1.5GB"""
        print("🚀 Starting ASYNC massive financial analysis...")
        start_time = time.time()
        
        await asyncio.sleep(0.8)
        
        # Generate massive dataframe (1.5M rows, 55 columns ≈ 1.5GB)
        df = generate_massive_dataframe(1500000, 55, "Financial Data")
        
        await asyncio.sleep(0.2)
        
        # Complex financial calculations using polars
        df = df.with_columns([
            (pl.col('price') * pl.col('volume') - (pl.col('price') * pl.col('volume') * 0.1)).alias('profit')
        ]).with_columns([
            ((pl.col('profit') / (pl.col('price') * pl.col('volume'))) * 100).alias('roi')
        ])
        
        # Sample for plotting
        plot_sample = df.sample(n=6000)
        
        # Real financial analytics using polars
        profit_by_category = df.group_by('category').agg(pl.col('profit').sum())
        roi_stats = df.select([
            pl.col('roi').mean().alias('mean'),
            pl.col('roi').std().alias('std'),
            pl.col('roi').min().alias('min'),
            pl.col('roi').max().alias('max')
        ])
        
        financial_data = {
            'plot_x': plot_sample['volume'].to_list(),
            'plot_y': plot_sample['profit'].to_list(),
            'plot_color': plot_sample['category'].to_list(),
            'total_transactions': len(df),
            'total_profit': df['profit'].sum(),
            'avg_roi': df['roi'].mean(),
            'profit_by_category': profit_by_category.to_dict(as_series=False),
            'roi_stats': roi_stats.to_dict(as_series=False),
            'memory_gb': df.estimated_size('mb') / 1024
        }
        
        load_time = time.time() - start_time
        print(f"✅ ASYNC massive financial analysis completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_financial',
            'title': 'Massive Financial Analysis',
            'data': financial_data,
            'raw_df': df,  # Include raw dataframe for dynamic queries
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    async def load_massive_performance_data(self) -> Dict[str, Any]:
        """Load and process massive performance dataset - ~1.0GB"""
        print("🚀 Starting ASYNC massive performance metrics...")
        start_time = time.time()
        
        await asyncio.sleep(0.4)
        
        # Generate massive dataframe (1M rows, 45 columns ≈ 1GB)
        df = generate_massive_dataframe(1000000, 45, "Performance Data")
        
        await asyncio.sleep(0.15)
        
        # Performance analysis using polars
        df = df.with_columns([
            (pl.col('value_1') + np.random.exponential(20, len(df))).alias('response_time')
        ]).with_columns([
            (pl.col('response_time') > 150).cast(pl.Int32).alias('error_rate')
        ])
        
        # Sample for plotting
        plot_sample = df.sample(n=5000)
        
        # Real performance metrics using polars
        perf_by_hour = df.with_columns(
            pl.col('timestamp').dt.hour().alias('hour')
        ).group_by('hour').agg([
            pl.col('response_time').mean().alias('mean'),
            pl.col('response_time').quantile(0.95).alias('p95')
        ])
        
        error_analysis = df.group_by('category').agg(
            pl.col('error_rate').mean().alias('error_rate')
        )
        
        performance_data = {
            'plot_x': plot_sample.with_columns(pl.col('timestamp').dt.hour().alias('hour'))['hour'].to_list(),
            'plot_y': plot_sample['response_time'].to_list(),
            'plot_color': plot_sample['category'].to_list(),
            'total_events': len(df),
            'avg_response_time': df['response_time'].mean(),
            'error_rate': df['error_rate'].mean() * 100,
            'hourly_performance': perf_by_hour.to_dict(as_series=False),
            'error_by_category': error_analysis.to_dict(as_series=False),
            'memory_gb': df.estimated_size('mb') / 1024
        }
        
        load_time = time.time() - start_time
        print(f"✅ ASYNC massive performance metrics completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_performance',
            'title': 'Massive Performance Analysis',
            'data': performance_data,
            'raw_df': df,  # Include raw dataframe for dynamic queries
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }


# Global loader instance - with unique ID for this async app
loader = ExtremeAsyncComponentLoader()
loader.app_id = "async_extreme_test"  # Unique identifier


def get_memory_info() -> Dict[str, float]:
    """Get current memory usage information"""
    process = psutil.Process()
    memory_info = process.memory_info()
    system_memory = psutil.virtual_memory()
    
    return {
        'process_memory_mb': memory_info.rss / 1024 / 1024,
        'process_memory_gb': memory_info.rss / 1024 / 1024 / 1024,
        'system_total_gb': system_memory.total / 1024 / 1024 / 1024,
        'system_used_gb': system_memory.used / 1024 / 1024 / 1024,
        'system_free_gb': system_memory.available / 1024 / 1024 / 1024,
        'system_usage_percent': system_memory.percent
    }


def create_sales_scatter_plot(data: Dict[str, Any], sample_range: List[int] = None) -> dbc.Card:
    """Create massive sales scatter plot with plotly express"""
    # Apply dynamic sampling based on interactive controls
    if sample_range and 'raw_df' in data:
        sample_size = sample_range[1] * 1000  # Convert K to actual count
        df_sample = data['raw_df'].sample(n=min(sample_size, len(data['raw_df'])))
    else:
        df_sample = data['raw_df'].sample(n=5000)  # Default sample
    
    # Convert to pandas for plotly express (it's simpler)
    df_pd = df_sample.to_pandas()
    
    # Create scatter plot with plotly express
    fig = px.scatter(
        df_pd, 
        x='value_1', 
        y='price', 
        color='category',
        title=f"Sales Analysis: {data['records_processed']:,} records ({data['data']['memory_gb']:.2f}GB)",
        labels={'value_1': 'Value Metric', 'price': 'Price ($)', 'category': 'Category'}
    )
    
    fig.update_layout(
        height=350,
        width=600,
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-chart-scatter text-success me-2"),
            f"📊 Sales Scatter - {data['records_processed']:,} records"
        ]),
        dbc.CardBody([
            dcc.Graph(
                figure=fig, 
                config={'displayModeBar': False},
                style={
                    'height': '350px !important', 
                    'width': '100% !important',
                    'maxHeight': '350px',
                    'minHeight': '350px',
                    'overflow': 'hidden'
                }
            ),
            dbc.Row([
                dbc.Col([
                    html.H6(f"{data['data']['memory_gb']:.2f}GB", className="text-info mb-0"),
                    html.Small("Dataset Size", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['load_time']}s", className="text-primary mb-0"),
                    html.Small("⚡ ASYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"${data['data']['total_sales']:,.0f}", className="text-success mb-0"),
                    html.Small("Total Sales", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #28a745'})


def create_user_scatter_plot(data: Dict[str, Any], sample_range: List[int] = None) -> dbc.Card:
    """Create massive user analytics scatter plot with plotly express"""
    # Apply dynamic sampling
    if sample_range and 'raw_df' in data:
        sample_size = sample_range[1] * 1000
        df_sample = data['raw_df'].sample(n=min(sample_size, len(data['raw_df'])))
    else:
        df_sample = data['raw_df'].sample(n=4000)
    
    df_pd = df_sample.to_pandas()
    
    fig = px.scatter(
        df_pd,
        x='session_duration',
        y='value_1', 
        color='category',
        title=f"User Analytics: {data['records_processed']:,} users ({data['data']['memory_gb']:.2f}GB)",
        labels={'session_duration': 'Session Duration (min)', 'value_1': 'User Value', 'category': 'Segment'}
    )
    
    fig.update_layout(
        height=350,
        width=600,
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-users text-info me-2"),
            f"👥 User Analytics - {data['records_processed']:,} users"
        ]),
        dbc.CardBody([
            dcc.Graph(
                figure=fig, 
                config={'displayModeBar': False},
                style={
                    'height': '350px !important', 
                    'width': '100% !important',
                    'maxHeight': '350px',
                    'minHeight': '350px',
                    'overflow': 'hidden'
                }
            ),
            dbc.Row([
                dbc.Col([
                    html.H6(f"{data['data']['memory_gb']:.2f}GB", className="text-warning mb-0"),
                    html.Small("Dataset Size", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['load_time']}s", className="text-primary mb-0"),
                    html.Small("⚡ ASYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['data']['avg_session']:.1f}min", className="text-info mb-0"),
                    html.Small("Avg Session", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #17a2b8'})


def create_financial_scatter_plot(data: Dict[str, Any], sample_range: List[int] = None) -> dbc.Card:
    """Create massive financial analysis scatter plot with plotly express"""
    # Apply dynamic sampling  
    if sample_range and 'raw_df' in data:
        sample_size = sample_range[1] * 1000
        df_sample = data['raw_df'].sample(n=min(sample_size, len(data['raw_df'])))
    else:
        df_sample = data['raw_df'].sample(n=6000)
    
    df_pd = df_sample.to_pandas()
    
    fig = px.scatter(
        df_pd,
        x='volume',
        y='profit',
        color='category', 
        title=f"Financial Analysis: {data['records_processed']:,} transactions ({data['data']['memory_gb']:.2f}GB)",
        labels={'volume': 'Volume', 'profit': 'Profit ($)', 'category': 'Type'}
    )
    
    fig.update_layout(
        height=350,
        width=600,
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-dollar-sign text-warning me-2"),
            f"💰 Financial Analysis - {data['records_processed']:,} transactions"
        ]),
        dbc.CardBody([
            dcc.Graph(
                figure=fig, 
                config={'displayModeBar': False},
                style={
                    'height': '350px !important', 
                    'width': '100% !important',
                    'maxHeight': '350px',
                    'minHeight': '350px',
                    'overflow': 'hidden'
                }
            ),
            dbc.Row([
                dbc.Col([
                    html.H6(f"{data['data']['memory_gb']:.2f}GB", className="text-danger mb-0"),
                    html.Small("Dataset Size", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['load_time']}s", className="text-primary mb-0"),
                    html.Small("⚡ ASYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"${data['data']['total_profit']:,.0f}", className="text-success mb-0"),
                    html.Small("Total Profit", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #ffc107'})


def create_performance_scatter_plot(data: Dict[str, Any], sample_range: List[int] = None) -> dbc.Card:
    """Create massive performance metrics scatter plot with plotly express"""
    # Apply dynamic sampling
    if sample_range and 'raw_df' in data:
        sample_size = sample_range[1] * 1000
        df_sample = data['raw_df'].sample(n=min(sample_size, len(data['raw_df'])))
    else:
        df_sample = data['raw_df'].sample(n=5000)
    
    # Add hour column for plotting
    df_sample = df_sample.with_columns(
        pl.col('timestamp').dt.hour().alias('hour')
    )
    df_pd = df_sample.to_pandas()
    
    fig = px.scatter(
        df_pd,
        x='hour',
        y='response_time',
        color='category',
        title=f"Performance Analysis: {data['records_processed']:,} events ({data['data']['memory_gb']:.2f}GB)",
        labels={'hour': 'Hour of Day', 'response_time': 'Response Time (ms)', 'category': 'Service'}
    )
    
    fig.update_layout(
        height=350,
        width=600,
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-tachometer-alt text-danger me-2"),
            f"⚡ Performance Analysis - {data['records_processed']:,} events"
        ]),
        dbc.CardBody([
            dcc.Graph(
                figure=fig, 
                config={'displayModeBar': False},
                style={
                    'height': '350px !important', 
                    'width': '100% !important',
                    'maxHeight': '350px',
                    'minHeight': '350px',
                    'overflow': 'hidden'
                }
            ),
            dbc.Row([
                dbc.Col([
                    html.H6(f"{data['data']['memory_gb']:.2f}GB", className="text-info mb-0"),
                    html.Small("Dataset Size", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['load_time']}s", className="text-primary mb-0"),
                    html.Small("⚡ ASYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['data']['avg_response_time']:.1f}ms", className="text-success mb-0"),
                    html.Small("Avg Response", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #dc3545'})


def create_error_card(comp_id: str, error_msg: str) -> dbc.Card:
    """Create error display card"""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-exclamation-triangle text-danger me-2"),
            f"❌ Error: {comp_id}"
        ]),
        dbc.CardBody([
            dbc.Alert([
                html.H6("Massive Dataset Processing Failed"),
                html.P(error_msg),
                dbc.Button("Retry", color="outline-danger", size="sm")
            ], color="danger")
        ])
    ], className="h-100", style={'border': '3px solid #dc3545'})


# Massive component configuration
MASSIVE_COMPONENTS = {
    'sales-analysis': {
        'loader': loader.load_massive_sales_data,
        'renderer': create_sales_scatter_plot,
        'title': 'Sales Analysis (1.2GB)',
        'grid': {'col': 'span 6', 'row': 'span 6'}
    },
    'user-analytics': {
        'loader': loader.load_massive_user_data,
        'renderer': create_user_scatter_plot,
        'title': 'User Analytics (0.8GB)',
        'grid': {'col': 'span 6', 'row': 'span 6'}
    },
    'financial-analysis': {
        'loader': loader.load_massive_financial_data,
        'renderer': create_financial_scatter_plot,
        'title': 'Financial Analysis (1.5GB)',
        'grid': {'col': 'span 6', 'row': 'span 6'}
    },
    'performance-metrics': {
        'loader': loader.load_massive_performance_data,
        'renderer': create_performance_scatter_plot,
        'title': 'Performance Analysis (1.0GB)',
        'grid': {'col': 'span 6', 'row': 'span 6'}
    }
}


# App layout
app.layout = dbc.Container([
    # Header
    html.Div([
        html.H1([
            html.I(className="fas fa-rocket me-3 text-success"),
            "EXTREME Stress Test - ASYNC (1GB+ Dataframes)"
        ], className="mb-2"),
        html.P([
            "🔥 EXTREME ASYNC VERSION: 4 massive datasets (~4.5GB total) with real scatter plots! ",
            html.Strong("All load concurrently", className="text-success"),
            " - prepare for intense CPU/memory usage!"
        ], className="lead text-muted mb-4")
    ]),
    
    # Memory Status Alert
    dbc.Row([
        dbc.Col([
            html.Div(id="async-memory-status-card")
        ])
    ], className="mb-3"),
    
    # Warning Alert
    dbc.Row([
        dbc.Col([
            dbc.Alert([
                html.H5([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    "⚠️ EXTREME STRESS TEST WARNING"
                ], className="alert-heading"),
                html.P([
                    "This test processes 4.5M+ records (~4.5GB total memory) and renders real scatter plots. ",
                    html.Strong("Monitor your system resources!", className="text-danger"),
                    " This will stress CPU, memory, and browser rendering."
                ]),
                html.Hr(),
                html.P([
                    "💾 Memory: ~6-8GB RAM recommended | 🚀 CPU: Multi-core strongly recommended"
                ], className="mb-0 small")
            ], color="danger")
        ])
    ], className="mb-4"),
    
    # Interactive Controls
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-sliders-h me-2"),
                    "Interactive Dashboard Controls"
                ]),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Dataset Filter:", className="fw-bold"),
                            dcc.Dropdown(
                                id="dataset-filter",
                                options=[
                                    {'label': 'All Datasets', 'value': 'all'},
                                    {'label': 'Sales Only', 'value': 'sales'},
                                    {'label': 'Users Only', 'value': 'users'},
                                    {'label': 'Financial Only', 'value': 'financial'},
                                    {'label': 'Performance Only', 'value': 'performance'}
                                ],
                                value='all',
                                className="mb-2"
                            )
                        ], width=6),
                        dbc.Col([
                            html.Label("Sample Size (K records):", className="fw-bold"),
                            dcc.RangeSlider(
                                id="sample-size-slider",
                                min=1,
                                max=10,
                                step=1,
                                value=[3, 7],
                                marks={i: f'{i}K' for i in range(1, 11)},
                                tooltip={"placement": "bottom", "always_visible": True}
                            )
                        ], width=6)
                    ])
                ])
            ], className="shadow-sm")
        ])
    ], className="mb-3"),
    
    # Control panel
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.H4([
                                html.I(className="fas fa-fire me-2"),
                                "EXTREME ASYNC Stress Test"
                            ]),
                            html.P("Generate and render 4.5GB of data with scatter plots", className="text-muted")
                        ], width=8),
                        dbc.Col([
                            dbc.ButtonGroup([
                                dbc.Button([
                                    html.I(className="fas fa-rocket me-2"),
                                    "START EXTREME TEST (ASYNC)"
                                ], id="extreme-load-btn", color="danger", size="lg"),
                                dbc.Button([
                                    html.I(className="fas fa-times me-2"),
                                    "Clear"
                                ], id="extreme-clear-btn", color="outline-secondary", size="lg")
                            ], className="w-100")
                        ], width=4)
                    ]),
                    html.Hr(),
                    html.Div(id="extreme-status", children="Ready for extreme stress test")
                ])
            ], className="shadow-sm")
        ])
    ], className="mb-4"),
    
    # Dashboard grid
    html.Div(
        id="extreme-dashboard-grid",
        children=[],
        style={
            'display': 'grid',
            'grid-template-columns': 'repeat(12, 1fr)',
            'grid-template-rows': 'repeat(12, 60px)',
            'gap': '20px',
            'min-height': '800px',
            'background': 'linear-gradient(135deg, #ff6b6b 0%, #4ecdc4 100%)',
            'padding': '30px',
            'border-radius': '15px',
            'overflow': 'hidden'
        }
    ),
    
    # Footer
    html.Hr(className="mt-4"),
    html.Footer([
        html.P([
            html.I(className="fas fa-fire me-2 text-danger"),
            "🔥 EXTREME ASYNC: Processes 4.5GB+ of data concurrently with real scatter plot rendering. ",
            "Compare with sync version to see massive performance difference!"
        ], className="text-muted small text-center")
    ])
    
], fluid=True, className="py-4")


@callback(
    Output("async-memory-status-card", "children"),
    [Input("extreme-dashboard-grid", "children")],  # Update when dashboard changes
    prevent_initial_call=False
)
def update_memory_status(grid_children):
    """Update memory status display"""
    mem_info = get_memory_info()
    
    # Determine memory pressure level
    if mem_info['system_usage_percent'] > 90:
        alert_color = "danger"
        icon_color = "text-danger"
        status_text = "CRITICAL"
    elif mem_info['system_usage_percent'] > 75:
        alert_color = "warning"
        icon_color = "text-warning"  
        status_text = "HIGH"
    elif mem_info['system_usage_percent'] > 50:
        alert_color = "info"
        icon_color = "text-info"
        status_text = "MODERATE"
    else:
        alert_color = "success"
        icon_color = "text-success"
        status_text = "LOW"
    
    return dbc.Alert([
        html.H6([
            html.I(className=f"fas fa-memory {icon_color} me-2"),
            f"Memory Usage: {status_text} ({mem_info['system_usage_percent']:.1f}%)"
        ], className="alert-heading mb-2"),
        dbc.Row([
            dbc.Col([
                html.Strong("System Memory:"),
                html.Br(),
                f"{mem_info['system_used_gb']:.1f}GB used / {mem_info['system_total_gb']:.1f}GB total",
                html.Br(),
                f"🆓 {mem_info['system_free_gb']:.1f}GB available"
            ], width=6),
            dbc.Col([
                html.Strong("Process Memory:"),
                html.Br(), 
                f"🔥 {mem_info['process_memory_gb']:.2f}GB ({mem_info['process_memory_mb']:.0f}MB)",
                html.Br(),
                f"📈 Active dataframes: {len(loader.results)}"
            ], width=6)
        ])
    ], color=alert_color, className="mb-0")


@callback(
    [Output("extreme-dashboard-grid", "children"),
     Output("extreme-status", "children")],
    [Input("extreme-load-btn", "n_clicks"),
     Input("extreme-clear-btn", "n_clicks"),
     Input("dataset-filter", "value"),
     Input("sample-size-slider", "value")],
    prevent_initial_call=True
)
async def manage_extreme_dashboard(load_clicks, clear_clicks, dataset_filter, sample_range):
    """ASYNC: Load all massive datasets concurrently"""
    
    triggered = ctx.triggered_id
    
    # Handle interactive updates without reloading data
    if triggered in ["dataset-filter", "sample-size-slider"] and loader.results:
        filter_map = {
            'sales': ['sales-analysis'],
            'users': ['user-analytics'], 
            'financial': ['financial-analysis'],
            'performance': ['performance-metrics']
        }
        
        # Re-render existing components with new parameters
        grid_items = []
        for comp_id, config in MASSIVE_COMPONENTS.items():
            if comp_id in loader.results:
                result = loader.results[comp_id]
                if dataset_filter == 'all' or comp_id in filter_map.get(dataset_filter, []):
                    component_card = config['renderer'](result, sample_range)
                    grid_item = html.Div(
                        component_card,
                        style={
                            'grid-column': config['grid']['col'],
                            'grid-row': config['grid']['row']
                        }
                    )
                    grid_items.append(grid_item)
        
        status_msg = dbc.Alert(f"📊 Updated view: {dataset_filter} | Sample: {sample_range[0]}K-{sample_range[1]}K", color="info")
        return grid_items, status_msg
    
    if triggered == "extreme-clear-btn":
        return [], dbc.Alert("Dashboard cleared", color="info")
    
    if triggered == "extreme-load-btn":
        try:
            print("=" * 80)
            print("🔥 STARTING EXTREME ASYNC STRESS TEST")
            print(f"📊 Dataset Filter: {dataset_filter}")
            print(f"📈 Sample Range: {sample_range[0]}K - {sample_range[1]}K records")
            print("=" * 80)
            
            overall_start = time.time()
            
            # Filter components based on interactive controls
            active_components = MASSIVE_COMPONENTS.copy()
            if dataset_filter != 'all':
                filter_map = {
                    'sales': ['sales-analysis'],
                    'users': ['user-analytics'], 
                    'financial': ['financial-analysis'],
                    'performance': ['performance-metrics']
                }
                if dataset_filter in filter_map:
                    active_components = {k: v for k, v in MASSIVE_COMPONENTS.items() 
                                       if k in filter_map[dataset_filter]}
            
            # Create async tasks for filtered components
            component_tasks = []
            component_ids = []
            
            for comp_id, config in active_components.items():
                component_tasks.append(config['loader']())
                component_ids.append(comp_id)
            
            print(f"🚀 Loading {len(component_tasks)} MASSIVE datasets CONCURRENTLY...")
            print("⚠️  This will generate ~4.5GB of data and render real scatter plots!")
            
            # Load ALL massive components concurrently
            results = await asyncio.gather(*component_tasks, return_exceptions=True)
            
            overall_time = time.time() - overall_start
            
            # Render completed components
            grid_items = []
            successful = 0
            total_records = 0
            total_memory_gb = 0
            
            for comp_id, result in zip(component_ids, results):
                config = active_components[comp_id]
                
                if isinstance(result, Exception):
                    # Handle errors
                    component_card = create_error_card(comp_id, str(result))
                    print(f"❌ {comp_id} FAILED: {result}")
                else:
                    # Store results for interactive updates
                    loader.results[comp_id] = result
                    
                    # Render successful component with scatter plot
                    print(f"🎨 Rendering scatter plot for {comp_id}...")
                    component_card = config['renderer'](result, sample_range)
                    successful += 1
                    total_records += result.get('records_processed', 0)
                    total_memory_gb += result.get('data', {}).get('memory_gb', 0)
                
                # Add to grid
                grid_item = html.Div(
                    component_card,
                    style={
                        'grid-column': config['grid']['col'],
                        'grid-row': config['grid']['row']
                    }
                )
                grid_items.append(grid_item)
            
            print("=" * 80)
            print("🎉 EXTREME ASYNC STRESS TEST COMPLETE")
            print(f"⚡ Total Time: {overall_time:.2f}s")
            print(f"📊 Records Processed: {total_records:,}")
            print(f"💾 Total Data Size: {total_memory_gb:.2f}GB")
            print(f"🎯 Components: {successful}/{len(active_components)} successful")
            print(f"📈 Scatter Plots Rendered: {successful}")
            print("=" * 80)
            
            # Create status message with performance metrics
            status_alert = dbc.Alert([
                html.H5([
                    html.I(className="fas fa-rocket me-2"),
                    f"🔥 EXTREME ASYNC: {overall_time:.2f}s total"
                ], className="alert-heading text-success"),
                html.P([
                    f"✅ Processed {total_records:,} records ({total_memory_gb:.2f}GB) with {successful} scatter plots ",
                    html.Strong("concurrently", className="text-success"),
                    f" in {overall_time:.2f} seconds!"
                ]),
                html.Hr(),
                html.P([
                    "🚀 All 4.5GB+ datasets loaded simultaneously - total time ≈ slowest component!"
                ], className="mb-0 small")
            ], color="success")
            
            return grid_items, status_alert
            
        except Exception as e:
            print(f"💥 EXTREME TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            
            error_status = dbc.Alert([
                html.I(className="fas fa-times-circle me-2"),
                f"Failed to load massive datasets: {str(e)}"
            ], color="danger")
            
            return [], error_status
    
    # Default state
    return [], dbc.Alert("Ready for EXTREME async stress test", color="light")


if __name__ == "__main__":
    print("=" * 100)
    print("🔥 EXTREME STRESS TEST - ASYNC VERSION")
    print("=" * 100)
    print("⚠️  WARNING: This is an extreme stress test!")
    print("")
    print("🎯 Test Overview:")
    print("   • 4 massive datasets: 1.2GB + 0.8GB + 1.5GB + 1.0GB = ~4.5GB total")
    print("   • 4.5 million+ total records across all datasets")
    print("   • Real scatter plots with thousands of points each")
    print("   • ASYNC: All datasets load and render CONCURRENTLY")
    print("")
    print("💾 System Requirements:")
    print("   • RAM: 8GB+ recommended (6GB minimum)")
    print("   • CPU: Multi-core processor strongly recommended")
    print("   • Browser: Modern browser with WebGL support")
    print("")
    print("📊 Datasets:")
    print("   • Sales Analysis: 1.2M records × 50 cols (~1.2GB)")
    print("   • User Analytics: 800K records × 40 cols (~0.8GB)")
    print("   • Financial Data: 1.5M records × 55 cols (~1.5GB)")
    print("   • Performance Metrics: 1M records × 45 cols (~1.0GB)")
    print("")
    print("⚡ Expected ASYNC Performance:")
    print("   • Data Generation: ~5-10 seconds concurrent")
    print("   • Plot Rendering: ~5-15 seconds concurrent")
    print("   • Total Time: ~15-25 seconds (vs 45-80s sync)")
    print("   • Memory Peak: ~6-8GB during processing")
    print("")
    print("🔥 This will stress test your entire system!")
    print("=" * 100)
    print(f"🌐 Access EXTREME ASYNC at: http://localhost:8065")
    print("⚖️  Compare with EXTREME SYNC at: http://localhost:8066")
    print("=" * 100)
    
    app.run(debug=True, port=8065)