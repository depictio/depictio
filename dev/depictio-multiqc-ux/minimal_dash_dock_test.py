#!/usr/bin/env python3
"""
Minimal dash-dock prototype with MultiQC HTML serving
Single tab, single iframe, focused on getting the basic functionality working
"""

from pathlib import Path

import dash_dock
import dash_mantine_components as dmc
from flask import Flask, abort, send_from_directory

import dash
from dash import Input, Output, callback, dcc, html, clientside_callback, ClientsideFunction

# Initialize Flask server for serving external HTML files
server = Flask(__name__)

# Flask route to serve external HTML files
@server.route('/external/<path:filename>')
def serve_external_html(filename):
    """Serve HTML files from external locations"""
    external_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData"
    
    print(f"📁 Serving: {filename}")
    print(f"📂 From: {external_path}")
    
    file_path = Path(external_path) / filename
    print(f"🔍 Full path: {file_path}")
    print(f"✅ Exists: {file_path.exists()}")
    
    if not file_path.exists() or file_path.suffix.lower() != '.html':
        print(f"❌ File not found or not HTML: {file_path}")
        abort(404)
    
    return send_from_directory(external_path, filename)

# Test route
@server.route('/test')
def test_route():
    return "<h1>Flask is working!</h1><p>Server is running correctly.</p>"

# Initialize Dash app with Flask server
app = dash.Dash(__name__, server=server)

# Define dock configuration - minimal single tab
dock_config = {
    "global": {
        "tabEnableClose": False,
        "tabEnableFloat": True
    },
    "layout": {
        "type": "row", 
        "children": [
            {
                "type": "tabset",
                "children": [
                    {
                        "type": "tab",
                        "name": "MultiQC Report",
                        "component": "text",
                        "id": "multiqc-tab",
                        "enableFloat": True
                    }
                ]
            }
        ]
    }
}

# Create tab content
tab_components = [
    dash_dock.Tab(
        id="multiqc-tab",
        children=[
            html.Div([
                html.H4("MultiQC Report Viewer", 
                       style={'margin': '10px', 'color': '#333', 'textAlign': 'center'}),
                html.Div([
                    html.A("🔗 Test Flask Route", href="/test", target="_blank", 
                           style={'marginRight': '20px', 'color': 'blue'}),
                    html.A("📊 Direct MultiQC Link", 
                           href="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html", 
                           target="_blank", style={'color': 'green'})
                ], style={'textAlign': 'center', 'margin': '10px'}),
                html.Hr(),
                html.Iframe(
                    id="multiqc-iframe",
                    src="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
                    style={
                        'width': '100%',
                        'height': 'calc(100vh - 200px)', 
                        'border': '2px solid #ddd',
                        'borderRadius': '8px'
                    }
                )
            ], style={
                'height': '100%', 
                'padding': '15px',
                'backgroundColor': '#f9f9f9'
            })
        ]
    )
]

