#!/usr/bin/env python3
"""
Same-Origin MultiQC Proxy Test
Testing MultiQC toolbox automation with same-origin serving to bypass CORS restrictions
"""

from pathlib import Path
import re

import dash_dock
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from flask import Flask, Response, abort

import dash
from dash import Input, Output, dcc, html, clientside_callback

# Initialize Flask server for MultiQC proxy serving
server = Flask(__name__)

# Configuration for MultiQC data location
MULTIQC_DATA_PATH = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData"

# Alternative paths to try for MultiQC data
ALTERNATIVE_PATHS = [
    "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData",
    "/Users/tweber/Downloads",
    "/tmp",
    "."
]

def find_multiqc_file(filename):
    """Find MultiQC file in various possible locations"""
    for base_path in ALTERNATIVE_PATHS:
        file_path = Path(base_path) / filename
        if file_path.exists():
            return file_path
    return None

@server.route('/multiqc-proxy/<path:filename>')
def serve_multiqc_proxy(filename):
    """Proxy MultiQC content from same origin to bypass CORS"""
    print(f"🔄 Proxying MultiQC file: {filename}")
    
    file_path = find_multiqc_file(filename)
    
    if not file_path:
        print(f"❌ File not found in any location: {filename}")
        print(f"📁 Searched paths: {ALTERNATIVE_PATHS}")
        abort(404)
    
    try:
        # Determine MIME type
        if filename.endswith('.html'):
            return serve_multiqc_html(file_path)
        elif filename.endswith('.css'):
            return serve_static_asset(file_path, 'text/css')
        elif filename.endswith('.js'):
            return serve_static_asset(file_path, 'application/javascript')
        elif filename.endswith('.png'):
            return serve_static_asset(file_path, 'image/png')
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            return serve_static_asset(file_path, 'image/jpeg')
        else:
            return serve_static_asset(file_path, 'application/octet-stream')
            
    except Exception as e:
        print(f"❌ Error serving {filename}: {e}")
        abort(500)

