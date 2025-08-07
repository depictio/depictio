"""
Working Async Grid Layout - Simplified and Functional

This is a working implementation of async component loading with a grid layout.
Fixes all the issues from previous versions.
"""

import asyncio
import time
import random
from datetime import datetime
from typing import List, Dict, Any

from dash import Dash, html, dcc, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd


# Initialize Dash app
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server


class AsyncComponentLoader:
    """Handles async loading of dashboard components"""
    
    def __init__(self):
        self.results = {}
    
    async def load_sales_data(self) -> Dict[str, Any]:
        """Load sales chart data"""
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)
        
        if random.random() < 0.1:
            raise Exception("Sales API failed")
        
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        sales = [random.randint(1000, 5000) for _ in range(30)]
        
        return {
            'type': 'sales_chart',
            'title': 'Daily Sales',
            'data': {'dates': [d.strftime('%m-%d') for d in dates], 'sales': sales},
            'load_time': round(delay, 2)
        }
    
    async def load_user_data(self) -> Dict[str, Any]:
        """Load user metrics data"""
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)
        
        if random.random() < 0.1:
            raise Exception("User API failed")
        
        return {
            'type': 'user_metrics',
            'title': 'User Metrics',
            'data': {
                'total': random.randint(10000, 50000),
                'active': random.randint(5000, 15000),
                'new': random.randint(100, 1000)
            },
            'load_time': round(delay, 2)
        }
    
    async def load_revenue_data(self) -> Dict[str, Any]:
        """Load revenue pie chart data"""
        delay = random.uniform(1.5, 2.5)
        await asyncio.sleep(delay)
        
        if random.random() < 0.1:
            raise Exception("Revenue API failed")
        
        return {
            'type': 'revenue_pie',
            'title': 'Revenue Sources',
            'data': {
                'labels': ['Products', 'Services', 'Subscriptions', 'Other'],
                'values': [random.randint(10000, 50000) for _ in range(4)]
            },
            'load_time': round(delay, 2)
        }
    
    async def load_alerts_data(self) -> Dict[str, Any]:
        """Load system alerts data"""
        delay = random.uniform(0.3, 1.0)
        await asyncio.sleep(delay)
        
        return {
            'type': 'alerts',
            'title': 'System Alerts',
            'data': {
                'critical': random.randint(0, 3),
                'warning': random.randint(2, 8),
                'info': random.randint(5, 15)
            },
            'load_time': round(delay, 2)
        }


# Global loader instance
loader = AsyncComponentLoader()


def create_loading_card(comp_id: str, title: str) -> dbc.Card:
    """Create a loading placeholder card"""
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                dbc.Spinner(size="lg", color="primary"),
                html.H5(f"Loading {title}...", className="mt-3 text-muted"),
                html.P(f"ID: {comp_id}", className="text-muted small")
            ], className="text-center p-4")
        ])
    ], className="h-100 border-dashed")


def create_sales_chart(data: Dict[str, Any]) -> dbc.Card:
    """Create sales chart component"""
    chart_data = data['data']
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=chart_data['dates'],
        y=chart_data['sales'],
        mode='lines+markers',
        line=dict(color='#28a745', width=2),
        name='Sales'
    ))
    fig.update_layout(
        title=f"{data['title']} (loaded in {data['load_time']}s)",
        height=300,
        margin=dict(l=40, r=40, t=60, b=40)
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-chart-line text-success me-2"),
            "Sales Performance"
        ]),
        dbc.CardBody([
            dcc.Graph(figure=fig, config={'displayModeBar': False})
        ])
    ], className="h-100")


def create_user_metrics(data: Dict[str, Any]) -> dbc.Card:
    """Create user metrics component"""
    metrics = data['data']
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-users text-info me-2"),
            f"Users (loaded in {data['load_time']}s)"
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H3(f"{metrics['total']:,}", className="text-primary"),
                    html.P("Total Users", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H3(f"{metrics['active']:,}", className="text-success"),
                    html.P("Active", className="text-muted")
                ], width=4),
                dbc.Col([
                    html.H3(f"{metrics['new']:,}", className="text-warning"),
                    html.P("New", className="text-muted")
                ], width=4)
            ])
        ])
    ], className="h-100")


def create_revenue_pie(data: Dict[str, Any]) -> dbc.Card:
    """Create revenue pie chart component"""
    chart_data = data['data']
    
    fig = go.Figure(data=[go.Pie(
        labels=chart_data['labels'],
        values=chart_data['values'],
        hole=0.3
    )])
    fig.update_layout(
        title=f"{data['title']} (loaded in {data['load_time']}s)",
        height=250,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-chart-pie text-warning me-2"),
            "Revenue Breakdown"
        ]),
        dbc.CardBody([
            dcc.Graph(figure=fig, config={'displayModeBar': False})
        ])
    ], className="h-100")


def create_alerts_panel(data: Dict[str, Any]) -> dbc.Card:
    """Create alerts panel component"""
    alerts = data['data']
    
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-bell text-danger me-2"),
            f"Alerts (loaded in {data['load_time']}s)"
        ]),
        dbc.CardBody([
            dbc.ListGroup([
                dbc.ListGroupItem([
                    html.I(className="fas fa-exclamation-circle text-danger me-2"),
                    "Critical",
                    dbc.Badge(alerts['critical'], color="danger", pill=True, className="ms-auto")
                ], className="d-flex align-items-center"),
                dbc.ListGroupItem([
                    html.I(className="fas fa-exclamation-triangle text-warning me-2"),
                    "Warning", 
                    dbc.Badge(alerts['warning'], color="warning", pill=True, className="ms-auto")
                ], className="d-flex align-items-center"),
                dbc.ListGroupItem([
                    html.I(className="fas fa-info-circle text-info me-2"),
                    "Info",
                    dbc.Badge(alerts['info'], color="info", pill=True, className="ms-auto")
                ], className="d-flex align-items-center")
            ], flush=True)
        ])
    ], className="h-100")