# App layout
app.layout = dmc.MantineProvider(
    theme={"colorScheme": "light"},
    children=[
    html.Div([
        html.H1("🧪 Minimal Dash-Dock + MultiQC Test", 
               style={'textAlign': 'center', 'margin': '20px', 'color': '#2c3e50'}),
        
        html.Div([
            "✅ Flask serving external HTML files",
            html.Br(),
            "✅ Single dash-dock tab with iframe", 
            html.Br(),
            "✅ Tab floating enabled (tabEnableFloat: True)",
        ], style={
            'backgroundColor': '#e8f5e8', 
            'padding': '15px', 
            'margin': '20px',
            'borderRadius': '8px',
            'border': '1px solid #4CAF50'
        }),
        
        # MultiQC Investigation Panel
        html.Div([
            html.H4("🔍 MultiQC Toolbox Investigation"),
            html.Div([
                dmc.Button("Inspect Highlight Input", id="inspect-highlight-btn", variant="outline", size="sm", style={'margin': '5px'}),
                dmc.Button("Test Sample Input (00050101)", id="test-sample-input-btn", variant="outline", size="sm", style={'margin': '5px'}),
                dmc.Button("Simulate Enter Key", id="simulate-enter-btn", variant="outline", size="sm", style={'margin': '5px'}),
                dmc.Button("Simulate + Click", id="simulate-plus-btn", variant="outline", size="sm", style={'margin': '5px'}),
            ]),
            html.Pre(id="investigation-output", style={
                'backgroundColor': '#f8f9fa', 
                'padding': '10px', 
                'margin': '10px 0',
                'borderRadius': '4px',
                'border': '1px solid #ddd',
                'fontSize': '12px',
                'maxHeight': '300px',
                'overflow': 'auto',
                'whiteSpace': 'pre-wrap'
            })
        ], style={
            'backgroundColor': '#fff3cd', 
            'padding': '15px', 
            'margin': '20px',
            'borderRadius': '8px',
            'border': '1px solid #ffc107'
        }),
        
        # Dock container
        html.Div([
            dash_dock.DashDock(
                id='minimal-dock',
                model=dock_config,
                children=tab_components,
                useStateForModel=True,
                style={
                    'position': 'relative',
                    'height': '100%',
                    'width': '100%',
                    'overflow': 'hidden'
                }
            )
        ], style={
            'height': '70vh',
            'width': '95%',
            'margin': '20px auto',
            'border': '3px solid #3498db',
            'borderRadius': '10px',
            'backgroundColor': 'white'
        }, id='dock-container'),
        
        # Hidden components for clientside functionality
        dcc.Interval(id='inject-fullscreen-btn', interval=300, n_intervals=0, max_intervals=1),
        html.Div(id='fullscreen-trigger', style={'display': 'none'})
    ], style={'minHeight': '100vh', 'backgroundColor': '#ecf0f1'})
    ]
)

# Clientside callback to inject fullscreen button into dash-dock toolbar
clientside_callback(
    """
    function(n_intervals) {
        if (n_intervals === 0) return '';
        
        // Wait for dash-dock to render
        setTimeout(function() {
            const toolbar = document.querySelector('.flexlayout__tab_toolbar');
            if (toolbar && !document.getElementById('custom-fullscreen-btn')) {
                // Create fullscreen button with same styling as popout button
                const fullscreenBtn = document.createElement('button');
                fullscreenBtn.id = 'custom-fullscreen-btn';
                fullscreenBtn.className = 'flexlayout__tab_toolbar_button flexlayout__tab_toolbar_button-fullscreen';
                fullscreenBtn.title = 'Expand to full browser window';
                // Remove any custom spacing - let it align naturally
                
                // Create simple expand icon - much cleaner
                fullscreenBtn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                        <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                    </svg>
                `;
                
                // Add click handler for viewport expand toggle
                let isExpanded = false;
                let originalStyles = {};
                
                fullscreenBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const container = document.getElementById('dock-container');
                    const body = document.body;
                    
                    if (!isExpanded) {
                        // Store original styles
                        originalStyles = {
                            position: container.style.position || '',
                            top: container.style.top || '',
                            left: container.style.left || '',
                            width: container.style.width || '',
                            height: container.style.height || '',
                            zIndex: container.style.zIndex || '',
                            margin: container.style.margin || '',
                            border: container.style.border || '',
                            borderRadius: container.style.borderRadius || '',
                            bodyOverflow: body.style.overflow || ''
                        };
                        
                        // Expand to full viewport
                        container.style.position = 'fixed';
                        container.style.top = '0';
                        container.style.left = '0';
                        container.style.width = '100vw';
                        container.style.height = '100vh';
                        container.style.zIndex = '9999';
                        container.style.margin = '0';
                        container.style.border = 'none';
                        container.style.borderRadius = '0';
                        body.style.overflow = 'hidden'; // Prevent scrollbars
                        
                        isExpanded = true;
                        fullscreenBtn.title = 'Restore to normal size';
                        
                        // Keep the same clean icon for both states
                        fullscreenBtn.innerHTML = `
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                                <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                            </svg>
                        `;
                    } else {
                        // Restore original styles
                        container.style.position = originalStyles.position;
                        container.style.top = originalStyles.top;
                        container.style.left = originalStyles.left;
                        container.style.width = originalStyles.width;
                        container.style.height = originalStyles.height;
                        container.style.zIndex = originalStyles.zIndex;
                        container.style.margin = originalStyles.margin;
                        container.style.border = originalStyles.border;
                        container.style.borderRadius = originalStyles.borderRadius;
                        body.style.overflow = originalStyles.bodyOverflow;
                        
                        isExpanded = false;
                        fullscreenBtn.title = 'Expand to full browser window';
                        
                        // Change icon back to expand - simple and clean
                        fullscreenBtn.innerHTML = `
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                                <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                            </svg>
                        `;
                    }
                });
                
                // Insert the fullscreen button before the popout button
                const popoutBtn = toolbar.querySelector('.flexlayout__tab_toolbar_button-float');
                if (popoutBtn) {
                    toolbar.insertBefore(fullscreenBtn, popoutBtn);
                } else {
                    toolbar.appendChild(fullscreenBtn);
                }
                
                console.log('✅ Fullscreen button injected into dash-dock toolbar');
            }
        }, 200);
        
        return 'Fullscreen button injected';
    }
    """,
    Output('fullscreen-trigger', 'children'),
    Input('inject-fullscreen-btn', 'n_intervals')
)

