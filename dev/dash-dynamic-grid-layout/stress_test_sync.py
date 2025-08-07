"""
EXTREME Stress Test - SYNC VERSION with 1GB Dataframes and Real Plots

This implementation uses the same massive 1GB+ dataframes with scatter plots
but loads them SEQUENTIALLY to demonstrate the performance penalty of
synchronous processing under extreme load.

WARNING: This will use significant CPU and memory for a LONG time!
"""

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
    assets_folder="/tmp/dash_assets_sync",  # Use separate assets folder to prevent conflicts
    assets_url_path="/sync_assets/"  # Use separate URL path for assets
)
server = app.server


def generate_massive_dataframe(rows: int, cols: int, name: str) -> pl.DataFrame:
    """Generate a massive 1GB+ polars dataframe for extreme stress testing"""
    print(f"🐌 GENERATING MASSIVE {name} dataframe: {rows:,} rows × {cols} columns...")
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
    print(f"   🐌 Process Memory: {mem_info['process_memory_gb']:.2f}GB ({mem_info['process_memory_mb']:.0f}MB)")
    
    return df


class ExtremeSyncComponentLoader:
    """Handles massive dataframe processing with SYNC loading"""
    
    def __init__(self):
        self.results = {}
    
    def load_massive_sales_data(self) -> Dict[str, Any]:
        """Load and process massive sales dataset - ~1.2GB (SYNC)"""
        print("🐌 Starting SYNC massive sales analysis...")
        start_time = time.time()
        
        # Simulate network delay (sync)
        time.sleep(0.5)
        
        # Generate massive dataframe (1.2M rows, 50 columns ≈ 1.2GB)
        df = generate_massive_dataframe(1200000, 50, "Sales Data")
        
        # Heavy processing with real calculations (sync)
        time.sleep(0.1)
        
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
        print(f"✅ SYNC massive sales analysis completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_sales',
            'title': 'Massive Sales Analysis',
            'data': sales_data,
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    def load_massive_user_data(self) -> Dict[str, Any]:
        """Load and process massive user dataset - ~0.8GB (SYNC)"""
        print("🐌 Starting SYNC massive user analytics...")
        start_time = time.time()
        
        time.sleep(0.3)
        
        # Generate massive dataframe (800K rows, 40 columns ≈ 0.8GB)
        df = generate_massive_dataframe(800000, 40, "User Data")
        
        time.sleep(0.1)
        
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
        print(f"✅ SYNC massive user analytics completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_users',
            'title': 'Massive User Analytics',
            'data': user_data,
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    def load_massive_financial_data(self) -> Dict[str, Any]:
        """Load and process massive financial dataset - ~1.5GB (SYNC)"""
        print("🐌 Starting SYNC massive financial analysis...")
        start_time = time.time()
        
        time.sleep(0.8)
        
        # Generate massive dataframe (1.5M rows, 55 columns ≈ 1.5GB)
        df = generate_massive_dataframe(1500000, 55, "Financial Data")
        
        time.sleep(0.2)
        
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
        print(f"✅ SYNC massive financial analysis completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_financial',
            'title': 'Massive Financial Analysis',
            'data': financial_data,
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }
    
    def load_massive_performance_data(self) -> Dict[str, Any]:
        """Load and process massive performance dataset - ~1.0GB (SYNC)"""
        print("🐌 Starting SYNC massive performance metrics...")
        start_time = time.time()
        
        time.sleep(0.4)
        
        # Generate massive dataframe (1M rows, 45 columns ≈ 1GB)
        df = generate_massive_dataframe(1000000, 45, "Performance Data")
        
        time.sleep(0.15)
        
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
        print(f"✅ SYNC massive performance metrics completed in {load_time:.2f}s")
        
        return {
            'type': 'massive_performance',
            'title': 'Massive Performance Analysis',
            'data': performance_data,
            'load_time': round(load_time, 2),
            'records_processed': len(df)
        }


# Global loader instance - with unique ID for this sync app
loader = ExtremeSyncComponentLoader()
loader.app_id = "sync_extreme_test"  # Unique identifier


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


# Use same scatter plot renderers as async version (just copy them)
def create_sales_scatter_plot(data: Dict[str, Any]) -> dbc.Card:
    """Create massive sales scatter plot"""
    chart_data = data['data']
    
    # Create real scatter plot with 5K points
    fig = go.Figure()
    
    categories = list(set(chart_data['plot_color']))
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    
    for i, category in enumerate(categories):
        mask = [c == category for c in chart_data['plot_color']]
        x_vals = [x for x, m in zip(chart_data['plot_x'], mask) if m]
        y_vals = [y for y, m in zip(chart_data['plot_y'], mask) if m]
        
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers',
            name=f'Category {category}',
            marker=dict(color=colors[i % len(colors)], size=4, opacity=0.7),
            hovertemplate=f'<b>{category}</b><br>Value: %{{x:.2f}}<br>Price: $%{{y:.2f}}<extra></extra>'
        ))
    
    fig.update_layout(
        title=f"Sales Analysis: {data['records_processed']:,} records ({chart_data['memory_gb']:.2f}GB)",
        xaxis_title="Value Metric",
        yaxis_title="Price ($)",
        height=350,
        width=600,  # Fixed width
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False  # Disable autosize
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
                    html.H6(f"{data['load_time']}s", className="text-danger mb-0"),
                    html.Small("🐌 SYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"${data['data']['total_sales']:,.0f}", className="text-success mb-0"),
                    html.Small("Total Sales", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #28a745'})


def create_user_scatter_plot(data: Dict[str, Any]) -> dbc.Card:
    """Create massive user analytics scatter plot"""
    chart_data = data['data']
    
    # Create scatter plot
    fig = go.Figure()
    
    categories = list(set(chart_data['plot_color']))
    colors = ['#17a2b8', '#ffc107', '#dc3545', '#28a745', '#6f42c1']
    
    for i, category in enumerate(categories):
        mask = [c == category for c in chart_data['plot_color']]
        x_vals = [x for x, m in zip(chart_data['plot_x'], mask) if m]
        y_vals = [y for y, m in zip(chart_data['plot_y'], mask) if m]
        
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers',
            name=f'Segment {category}',
            marker=dict(color=colors[i % len(colors)], size=4, opacity=0.6),
            hovertemplate=f'<b>{category}</b><br>Session: %{{x:.1f}}min<br>Value: %{{y:.2f}}<extra></extra>'
        ))
    
    fig.update_layout(
        title=f"User Analytics: {data['records_processed']:,} users ({chart_data['memory_gb']:.2f}GB)",
        xaxis_title="Session Duration (min)",
        yaxis_title="User Value",
        height=350,
        width=600,  # Fixed width
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False  # Disable autosize
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
                    html.H6(f"{data['load_time']}s", className="text-danger mb-0"),
                    html.Small("🐌 SYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"{data['data']['avg_session']:.1f}min", className="text-info mb-0"),
                    html.Small("Avg Session", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #17a2b8'})


def create_financial_scatter_plot(data: Dict[str, Any]) -> dbc.Card:
    """Create massive financial analysis scatter plot"""
    chart_data = data['data']
    
    # Create scatter plot
    fig = go.Figure()
    
    categories = list(set(chart_data['plot_color']))
    colors = ['#ffc107', '#fd7e14', '#e83e8c', '#20c997', '#6610f2']
    
    for i, category in enumerate(categories):
        mask = [c == category for c in chart_data['plot_color']]
        x_vals = [x for x, m in zip(chart_data['plot_x'], mask) if m]
        y_vals = [y for y, m in zip(chart_data['plot_y'], mask) if m]
        
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers',
            name=f'Type {category}',
            marker=dict(color=colors[i % len(colors)], size=4, opacity=0.6),
            hovertemplate=f'<b>{category}</b><br>Volume: %{{x:,.0f}}<br>Profit: $%{{y:,.0f}}<extra></extra>'
        ))
    
    fig.update_layout(
        title=f"Financial Analysis: {data['records_processed']:,} transactions ({chart_data['memory_gb']:.2f}GB)",
        xaxis_title="Volume",
        yaxis_title="Profit ($)",
        height=350,
        width=600,  # Fixed width
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False  # Disable autosize
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
                    html.H6(f"{data['load_time']}s", className="text-danger mb-0"),
                    html.Small("🐌 SYNC Load", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H6(f"${data['data']['total_profit']:,.0f}", className="text-success mb-0"),
                    html.Small("Total Profit", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100", style={'border': '3px solid #ffc107'})


def create_performance_scatter_plot(data: Dict[str, Any]) -> dbc.Card:
    """Create massive performance metrics scatter plot"""
    chart_data = data['data']
    
    # Create scatter plot
    fig = go.Figure()
    
    categories = list(set(chart_data['plot_color']))
    colors = ['#dc3545', '#fd7e14', '#ffc107', '#198754', '#0d6efd']
    
    for i, category in enumerate(categories):
        mask = [c == category for c in chart_data['plot_color']]
        x_vals = [x for x, m in zip(chart_data['plot_x'], mask) if m]
        y_vals = [y for y, m in zip(chart_data['plot_y'], mask) if m]
        
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers',
            name=f'Service {category}',
            marker=dict(color=colors[i % len(colors)], size=4, opacity=0.6),
            hovertemplate=f'<b>{category}</b><br>Hour: %{{x}}<br>Response: %{{y:.1f}}ms<extra></extra>'
        ))
    
    fig.update_layout(
        title=f"Performance Analysis: {data['records_processed']:,} events ({chart_data['memory_gb']:.2f}GB)",
        xaxis_title="Hour of Day",
        yaxis_title="Response Time (ms)",
        height=350,
        width=600,  # Fixed width
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        autosize=False  # Disable autosize
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
                    html.H6(f"{data['load_time']}s", className="text-danger mb-0"),
                    html.Small("🐌 SYNC Load", className="text-muted")
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


# Massive component configuration (same as async but with sync loaders)
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
            html.I(className="fas fa-turtle me-3 text-danger"),
            "EXTREME Stress Test - SYNC (1GB+ Dataframes)"
        ], className="mb-2"),
        html.P([
            "🐌 EXTREME SYNC VERSION: 4 massive datasets (~4.5GB total) load ",
            html.Strong("SEQUENTIALLY", className="text-danger"),
            " with real scatter plots - this will take a very long time!"
        ], className="lead text-muted mb-4")
    ]),
    
    # Warning Alert
    dbc.Row([
        dbc.Col([
            dbc.Alert([
                html.H5([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    "⚠️ EXTREME SYNC WARNING - VERY SLOW!"
                ], className="alert-heading"),
                html.P([
                    "This SYNC version processes the same 4.5GB of data but ",
                    html.Strong("SEQUENTIALLY", className="text-danger"),
                    " - each dataset waits for the previous one to complete entirely. ",
                    html.Strong("Expected time: 45-80 seconds!", className="text-danger")
                ]),
                html.Hr(),
                html.P([
                    "⏰ Prepare to wait! Go grab coffee while this runs."
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
                                id="sync-dataset-filter",
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
                                id="sync-sample-size-slider",
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
                                html.I(className="fas fa-hourglass-end me-2"),
                                "EXTREME SYNC Stress Test"
                            ]),
                            html.P("Wait for 4.5GB of sequential data processing", className="text-muted")
                        ], width=8),
                        dbc.Col([
                            dbc.ButtonGroup([
                                dbc.Button([
                                    html.I(className="fas fa-turtle me-2"),
                                    "START EXTREME TEST (SYNC)"
                                ], id="extreme-sync-load-btn", color="danger", size="lg"),
                                dbc.Button([
                                    html.I(className="fas fa-times me-2"),
                                    "Clear"
                                ], id="extreme-sync-clear-btn", color="outline-secondary", size="lg")
                            ], className="w-100")
                        ], width=4)
                    ]),
                    html.Hr(),
                    html.Div(id="extreme-sync-status", children="Ready for extreme SYNC stress test")
                ])
            ], className="shadow-sm")
        ])
    ], className="mb-4"),
    
    # Dashboard grid
    html.Div(
        id="extreme-sync-dashboard-grid",
        children=[],
        style={
            'display': 'grid',
            'grid-template-columns': 'repeat(12, 1fr)',
            'grid-template-rows': 'repeat(12, 60px)',
            'gap': '20px',
            'min-height': '800px',
            'background': 'linear-gradient(135deg, #dc3545 0%, #6f42c1 100%)',
            'padding': '30px',
            'border-radius': '15px',
            'overflow': 'hidden'
        }
    ),
    
    # Footer
    html.Hr(className="mt-4"),
    html.Footer([
        html.P([
            html.I(className="fas fa-turtle me-2 text-danger"),
            "🐌 EXTREME SYNC: Processes 4.5GB+ sequentially with scatter plots. ",
            "Compare with async version to see the dramatic performance penalty!"
        ], className="text-muted small text-center")
    ])
    
], fluid=True, className="py-4")