def serve_multiqc_html(file_path):
    """Process and serve MultiQC HTML with same-origin modifications"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Process relative URLs to point to our proxy
    content = re.sub(r'src="([^"]+)"', r'src="/multiqc-proxy/\1"', content)
    content = re.sub(r'href="([^"]+\.css)"', r'href="/multiqc-proxy/\1"', content)
    content = re.sub(r'url\(([^)]+)\)', r'url(/multiqc-proxy/\1)', content)
    
    # Inject automation helpers
    automation_script = """
    <script>
    window.addEventListener('DOMContentLoaded', function() {
        console.log('🚀 MultiQC loaded with automation helpers');
        
        // Signal readiness to parent frame
        if (window.parent !== window) {
            window.parent.postMessage({type: 'multiqc-ready', source: 'automation'}, '*');
        }
        
        // Add automation helper functions
        window.multiqcAutomation = {
            highlightSamples: function(sampleId) {
                console.log('🎯 Attempting to highlight samples:', sampleId);
                const selectors = [
                    'input[placeholder*="highlight" i]',
                    'input[placeholder*="sample" i]',
                    '#mqc-highlight-input',
                    '.highlight-input',
                    'input[id*="highlight"]',
                    'input[class*="highlight"]',
                    '#toolbox input[type="text"]',
                    '.mqc-toolbox input[type="text"]',
                    '.mqc_toolbox input[type="text"]',
                    '#mqc_toolbox input[type="text"]'
                ];
                
                for (let selector of selectors) {
                    const input = document.querySelector(selector);
                    if (input) {
                        console.log('✅ Found highlight input:', selector);
                        input.value = sampleId;
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                        return {success: true, element: selector, value: input.value};
                    }
                }
                
                console.log('❌ No highlight input found');
                return {success: false, message: 'No highlight input element found'};
            },
            
            clickAddButton: function() {
                console.log('➕ Attempting to click add button');
                const selectors = [
                    'button[title*="+" i]',
                    'button[title*="add" i]',
                    '.btn-add',
                    '.add-btn',
                    'button.add',
                    '[class*="highlight"] button',
                    '.input-group button',
                    '.input-group-btn button'
                ];
                
                for (let selector of selectors) {
                    const button = document.querySelector(selector);
                    if (button) {
                        console.log('✅ Found add button:', selector);
                        button.click();
                        return {success: true, element: selector};
                    }
                }
                
                console.log('❌ No add button found');
                return {success: false, message: 'No add button element found'};
            },
            
            simulateEnter: function() {
                console.log('⌨️ Simulating Enter key');
                const input = document.querySelector('input[placeholder*="highlight" i], input[placeholder*="sample" i]');
                if (input) {
                    input.focus();
                    const event = new KeyboardEvent('keydown', {
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    });
                    input.dispatchEvent(event);
                    return {success: true, value: input.value};
                }
                return {success: false, message: 'No input element found'};
            },
            
            inspectPage: function() {
                console.log('🔍 Inspecting MultiQC page structure');
                const toolbox = document.querySelector('#toolbox, .toolbox, [id*="toolbox"], .mqc-toolbox, .mqc_toolbox');
                const inputs = document.querySelectorAll('input[type="text"]');
                const buttons = document.querySelectorAll('button');
                
                return {
                    toolbox: toolbox ? {
                        id: toolbox.id,
                        className: toolbox.className,
                        innerHTML: toolbox.innerHTML.substring(0, 500)
                    } : null,
                    inputCount: inputs.length,
                    buttonCount: buttons.length,
                    inputDetails: Array.from(inputs).slice(0, 5).map(input => ({
                        id: input.id,
                        className: input.className,
                        placeholder: input.placeholder,
                        value: input.value
                    }))
                };
            }
        };
        
        console.log('✅ MultiQC automation helpers installed');
    });
    </script>
    """
    
    # Inject before closing </head> tag
    if '</head>' in content:
        content = content.replace('</head>', automation_script + '</head>')
    else:
        # If no </head>, add to end of content
        content += automation_script
    
    print("✅ MultiQC HTML processed and automation scripts injected")
    return Response(content, mimetype='text/html')

def serve_static_asset(file_path, mimetype):
    """Serve static assets (CSS, JS, images)"""
    with open(file_path, 'rb') as f:
        return Response(f.read(), mimetype=mimetype)

# Mock function removed - using real MultiQC reports only

# Test route
@server.route('/test-proxy')
def test_proxy():
    return "✅ Same-origin proxy server is working!"

# Initialize Dash app with the Flask server
app = dash.Dash(__name__, server=server, suppress_callback_exceptions=True)

# Dock configuration for MultiQC
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
                        "name": "MultiQC Report (Same-Origin)",
                        "component": "text",
                        "id": "multiqc-tab",
                        "enableFloat": True
                    }
                ]
            }
        ]
    }
}

# Tab content with same-origin iframe
tab_components = [
    dash_dock.Tab(
        id="multiqc-tab",
        children=[
            html.Iframe(
                id="multiqc-iframe",
                src="/multiqc-proxy/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
                style={
                    'width': '100%',
                    'height': '100%',
                    'border': 'none'
                }
            )
        ]
    )
]

# Main app layout
app.layout = dmc.MantineProvider([
    html.H1("🧪 Same-Origin MultiQC Automation Test"),
    
    dmc.Alert(
        "This prototype tests MultiQC toolbox automation using same-origin serving to bypass CORS restrictions.",
        title="🔬 Experiment Status",
        icon=DashIconify(icon="mdi:flask"),
        color="blue"
    ),
    
    # Control panel
    dmc.Card([
        dmc.Title("🎮 Automation Controls", order=3),
        dmc.Space(h=10),
        
        dmc.Group([
            dmc.Button(
                "Inspect MultiQC Page",
                id="inspect-page-btn",
                leftSection=DashIconify(icon="mdi:magnify"),
                variant="outline",
                size="sm"
            ),
            dmc.Button(
                "Set Sample ID (00050101)",
                id="set-sample-btn", 
                leftSection=DashIconify(icon="mdi:text-box"),
                variant="outline",
                size="sm"
            ),
            dmc.Button(
                "Simulate Enter Key",
                id="simulate-enter-btn",
                leftSection=DashIconify(icon="mdi:keyboard"),
                variant="outline", 
                size="sm"
            ),
            dmc.Button(
                "Click Add Button",
                id="click-add-btn",
                leftSection=DashIconify(icon="mdi:plus"),
                variant="outline",
                size="sm"
            )
        ], gap="sm"),
        
        dmc.Space(h=15),
        
        # Results display
        html.Div(id="automation-results", style={
            'background': '#f8f9fa',
            'padding': '15px',
            'borderRadius': '8px',
            'border': '1px solid #dee2e6',
            'fontFamily': 'monospace',
            'fontSize': '12px',
            'whiteSpace': 'pre-wrap',
            'minHeight': '100px'
        })
    ], withBorder=True, shadow="sm", p="lg", m="lg"),
    
    # MultiQC iframe in dock container
    html.Div([
        dash_dock.DashDock(
            id='dock-layout',
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
    ], id="dock-container", style={
        'height': '60vh',
        'width': '100%',
        'position': 'relative',
        'overflow': 'hidden',
        'border': '2px solid #dee2e6',
        'borderRadius': '8px',
        'margin': '20px'
    }),
    
    # Test links
    dmc.Group([
        html.A(
            dmc.Button(
                "Test Proxy Server",
                leftSection=DashIconify(icon="mdi:server"),
                variant="light",
                size="sm"
            ),
            href="/test-proxy",
            target="_blank"
        ),
        html.A(
            dmc.Button(
                "Open MultiQC in New Tab",
                leftSection=DashIconify(icon="mdi:open-in-new"),
                variant="light", 
                size="sm"
            ),
            href="/multiqc-proxy/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
            target="_blank"
        )
    ], justify="center", m="lg"),
    
    html.Div([
        html.H4("🔍 Expected Results:"),
        html.Ul([
            html.Li("✅ Proxy server eliminates CORS restrictions"),
            html.Li("✅ Automation buttons can access iframe content"),
            html.Li("✅ Sample ID input can be programmatically controlled"),
            html.Li("✅ Button clicks and keyboard events work"),
            html.Li("📊 Full DOM access enables advanced automation")
        ])
    ], style={
        'background': '#e7f3ff',
        'padding': '15px',
        'borderRadius': '8px',
        'margin': '20px',
        'border': '1px solid #b3d9ff'
    })
])

# Combined automation callback (same-origin enabled)
clientside_callback(
    """
    function(inspect_clicks, set_clicks, enter_clicks, add_clicks) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) return '🚀 Same-origin MultiQC automation ready. Click any button to test.';
        
        const triggered_id = ctx.triggered[0]['prop_id'].split('.')[0];
        
        try {
            const iframe = document.querySelector('#multiqc-iframe');
            if (!iframe) {
                return '❌ Error: MultiQC iframe not found';
            }
            
            // With same-origin serving, this should now work!
            const iframeDoc = iframe.contentWindow.document;
            
            if (!iframeDoc) {
                return '❌ Error: Still cannot access iframe document (check same-origin implementation)';
            }
            
            if (triggered_id === 'inspect-page-btn') {
                // INSPECT PAGE FUNCTIONALITY
                let results = ['=== 🔍 SAME-ORIGIN MULTIQC PAGE INSPECTION ===\\n'];
                
                // Check if automation helpers are available
                const automation = iframe.contentWindow.multiqcAutomation;
                if (automation) {
                    results.push('✅ MultiQC automation helpers detected!');
                    const inspection = automation.inspectPage();
                    
                    results.push(`\\n📊 Page Structure:`);
                    results.push(`   - Input fields found: ${inspection.inputCount}`);
                    results.push(`   - Buttons found: ${inspection.buttonCount}`);
                    
                    if (inspection.toolbox) {
                        results.push(`   - Toolbox detected: #${inspection.toolbox.id} .${inspection.toolbox.className}`);
                    } else {
                        results.push(`   - No toolbox container found`);
                    }
                    
                    if (inspection.inputDetails.length > 0) {
                        results.push(`\\n📝 Input Field Details:`);
                        inspection.inputDetails.forEach((input, i) => {
                            results.push(`   [${i}] ID: ${input.id || 'none'}`);
                            results.push(`       Class: ${input.className || 'none'}`);
                            results.push(`       Placeholder: "${input.placeholder || 'none'}"`);
                            results.push(`       Value: "${input.value || 'empty'}"`);
                        });
                    }
                } else {
                    // Fallback direct DOM inspection
                    results.push('⚠️ No automation helpers found, using direct DOM access...');
                    
                    const inputs = iframeDoc.querySelectorAll('input[type="text"]');
                    const buttons = iframeDoc.querySelectorAll('button');
                    const toolbox = iframeDoc.querySelector('#toolbox, .toolbox, [id*="toolbox"]');
                    
                    results.push(`\\n📊 Direct DOM Inspection:`);
                    results.push(`   - Input fields: ${inputs.length}`);
                    results.push(`   - Buttons: ${buttons.length}`);
                    results.push(`   - Toolbox: ${toolbox ? 'Found' : 'Not found'}`);
                    
                    // Try to find highlight input
                    const highlightInput = iframeDoc.querySelector('input[placeholder*="highlight" i], #highlight-samples');
                    if (highlightInput) {
                        results.push(`\\n✅ Highlight input found:`);
                        results.push(`   - ID: ${highlightInput.id}`);
                        results.push(`   - Placeholder: "${highlightInput.placeholder}"`);
                        results.push(`   - Current value: "${highlightInput.value}"`);
                    }
                }
                
                return results.join('\\n');
                
            } else if (triggered_id === 'set-sample-btn') {
                // SET SAMPLE ID FUNCTIONALITY
                const automation = iframe.contentWindow.multiqcAutomation;
                if (automation) {
                    const result = automation.highlightSamples('00050101');
                    if (result.success) {
                        return `✅ SUCCESS: Sample ID set using automation helper\\n` +
                               `   - Element: ${result.element}\\n` +
                               `   - Value: "${result.value}"\\n` +
                               `   - Same-origin access: WORKING! 🎉`;
                    } else {
                        return `❌ FAILED: ${result.message}`;
                    }
                } else {
                    // Fallback direct approach
                    const input = iframeDoc.querySelector('input[placeholder*="highlight" i], #highlight-samples');
                    if (input) {
                        input.value = '00050101';
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                        return `✅ SUCCESS: Direct DOM manipulation worked!\\n` +
                               `   - Element: ${input.tagName}#${input.id}\\n` +
                               `   - Value: "${input.value}"\\n` +
                               `   - Same-origin access: WORKING! 🎉`;
                    } else {
                        return `❌ FAILED: No highlight input field found`;
                    }
                }
                
            } else if (triggered_id === 'simulate-enter-btn') {
                // SIMULATE ENTER KEY
                const automation = iframe.contentWindow.multiqcAutomation;
                if (automation) {
                    const result = automation.simulateEnter();
                    if (result.success) {
                        return `✅ SUCCESS: Enter key simulated using automation helper\\n` +
                               `   - Input value: "${result.value}"\\n` +
                               `   - Same-origin keyboard events: WORKING! ⌨️`;
                    } else {
                        return `❌ FAILED: ${result.message}`;
                    }
                } else {
                    const input = iframeDoc.querySelector('input[placeholder*="highlight" i], #highlight-samples');
                    if (input) {
                        input.focus();
                        const event = new KeyboardEvent('keydown', {
                            key: 'Enter',
                            code: 'Enter', 
                            keyCode: 13,
                            which: 13,
                            bubbles: true
                        });
                        input.dispatchEvent(event);
                        return `✅ SUCCESS: Direct Enter key simulation worked!\\n` +
                               `   - Input value: "${input.value}"\\n` +
                               `   - Same-origin keyboard events: WORKING! ⌨️`;
                    } else {
                        return `❌ FAILED: No input field found for Enter simulation`;
                    }
                }
                
            } else if (triggered_id === 'click-add-btn') {
                // CLICK ADD BUTTON
                const automation = iframe.contentWindow.multiqcAutomation;
                if (automation) {
                    const result = automation.clickAddButton();
                    if (result.success) {
                        return `✅ SUCCESS: Add button clicked using automation helper\\n` +
                               `   - Element: ${result.element}\\n` +
                               `   - Same-origin button clicks: WORKING! ➕`;
                    } else {
                        return `❌ FAILED: ${result.message}`;
                    }
                } else {
                    const button = iframeDoc.querySelector('button.add-btn, .add-btn');
                    if (button) {
                        button.click();
                        return `✅ SUCCESS: Direct button click worked!\\n` +
                               `   - Button: ${button.textContent}\\n` +
                               `   - Same-origin button clicks: WORKING! ➕`;
                    } else {
                        return `❌ FAILED: No add button found`;
                    }
                }
            }
            
        } catch (error) {
            return `💥 CRITICAL ERROR: ${error.message}\\n\\n` +
                   `This suggests same-origin serving is not working correctly.\\n` +
                   `Expected: Full DOM access\\n` +
                   `Actual: ${error.name}\\n\\n` +
                   `Check the Flask proxy implementation.`;
        }
        
        return '🤔 Unknown button triggered';
    }
    """,
    Output('automation-results', 'children'),
    [Input('inspect-page-btn', 'n_clicks'),
     Input('set-sample-btn', 'n_clicks'), 
     Input('simulate-enter-btn', 'n_clicks'),
     Input('click-add-btn', 'n_clicks')]
)

if __name__ == '__main__':
    print("🚀 Starting Same-Origin MultiQC Automation Test...")
    print("📍 Main App: http://localhost:8053")
    print("🔧 Test Proxy: http://localhost:8053/test-proxy")
    print("📊 MultiQC Direct: http://localhost:8053/multiqc-proxy/multiqc_output_fastqc_v1_30_0/multiqc_report.html")
    print("\n🎯 Expected Behavior:")
    print("  ✅ Iframe content should be accessible (same-origin)")
    print("  ✅ Automation buttons should successfully manipulate MultiQC")
    print("  ✅ Sample ID input should be programmably controllable")
    print("  ✅ Keyboard/mouse events should work")
    print("\n🔬 This tests the CORS bypass solution!")
    
    app.run(debug=True, port=8053)