def create_error_card(comp_id: str, error_msg: str) -> dbc.Card:
    """Create error display card"""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-exclamation-triangle text-danger me-2"),
            f"Error: {comp_id}"
        ]),
        dbc.CardBody([
            dbc.Alert([
                html.H6("Component Failed to Load"),
                html.P(error_msg),
                dbc.Button("Retry", color="outline-danger", size="sm")
            ], color="danger")
        ])
    ], className="h-100")


# Component configuration
COMPONENTS = {
    'sales-chart': {
        'loader': loader.load_sales_data,
        'renderer': create_sales_chart,
        'title': 'Sales Chart',
        'grid': {'col': 'span 6', 'row': 'span 4'}
    },
    'user-metrics': {
        'loader': loader.load_user_data,
        'renderer': create_user_metrics,
        'title': 'User Metrics',
        'grid': {'col': 'span 3', 'row': 'span 2'}
    },
    'revenue-pie': {
        'loader': loader.load_revenue_data,
        'renderer': create_revenue_pie,
        'title': 'Revenue Chart',
        'grid': {'col': 'span 3', 'row': 'span 2'}
    },
    'alerts-panel': {
        'loader': loader.load_alerts_data,
        'renderer': create_alerts_panel,
        'title': 'System Alerts',
        'grid': {'col': 'span 6', 'row': 'span 2'}
    }
}


# App layout
app.layout = dbc.Container([
    html.H1("Working Async Grid Dashboard", className="mb-4"),
    
    # Control panel
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("Control Panel"),
                    html.P("Click 'Load Dashboard' to see async component loading in action."),
                    dbc.ButtonGroup([
                        dbc.Button([
                            html.I(className="fas fa-play me-2"),
                            "Load Dashboard"
                        ], id="load-btn", color="primary", size="lg"),
                        dbc.Button([
                            html.I(className="fas fa-times me-2"),
                            "Clear Dashboard"
                        ], id="clear-btn", color="outline-secondary", size="lg")
                    ]),
                    html.Hr(),
                    html.H6("Status:"),
                    html.Div(id="status-display", children="Ready to load")
                ])
            ])
        ])
    ], className="mb-4"),
    
    # Dashboard grid
    html.Div(
        id="dashboard-grid",
        children=[],
        style={
            'display': 'grid',
            'grid-template-columns': 'repeat(12, 1fr)',
            'grid-auto-rows': '100px',
            'gap': '15px',
            'min-height': '600px',
            'background': '#f8f9fa',
            'padding': '20px',
            'border-radius': '8px'
        }
    ),
    
    # No longer need interval or state store - pure async callbacks!
    
], fluid=True)


@callback(
    [Output("dashboard-grid", "children"),
     Output("status-display", "children")],
    [Input("load-btn", "n_clicks"),
     Input("clear-btn", "n_clicks")],
    prevent_initial_call=True
)
async def manage_dashboard(load_clicks, clear_clicks):
    """Pure async dashboard management - follows your example pattern"""
    
    triggered = ctx.triggered_id
    
    if triggered == "clear-btn":
        return [], dbc.Alert("Dashboard cleared", color="info")
    
    if triggered == "load-btn":
        try:
            start_time = time.time()
            
            # Create async tasks for all components (like your example)
            component_tasks = []
            component_ids = []
            
            for comp_id, config in COMPONENTS.items():
                component_tasks.append(config['loader']())
                component_ids.append(comp_id)
            
            # Load all components concurrently (like asyncio.gather in your example)
            results = await asyncio.gather(*component_tasks, return_exceptions=True)
            
            # Render completed components
            grid_items = []
            successful = 0
            errors = 0
            
            for comp_id, result in zip(component_ids, results):
                config = COMPONENTS[comp_id]
                
                if isinstance(result, Exception):
                    # Handle errors
                    component_card = create_error_card(comp_id, str(result))
                    errors += 1
                else:
                    # Render successful component  
                    component_card = config['renderer'](result)
                    successful += 1
                
                # Add to grid
                grid_item = html.Div(
                    component_card,
                    style={
                        'grid-column': config['grid']['col'],
                        'grid-row': config['grid']['row']
                    }
                )
                grid_items.append(grid_item)
            
            # Create status message
            total_time = round(time.time() - start_time, 2)
            
            if errors == 0:
                status_alert = dbc.Alert([
                    html.I(className="fas fa-check-circle me-2"),
                    f"✅ All {successful} components loaded in {total_time}s!"
                ], color="success")
            else:
                status_alert = dbc.Alert([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    f"⚠️ Loaded in {total_time}s: {successful} successful, {errors} failed"
                ], color="warning")
            
            return grid_items, status_alert
            
        except Exception as e:
            error_status = dbc.Alert([
                html.I(className="fas fa-times-circle me-2"),
                f"Failed to load dashboard: {str(e)}"
            ], color="danger")
            
            return [], error_status
    
    # Default state
    return [], dbc.Alert("Ready to load dashboard", color="light")


# Removed old threading-based functions - now using pure async callbacks


if __name__ == "__main__":
    print("🚀 Starting Working Async Grid Dashboard...")
    print("✅ Now using native async def callbacks - just like your example:")
    print("   • async def callbacks with asyncio.gather()")
    print("   • No threading workarounds needed")
    print("   • All components load concurrently")
    print("   • Clean CSS Grid layout")
    print("   • Comprehensive error handling")
    print(f"🌐 Dashboard available at: http://localhost:8056")
    
    app.run(debug=True, port=8056)