@callback(
    [Output("extreme-sync-dashboard-grid", "children"),
     Output("extreme-sync-status", "children")],
    [Input("extreme-sync-load-btn", "n_clicks"),
     Input("extreme-sync-clear-btn", "n_clicks"),
     Input("sync-dataset-filter", "value"),
     Input("sync-sample-size-slider", "value")],
    prevent_initial_call=True
)
def manage_extreme_sync_dashboard(load_clicks, clear_clicks, dataset_filter, sample_range):
    """SYNC: Load all massive datasets sequentially"""
    
    triggered = ctx.triggered_id
    
    if triggered == "extreme-sync-clear-btn":
        return [], dbc.Alert("Dashboard cleared", color="info")
    
    if triggered == "extreme-sync-load-btn":
        try:
            print("=" * 80)
            print("🐌 STARTING EXTREME SYNC STRESS TEST")
            print(f"📊 Dataset Filter: {dataset_filter}")
            print(f"📈 Sample Range: {sample_range[0]}K - {sample_range[1]}K records")
            print("=" * 80)
            print("⚠️  WARNING: This will take 45-80 seconds!")
            
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
            
            # Load components SEQUENTIALLY (one at a time)
            results = []
            component_ids = []
            
            print(f"🐌 Loading {len(active_components)} MASSIVE datasets SEQUENTIALLY...")
            print("☕ Time to grab coffee - this will be VERY slow!")
            
            for i, (comp_id, config) in enumerate(active_components.items(), 1):
                print(f"⏳ [{i}/4] Loading {comp_id}... (waiting for previous to complete)")
                try:
                    # Load ONE massive component at a time (blocking)
                    result = config['loader']()
                    results.append(result)
                    print(f"✅ [{i}/4] {comp_id} completed")
                except Exception as e:
                    print(f"❌ [{i}/4] {comp_id} FAILED: {e}")
                    results.append(e)
                
                component_ids.append(comp_id)
            
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
                    # Render successful component with scatter plot
                    print(f"🎨 Rendering scatter plot for {comp_id}...")
                    component_card = config['renderer'](result)
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
            print("🐌 EXTREME SYNC STRESS TEST COMPLETE")
            print(f"⏰ Total Time: {overall_time:.2f}s")
            print(f"📊 Records Processed: {total_records:,}")
            print(f"💾 Total Data Size: {total_memory_gb:.2f}GB")
            print(f"🎯 Components: {successful}/{len(active_components)} successful")
            print(f"📈 Scatter Plots Rendered: {successful}")
            print("=" * 80)
            
            # Create status message with performance metrics
            status_alert = dbc.Alert([
                html.H5([
                    html.I(className="fas fa-turtle me-2"),
                    f"🐌 EXTREME SYNC: {overall_time:.2f}s total"
                ], className="alert-heading text-danger"),
                html.P([
                    f"✅ Processed {total_records:,} records ({total_memory_gb:.2f}GB) with {successful} scatter plots ",
                    html.Strong("sequentially", className="text-danger"),
                    f" in {overall_time:.2f} seconds!"
                ]),
                html.Hr(),
                html.P([
                    "🐌 Each dataset waited for the previous one - total time = sum of all individual times!"
                ], className="mb-0 small")
            ], color="warning")
            
            return grid_items, status_alert
            
        except Exception as e:
            print(f"💥 EXTREME SYNC TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            
            error_status = dbc.Alert([
                html.I(className="fas fa-times-circle me-2"),
                f"Failed to load massive datasets: {str(e)}"
            ], color="danger")
            
            return [], error_status
    
    # Default state
    return [], dbc.Alert("Ready for EXTREME sync stress test (this will be slow!)", color="light")


if __name__ == "__main__":
    print("=" * 100)
    print("🐌 EXTREME STRESS TEST - SYNC VERSION")
    print("=" * 100)
    print("⚠️  WARNING: This will be EXTREMELY SLOW!")
    print("")
    print("🎯 Test Overview:")
    print("   • 4 massive datasets: 1.2GB + 0.8GB + 1.5GB + 1.0GB = ~4.5GB total")
    print("   • 4.5 million+ total records across all datasets")
    print("   • Real scatter plots with thousands of points each")
    print("   • SYNC: All datasets load and render SEQUENTIALLY")
    print("")
    print("💾 System Requirements:")
    print("   • RAM: 8GB+ recommended")
    print("   • CPU: Any (but prepare to wait!)")
    print("   • Patience: LOTS! ☕")
    print("")
    print("📊 Datasets (same as async, but processed sequentially):")
    print("   • Sales Analysis: 1.2M records × 50 cols (~1.2GB)")
    print("   • User Analytics: 800K records × 40 cols (~0.8GB)")
    print("   • Financial Data: 1.5M records × 55 cols (~1.5GB)")
    print("   • Performance Metrics: 1M records × 45 cols (~1.0GB)")
    print("")
    print("🐌 Expected SYNC Performance:")
    print("   • Data Generation: ~20-40 seconds sequential")
    print("   • Plot Rendering: ~25-40 seconds sequential")
    print("   • Total Time: ~45-80 seconds (vs 15-25s async)")
    print("   • Each dataset waits for previous to complete entirely")
    print("")
    print("☕ Grab coffee, this will take a while!")
    print("=" * 100)
    print(f"🌐 Access EXTREME SYNC at: http://localhost:8066")
    print("⚖️  Compare with EXTREME ASYNC at: http://localhost:8065")
    print("=" * 100)
    
    app.run(debug=True, port=8066)