# ESC key handler to restore from expanded view
clientside_callback(
    """
    function() {
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                const fullscreenBtn = document.getElementById('custom-fullscreen-btn');
                if (fullscreenBtn && fullscreenBtn.title === 'Restore to normal size') {
                    fullscreenBtn.click(); // Trigger the restore action
                }
            }
        });
        return '';
    }
    """,
    Output('fullscreen-trigger', 'title'),
    Input('minimal-dock', 'id')
)

# MultiQC Investigation Callbacks
clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return '';
        
        try {
            const iframe = document.querySelector('#multiqc-iframe');
            if (!iframe || !iframe.contentWindow) {
                return 'Error: Cannot access iframe content (CORS/Same-origin policy)';
            }
            
            const iframeDoc = iframe.contentWindow.document;
            
            // Look for highlight samples input - common selectors
            const possibleSelectors = [
                'input[placeholder*="highlight"]',
                'input[placeholder*="sample"]', 
                '#mqc-highlight-input',
                '.highlight-input',
                'input[id*="highlight"]',
                'input[class*="highlight"]',
                '#toolbox input[type="text"]',
                '.mqc-toolbox input[type="text"]'
            ];
            
            let results = [];
            results.push('=== SEARCHING FOR HIGHLIGHT SAMPLES INPUT ===\\n');
            
            for (let selector of possibleSelectors) {
                const elements = iframeDoc.querySelectorAll(selector);
                if (elements.length > 0) {
                    results.push(`✅ Found ${elements.length} element(s) with selector: ${selector}`);
                    elements.forEach((el, i) => {
                        results.push(`  [${i}] Tag: ${el.tagName}, ID: ${el.id}, Class: ${el.className}`);
                        results.push(`      Placeholder: "${el.placeholder || 'none'}"`);
                        results.push(`      Value: "${el.value || 'empty'}"`);
                    });
                } else {
                    results.push(`❌ No elements found for: ${selector}`);
                }
            }
            
            // Also check for any toolbox container
            const toolbox = iframeDoc.querySelector('#toolbox, .toolbox, [id*="toolbox"]');
            if (toolbox) {
                results.push('\\n=== TOOLBOX CONTAINER FOUND ===');
                results.push(`Toolbox HTML snippet: ${toolbox.outerHTML.substring(0, 200)}...`);
            }
            
            return results.join('\\n');
            
        } catch (error) {
            return `Error accessing iframe: ${error.message}\\n\\nThis is likely due to CORS restrictions. The MultiQC report is served from a different origin than our Dash app, so we cannot directly access its content via JavaScript.\\n\\nPossible solutions:\\n1. Serve MultiQC from same origin\\n2. Use postMessage API\\n3. Browser extension approach`;
        }
    }
    """,
    Output('investigation-output', 'children'),
    Input('inspect-highlight-btn', 'n_clicks')
)

clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return '';
        
        try {
            const iframe = document.querySelector('#multiqc-iframe');
            if (!iframe || !iframe.contentWindow) {
                return 'Error: Cannot access iframe content';
            }
            
            const iframeDoc = iframe.contentWindow.document;
            
            // Try to find and interact with highlight input
            const input = iframeDoc.querySelector('input[placeholder*="highlight"], input[placeholder*="sample"], #mqc-highlight-input, .highlight-input');
            
            if (input) {
                // Clear existing value and set new value
                input.value = '';
                input.value = '00050101';
                
                // Trigger input events
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                
                return `✅ Successfully set input value to "00050101"\\nInput element: ${input.tagName}#${input.id}.${input.className}\\nCurrent value: "${input.value}"`;
            } else {
                return '❌ Could not find highlight samples input field';
            }
            
        } catch (error) {
            return `Error: ${error.message}`;
        }
    }
    """,
    Output('investigation-output', 'children'),
    Input('test-sample-input-btn', 'n_clicks')
)

clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return '';
        
        try {
            const iframe = document.querySelector('#multiqc-iframe');
            const iframeDoc = iframe.contentWindow.document;
            
            const input = iframeDoc.querySelector('input[placeholder*="highlight"], input[placeholder*="sample"]');
            
            if (input) {
                // Focus the input first
                input.focus();
                
                // Simulate Enter key press
                const enterEvent = new KeyboardEvent('keydown', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true
                });
                
                input.dispatchEvent(enterEvent);
                
                // Also try keyup
                const enterUpEvent = new KeyboardEvent('keyup', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true
                });
                
                input.dispatchEvent(enterUpEvent);
                
                return `✅ Simulated Enter key on input field\\nValue: "${input.value}"`;
            } else {
                return '❌ Could not find input field to simulate Enter key';
            }
            
        } catch (error) {
            return `Error: ${error.message}`;
        }
    }
    """,
    Output('investigation-output', 'children'),
    Input('simulate-enter-btn', 'n_clicks')
)

clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return '';
        
        try {
            const iframe = document.querySelector('#multiqc-iframe');
            const iframeDoc = iframe.contentWindow.document;
            
            // Look for + button near the highlight input
            const plusSelectors = [
                'button[title*="+"], button[title*="add"]',
                '.btn:contains("+")',
                'button.add-btn, .add-button',
                '[class*="highlight"] button, [id*="highlight"] button',
                '.input-group button, .input-group-btn button'
            ];
            
            let results = [];
            
            for (let selector of plusSelectors) {
                const buttons = iframeDoc.querySelectorAll(selector);
                if (buttons.length > 0) {
                    results.push(`Found ${buttons.length} potential + buttons with: ${selector}`);
                    
                    // Try clicking the first one
                    const button = buttons[0];
                    button.click();
                    
                    results.push(`✅ Clicked button: ${button.tagName} ${button.className} "${button.textContent}"`);
                    break;
                }
            }
            
            if (results.length === 0) {
                results.push('❌ Could not find + button to click');
                
                // Fallback: look for any button near input
                const input = iframeDoc.querySelector('input[placeholder*="highlight"]');
                if (input) {
                    const parent = input.parentElement;
                    const nearbyButtons = parent.querySelectorAll('button');
                    results.push(`Found ${nearbyButtons.length} buttons near input in parent container`);
                }
            }
            
            return results.join('\\n');
            
        } catch (error) {
            return `Error: ${error.message}`;
        }
    }
    """,
    Output('investigation-output', 'children'),
    Input('simulate-plus-btn', 'n_clicks')
)

if __name__ == '__main__':
    print("🚀 Starting minimal dash-dock + MultiQC test...")
    print("📍 http://localhost:8051")
    print("🔧 Test Flask: http://localhost:8051/test")
    print("📊 Test MultiQC: http://localhost:8051/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html")
    app.run(debug=True, port=8051)