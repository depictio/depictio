#!/usr/bin/env python3
"""
Minimal dash-dock prototype with MultiQC HTML serving
Single tab, single iframe, focused on getting the basic functionality working
"""

from pathlib import Path

import dash_dock
import dash_mantine_components as dmc
import polars as pl
from flask import Flask, abort, send_from_directory

import dash
from dash import ClientsideFunction, Input, Output, State, callback, clientside_callback, dcc, html

# Initialize Flask server for serving external HTML files
server = Flask(__name__)

# Flask route to serve external files (HTML, CSS, JS, images, source maps, etc.)
@server.route('/external/<path:filename>')
def serve_external_html(filename):
    """Serve files from external MultiQC locations"""
    external_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData"
    
    print(f"📁 Serving: {filename}")
    print(f"📂 From: {external_path}")
    
    file_path = Path(external_path) / filename
    print(f"🔍 Full path: {file_path}")
    print(f"✅ Exists: {file_path.exists()}")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        abort(404)
    
    # Allow common MultiQC file types
    allowed_extensions = {'.html', '.css', '.js', '.map', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.json', '.woff', '.woff2', '.ttf', '.eot'}
    if file_path.suffix.lower() not in allowed_extensions:
        print(f"❌ File type not allowed: {file_path.suffix}")
        abort(404)
    
    return send_from_directory(external_path, filename)

# Test route
@server.route('/test')
def test_route():
    return "<h1>Flask is working!</h1><p>Server is running correctly.</p>"

# Initialize Dash app with Flask server
app = dash.Dash(__name__, server=server)

# Load sample list from MultiQC parquet file
def load_multiqc_samples():
    """Load unique sample names from MultiQC parquet file using general_stats_table anchor"""
    try:
        parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_30_0/multiqc_data/BETA-multiqc.parquet"
        df = pl.read_parquet(parquet_path)
        
        if 'sample' in df.columns and 'anchor' in df.columns:
            # Filter by general_stats_table anchor, select sample column, drop nulls
            sample_series = (
                df.filter(pl.col("anchor") == "general_stats_table")
                .select("sample")
                .drop_nulls()
                .unique()
                .sort("sample")
            )
            
            # Convert to list and filter out None values and "null" strings
            sample_list = [
                s for s in sample_series["sample"].to_list() 
                if s is not None and s != "null" and s != ""
            ]
            
            print(f"✅ Loaded {len(sample_list)} unique samples from general_stats_table")
            return sample_list
        else:
            missing_cols = [col for col in ['sample', 'anchor'] if col not in df.columns]
            print(f"❌ Missing columns in parquet file: {missing_cols}")
            return ["00050101", "F1-1A_S1_R1_001"]  # Fallback samples
    except Exception as e:
        print(f"❌ Error loading MultiQC samples: {e}")
        return ["00050101", "F1-1A_S1_R1_001"]  # Fallback samples

# Load available samples
AVAILABLE_SAMPLES = load_multiqc_samples()

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
                # html.H4("MultiQC Report Viewer", 
                #        style={'margin': '10px', 'color': '#333', 'textAlign': 'center'}),
                # html.Div([
                #     html.A("🔗 Test Flask Route", href="/test", target="_blank", 
                #            style={'marginRight': '20px', 'color': 'blue'}),
                #     html.A("📊 Direct MultiQC Link", 
                #            href="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html", 
                #            target="_blank", style={'color': 'green'})
                # ], style={'textAlign': 'center', 'margin': '10px'}),
                # html.Hr(),
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
        html.H1("🧪 Minimal Depictio x MultiQC interface prototype", 
               style={'textAlign': 'center', 'margin': '20px', 'color': '#2c3e50'}),
        
        # html.Div([
        #     "✅ Flask serving external HTML files",
        #     html.Br(),
        #     "✅ Single dash-dock tab with iframe", 
        #     html.Br(),
        #     "✅ Tab floating enabled (tabEnableFloat: True)",
        # ], style={
        #     'backgroundColor': '#e8f5e8', 
        #     'padding': '15px', 
        #     'margin': '20px',
        #     'borderRadius': '8px',
        #     'border': '1px solid #4CAF50'
        # })
        # ,
        
        # MultiQC Toolbox Automation Panel
        html.Div([
            html.H4("🔍 MultiQC Toolbox Automation"),
            
            # HIGHLIGHT SAMPLES SECTION
            html.Div([
                html.H5("🎨 Highlight Samples", style={'margin': '0 0 10px 0', 'color': '#1976d2'}),
                html.Div([
                    # TagsInput for sample patterns with autocomplete
                    dmc.TagsInput(
                        id="highlight-pattern-input",
                        label="Sample Patterns",
                        placeholder="Type or select samples (supports regex)",
                        value=[],
                        data=AVAILABLE_SAMPLES,
                        maxDropdownHeight=300,
                        limit=10,
                        clearable=True,
                        searchValue="",
                        style={'width': '280px', 'marginRight': '10px'}
                    ),
                    # Regex toggle
                    dmc.Switch(
                        id="highlight-regex-switch",
                        label="Use Regex",
                        checked=False,
                        style={'marginRight': '15px'}
                    ),
                    # Action buttons
                    dmc.Button("Clear All", id="highlight-clear-btn", variant="outline", color="red", size="sm", style={'margin': '0 5px'}),
                ], style={'display': 'flex', 'alignItems': 'end', 'flexWrap': 'wrap', 'gap': '10px'})
            ], style={
                'backgroundColor': '#e3f2fd', 
                'padding': '15px', 
                'margin': '10px 0',
                'borderRadius': '8px',
                'border': '2px solid #1976d2'
            }),
            
            # SHOW/HIDE SAMPLES SECTION
            html.Div([
                html.H5("👁️ Show/Hide Samples", style={'margin': '0 0 10px 0', 'color': '#388e3c'}),
                html.Div([
                    # TagsInput for sample patterns with autocomplete
                    dmc.TagsInput(
                        id="showhide-pattern-input",
                        label="Sample Patterns",
                        placeholder="Type or select samples (supports regex)",
                        value=[],
                        data=AVAILABLE_SAMPLES,
                        maxDropdownHeight=300,
                        limit=10,
                        clearable=True,
                        searchValue="",
                        style={'width': '280px', 'marginRight': '10px'}
                    ),
                    # Regex toggle
                    dmc.Switch(
                        id="showhide-regex-switch",
                        label="Use Regex",
                        checked=False,
                        style={'marginRight': '15px'}
                    ),
                    # Show/Hide mode toggle
                    dmc.SegmentedControl(
                        id="showhide-mode-control",
                        value="show",
                        data=[
                            {"label": "👁️ Show Only", "value": "show"},
                            {"label": "🙈 Hide", "value": "hide"}
                        ],
                        style={'marginRight': '15px'}
                    ),
                    # Action buttons
                    dmc.Button("Clear All", id="showhide-clear-btn", variant="outline", color="red", size="sm", style={'margin': '0 5px'}),
                ], style={'display': 'flex', 'alignItems': 'end', 'flexWrap': 'wrap', 'gap': '10px'})
            ], style={
                'backgroundColor': '#e8f5e9', 
                'padding': '15px', 
                'margin': '10px 0',
                'borderRadius': '8px',
                'border': '2px solid #388e3c'
            }),
            
            # DEBUG SECTION (collapsible)
            dmc.Accordion(
                children=[
                    dmc.AccordionItem([
                        dmc.AccordionControl("🔧 Debug Controls"),
                        dmc.AccordionPanel([
                            dmc.Group([
                                dmc.Button("Inspect MultiQC", id="inspect-highlight-btn", variant="outline", size="xs"),
                                dmc.Button("Test Pattern Input", id="test-sample-input-btn", variant="outline", size="xs"),
                                dmc.Button("Test + Button", id="simulate-plus-btn", variant="outline", size="xs"),
                                dmc.Button("Test Apply", id="simulate-apply-btn", variant="outline", size="xs"),
                                dmc.Button("Test Enter", id="simulate-enter-btn", variant="outline", size="xs"),
                            ], gap="xs", style={'flexWrap': 'wrap'})
                        ])
                    ], value="debug-controls")
                ],
                style={'margin': '10px 0'}
            ),
            
            # OUTPUT AREA (collapsible)
            dmc.Accordion(
                children=[
                    dmc.AccordionItem([
                        dmc.AccordionControl("📋 Debug Console Output"),
                        dmc.AccordionPanel([
                            html.Pre(id="investigation-output", style={
                                'backgroundColor': '#f8f9fa', 
                                'padding': '10px', 
                                'margin': '0',
                                'borderRadius': '4px',
                                'border': '1px solid #ddd',
                                'fontSize': '12px',
                                'maxHeight': '300px',
                                'overflow': 'auto',
                                'whiteSpace': 'pre-wrap'
                            })
                        ])
                    ], value="debug-output")
                ],
                value=["debug-output"],  # Start with output expanded
                multiple=True,
                style={'margin': '10px 0'}
            )
        ], style={
            'backgroundColor': '#fff', 
            'padding': '20px', 
            'margin': '20px',
            'borderRadius': '12px',
            'border': '1px solid #ddd',
            'boxShadow': '0 2px 8px rgba(0,0,0,0.1)'
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

# Combined MultiQC Automation Callback
clientside_callback(
    """
    function(
        // Debug buttons - Inputs
        inspect_clicks, test_clicks, plus_clicks, apply_clicks, enter_clicks,
        // Clear buttons - Inputs
        highlight_clear_clicks, showhide_clear_clicks,
        // Automatic triggers on dropdown changes - Inputs
        highlight_pattern, showhide_pattern,
        // All States (configuration)
        highlight_regex, showhide_regex, showhide_mode
    ) {
        // Determine what triggered the callback
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) return '🚀 MultiQC toolbox automation ready. Select samples to trigger automation.';
        
        const triggered = ctx.triggered[0]['prop_id'];
        const triggered_id = triggered.split('.')[0];
        const triggered_prop = triggered.split('.')[1];
        
        try {
            // DEBUG: Log all parameters to understand the error
            console.log('DEBUG - Callback parameters:', {
                highlight_pattern: highlight_pattern,
                showhide_pattern: showhide_pattern,
                highlight_pattern_type: typeof highlight_pattern,
                showhide_pattern_type: typeof showhide_pattern,
                triggered_id: triggered_id,
                triggered_prop: triggered_prop
            });
            
            const iframe = document.querySelector('#multiqc-iframe');
            if (!iframe || !iframe.contentWindow) {
                return '❌ Error: Cannot access iframe - check if MultiQC content is loaded.';
            }
            
            // 🎯 CRITICAL TEST: Try to access iframe document
            const iframeDoc = iframe.contentWindow.document;
            
            if (!iframeDoc) {
                return '❌ CORS BLOCKED: Cannot access iframe.contentWindow.document\\n\\n' +
                       'This confirms CORS/Same-Origin Policy restrictions.\\n' +
                       'MultiQC content and Dash app are from different origins.';
            }
            
            // If we get here, we have same-origin access! 🎉
            const originStatus = `✅ SAME-ORIGIN ACCESS CONFIRMED!\\n` +
                               `✅ iframe.contentWindow.document accessible\\n` +
                               `✅ No CORS restrictions detected\\n\\n`;
            
            if (triggered_id === 'inspect-highlight-btn') {
                // INSPECT PAGE FUNCTIONALITY (using REAL MultiQC selectors)
                const possibleSelectors = [
                    '#mqc_colour_filter',  // The actual "Custom Pattern" input
                    'input[placeholder="Custom Pattern"]',
                    '#mqc_colour_filter_color',  // The color picker
                    '#mqc_cols input[type="text"]',  // Any text inputs in the toolbox
                    '.mqc_filter_section input[type="text"]'
                ];
                
                let results = [originStatus + '=== SEARCHING FOR HIGHLIGHT SAMPLES INPUT ===\\n'];
                
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
                
                // Check toolbox containers (using REAL MultiQC structure)
                const toolbox = iframeDoc.querySelector('#mqc_cols, .mqc_filter_section, .mqc-toolbox-label');
                if (toolbox) {
                    results.push('\\n=== MULTIQC TOOLBOX FOUND ===');
                    results.push(`Toolbox element: ${toolbox.id ? '#' + toolbox.id : '.' + toolbox.className}`);
                    results.push(`Toolbox HTML snippet: ${toolbox.outerHTML.substring(0, 300)}...`);
                } else {
                    results.push('\\n❌ No MultiQC toolbox container found');
                }
                
                return results.join('\\n');
                
            } else if (triggered_id === 'test-sample-input-btn') {
                // TEST SAMPLE INPUT FUNCTIONALITY (using REAL MultiQC input)
                const input = iframeDoc.querySelector('#mqc_colour_filter');  // The actual "Custom Pattern" input
                
                if (input) {
                    input.value = '';
                    input.value = '00050101';
                    
                    // Trigger proper input events for MultiQC
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('keyup', { bubbles: true }));  // MultiQC might listen to keyup
                    
                    return originStatus + 
                           `✅ SUCCESS: Sample ID set in MultiQC Custom Pattern input!\\n` +
                           `   - Element: ${input.tagName}#${input.id}\\n` +
                           `   - Placeholder: "${input.placeholder}"\\n` +
                           `   - Current value: "${input.value}"\\n` +
                           `   - Input/change/keyup events dispatched successfully`;
                } else {
                    return originStatus + 
                           '❌ FAILED: Could not find #mqc_colour_filter input\\n' +
                           'But iframe DOM access is working (CORS not the issue)';
                }
                
            } else if (triggered_id === 'simulate-enter-btn') {
                // SIMULATE ENTER KEY (on actual MultiQC Custom Pattern input)
                const input = iframeDoc.querySelector('#mqc_colour_filter');
                
                if (input) {
                    input.focus();
                    
                    // Try to trigger form submission (MultiQC form might listen to Enter)
                    const enterEvent = new KeyboardEvent('keydown', {
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    });
                    input.dispatchEvent(enterEvent);
                    
                    const enterUpEvent = new KeyboardEvent('keyup', {
                        key: 'Enter',
                        code: 'Enter', 
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    });
                    input.dispatchEvent(enterUpEvent);
                    
                    // Also try triggering the form submit directly
                    const form = iframeDoc.querySelector('#mqc_color_form');
                    if (form) {
                        form.dispatchEvent(new Event('submit', { bubbles: true }));
                    }
                    
                    return originStatus +
                           `✅ SUCCESS: Enter key + form submit attempted!\\n` +
                           `   - Input: #mqc_colour_filter\\n` +
                           `   - Input value: "${input.value}"\\n` +
                           `   - KeyDown + KeyUp events sent\\n` +
                           `   - Form submit event sent: ${form ? 'Yes' : 'No'}`;
                } else {
                    return originStatus + 
                           '❌ FAILED: Could not find #mqc_colour_filter input\\n' +
                           'But iframe DOM access is working (CORS not the issue)';
                }
                
            } else if (triggered_id === 'simulate-plus-btn') {
                // SIMULATE + BUTTON CLICK (using REAL MultiQC IDs from the provided structure)
                const plusSelectors = [
                    '#mqc_colour_filter_update',  // The actual "+" button: <button type="submit" id="mqc_colour_filter_update" class="btn btn-default btn-sm">+</button>
                    'button[type="submit"]#mqc_colour_filter_update',
                    '.mqc_toolbox_clear',  // The Clear button with trash icon
                    '#mqc_cols_apply',  // The Apply button
                    'button.btn.btn-default.btn-sm'  // Generic class match
                ];
                
                let results = [originStatus + '=== SEARCHING FOR ADD/+ BUTTONS ===\\n'];
                
                for (let selector of plusSelectors) {
                    const buttons = iframeDoc.querySelectorAll(selector);
                    if (buttons.length > 0) {
                        results.push(`✅ Found ${buttons.length} potential + buttons with: ${selector}`);
                        
                        const button = buttons[0];
                        button.click();
                        
                        results.push(`✅ SUCCESS: Button clicked programmatically!`);
                        results.push(`   - Element: ${button.tagName}.${button.className}`);
                        results.push(`   - Text: "${button.textContent.trim()}"`);
                        results.push(`   - Click event dispatched successfully`);
                        return results.join('\\n');
                    }
                }
                
                results.push('❌ FAILED: No add/+ buttons found');
                results.push('But iframe DOM access is working (CORS not the issue)');
                
                // Fallback: show available buttons
                const allButtons = iframeDoc.querySelectorAll('button');
                results.push(`\\nFound ${allButtons.length} total buttons in MultiQC:`);
                Array.from(allButtons).slice(0, 5).forEach((btn, i) => {
                    results.push(`  [${i}] "${btn.textContent.trim()}" (${btn.className})`);
                });
                
                return results.join('\\n');
                
            } else if (triggered_id === 'simulate-apply-btn') {
                // SIMULATE APPLY BUTTON CLICK (handle disabled state)
                const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                
                if (applyButton) {
                    // Check if button is enabled
                    const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                    
                    // Force enable the button if disabled
                    if (wasDisabled) {
                        applyButton.disabled = false;
                        applyButton.removeAttribute('disabled');
                        applyButton.classList.remove('disabled');
                    }
                    
                    applyButton.click();
                    
                    return originStatus +
                           `✅ SUCCESS: Apply button clicked!\\n` +
                           `   - Button: #mqc_cols_apply\\n` +
                           `   - Was disabled: ${wasDisabled} ${wasDisabled ? '(force enabled)' : ''}\\n` +
                           `   - Current state: ${applyButton.disabled ? 'disabled' : 'enabled'}\\n` +
                           `   - Button text: "${applyButton.textContent}"\\n` +
                           `   - Click event dispatched successfully`;
                } else {
                    return originStatus + 
                           '❌ FAILED: Could not find #mqc_cols_apply button\\n' +
                           'But iframe DOM access is working (CORS not the issue)';
                }
                
            } else if (triggered_id === 'clear-highlights-btn') {
                // CLEAR HIGHLIGHTS + APPLY FUNCTIONALITY
                let results = [originStatus + '=== 🗑️ CLEAR HIGHLIGHTS + APPLY SEQUENCE ===\\n'];
                
                // Step 1: Click Clear Button
                const clearButton = iframeDoc.querySelector('.mqc_toolbox_clear');
                if (!clearButton) {
                    return originStatus + '❌ STEP 1 FAILED: Could not find .mqc_toolbox_clear button';
                }
                
                clearButton.click();
                results.push('✅ STEP 1: Clear button clicked (trash icon)');
                
                // Step 2: Clear input field for good measure
                const input = iframeDoc.querySelector('#mqc_colour_filter');
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    results.push('✅ STEP 2: Input field cleared');
                }
                
                // Small delay before apply
                setTimeout(() => {}, 100);
                
                // Step 3: Click Apply Button (force enable if needed)
                const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                if (!applyButton) {
                    results.push('❌ STEP 3 FAILED: Could not find Apply button (#mqc_cols_apply)');
                    return results.join('\\n');
                }
                
                const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                if (wasDisabled) {
                    applyButton.disabled = false;
                    applyButton.removeAttribute('disabled');
                    applyButton.classList.remove('disabled');
                }
                
                applyButton.click();
                results.push(`✅ STEP 3: Apply button clicked ${wasDisabled ? '(was disabled, force enabled)' : '(was enabled)'}`);
                
                results.push('\\n🎉 CLEAR + APPLY COMPLETE!');
                results.push('   → All highlights should now be removed from MultiQC charts');
                results.push('   → Charts should return to their original state');
                
                return results.join('\\n');
                
            } else if (triggered_id === 'full-automation-btn') {
                // FULL SEQUENTIAL AUTOMATION: Pattern → + → Apply
                let results = [originStatus + '=== 🚀 FULL MULTIQC AUTOMATION SEQUENCE ===\\n'];
                
                // Step 1: Set Custom Pattern
                const input = iframeDoc.querySelector('#mqc_colour_filter');
                if (!input) {
                    return originStatus + '❌ STEP 1 FAILED: Could not find #mqc_colour_filter input';
                }
                
                input.value = '';
                input.value = '00050101';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('keyup', { bubbles: true }));
                results.push('✅ STEP 1: Custom Pattern set to "00050101"');
                
                // Small delay to let MultiQC process
                setTimeout(() => {}, 100);
                
                // Step 2: Click + Button
                const plusButton = iframeDoc.querySelector('#mqc_colour_filter_update');
                if (!plusButton) {
                    results.push('❌ STEP 2 FAILED: Could not find + button (#mqc_colour_filter_update)');
                    return results.join('\\n');
                }
                
                plusButton.click();
                results.push('✅ STEP 2: + Button clicked successfully');
                
                // Small delay before apply
                setTimeout(() => {}, 100);
                
                // Step 3: Click Apply Button (force enable if needed)
                const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                if (!applyButton) {
                    results.push('❌ STEP 3 FAILED: Could not find Apply button (#mqc_cols_apply)');
                    return results.join('\\n');
                }
                
                const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                if (wasDisabled) {
                    applyButton.disabled = false;
                    applyButton.removeAttribute('disabled');
                    applyButton.classList.remove('disabled');
                }
                
                applyButton.click();
                results.push(`✅ STEP 3: Apply button clicked ${wasDisabled ? '(was disabled, force enabled)' : '(was enabled)'}`);
                
                results.push('\\n🎉 FULL AUTOMATION COMPLETE!');
                results.push('   → Sample "00050101" should now be highlighted in MultiQC charts');
                results.push('   → Check the MultiQC report to see the visual changes');
                
                return results.join('\\n');
                
            } else if (triggered_id === 'show-only-sample-btn') {
                // SHOW ONLY SAMPLES AUTOMATION: Set radio → Pattern → + → Apply
                let results = [originStatus + '=== 👁️ SHOW ONLY SAMPLE AUTOMATION ===\\n'];
                
                // Step 1: Select "Show only matching samples" radio button
                const showRadio = iframeDoc.querySelector('input[value="show"].mqc_hidesamples_showhide');
                if (!showRadio) {
                    return originStatus + '❌ STEP 1 FAILED: Could not find "show only" radio button';
                }
                
                showRadio.checked = true;
                showRadio.dispatchEvent(new Event('change', { bubbles: true }));
                results.push('✅ STEP 1: Selected "Show only matching samples"');
                
                // Step 2: Set the hide/show filter input
                const hideInput = iframeDoc.querySelector('#mqc_hidesamples_filter');
                if (!hideInput) {
                    return originStatus + '❌ STEP 2 FAILED: Could not find #mqc_hidesamples_filter input';
                }
                
                hideInput.value = '';
                hideInput.value = '00050101';
                hideInput.dispatchEvent(new Event('input', { bubbles: true }));
                hideInput.dispatchEvent(new Event('change', { bubbles: true }));
                results.push('✅ STEP 2: Set pattern "00050101" in hide/show filter');
                
                // Step 3: Click the + button for hide/show
                const hidePlusButton = iframeDoc.querySelector('#mqc_hidesamples_filter_update');
                if (!hidePlusButton) {
                    results.push('❌ STEP 3 FAILED: Could not find + button (#mqc_hidesamples_filter_update)');
                    return results.join('\\n');
                }
                
                hidePlusButton.click();
                results.push('✅ STEP 3: + Button clicked for hide/show filter');
                
                // Step 4: Click Apply Button (force enable if needed)
                const applyButton = iframeDoc.querySelector('#mqc_hide_apply');
                if (!applyButton) {
                    results.push('❌ STEP 4 FAILED: Could not find Apply button (#mqc_hide_apply)');
                    return results.join('\\n');
                }
                
                const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                if (wasDisabled) {
                    applyButton.disabled = false;
                    applyButton.removeAttribute('disabled');
                    applyButton.classList.remove('disabled');
                }
                
                applyButton.click();
                results.push(`✅ STEP 4: Apply button clicked ${wasDisabled ? '(was disabled, force enabled)' : '(was enabled)'}`);
                
                results.push('\\n🎉 SHOW ONLY AUTOMATION COMPLETE!');
                results.push('   → Only sample "00050101" should now be visible in MultiQC charts');
                results.push('   → All other samples should be hidden');
                
                return results.join('\\n');
                
            } else if (triggered_id === 'highlight-pattern-input' && triggered_prop === 'value') {
                // AUTO HIGHLIGHT AUTOMATION - triggered by TagsInput changes
                let results = [originStatus + '=== 🎨 AUTO HIGHLIGHT AUTOMATION ===\\n'];
                
                // Get patterns from TagsInput (returns array) - with null/undefined safety
                const patterns = (highlight_pattern && Array.isArray(highlight_pattern) && highlight_pattern.length > 0) ? highlight_pattern : [];
                
                if (patterns.length === 0) {
                    // Clear highlights when TagsInput is emptied
                    const clearButton = iframeDoc.querySelector('.mqc_toolbox_clear');
                    if (clearButton) {
                        clearButton.click();
                        const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                        if (applyButton) {
                            const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                            if (wasDisabled) {
                                applyButton.disabled = false;
                                applyButton.removeAttribute('disabled');
                                applyButton.classList.remove('disabled');
                            }
                            applyButton.click();
                        }
                        return originStatus + '🗑️ AUTO CLEAR: Removed all highlights (TagsInput emptied)';
                    }
                    return originStatus + '📝 TagsInput cleared but no clear button found';
                }
                
                const pattern = patterns.join('|'); // Join multiple patterns with OR for regex
                results.push(`Patterns: [${patterns.join(', ')}]`);
                results.push(`Combined Pattern: "${pattern}"`);
                results.push(`Use Regex: ${highlight_regex ? 'Yes' : 'No'}`);
                results.push(`Trigger: TagsInput value change`);
                
                // Step 1: Set Custom Pattern
                const input = iframeDoc.querySelector('#mqc_colour_filter');
                if (!input) {
                    return originStatus + '❌ STEP 1 FAILED: Could not find #mqc_colour_filter input';
                }
                
                input.value = '';
                input.value = pattern;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('keyup', { bubbles: true }));
                results.push(`✅ STEP 1: Pattern set to "${pattern}"`);
                
                // Step 1.5: Set Regex Mode (MultiQC custom switch)
                const regexSwitch = iframeDoc.querySelector('.mqc_switch_wrapper[data-target="mqc_cols"] .mqc_switch');
                if (regexSwitch) {
                    const isCurrentlyOn = regexSwitch.classList.contains('on');
                    const shouldBeOn = highlight_regex || false;
                    
                    if (isCurrentlyOn !== shouldBeOn) {
                        // Click to toggle the switch
                        regexSwitch.click();
                        results.push(`✅ STEP 1.5: Highlight regex ${shouldBeOn ? 'enabled' : 'disabled'} (toggled)`);
                    } else {
                        results.push(`✅ STEP 1.5: Highlight regex already ${shouldBeOn ? 'enabled' : 'disabled'} (no change needed)`);
                    }
                } else {
                    results.push('⚠️ STEP 1.5: Highlight regex switch not found (selector: .mqc_switch_wrapper[data-target="mqc_cols"] .mqc_switch)');
                }
                
                // Step 2: Click + Button
                const plusButton = iframeDoc.querySelector('#mqc_colour_filter_update');
                if (!plusButton) {
                    results.push('❌ STEP 2 FAILED: Could not find + button (#mqc_colour_filter_update)');
                    return results.join('\\n');
                }
                
                plusButton.click();
                results.push('✅ STEP 2: + Button clicked');
                
                // Step 3: Auto-Apply
                const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                if (!applyButton) {
                    results.push('❌ STEP 3 FAILED: Could not find Apply button (#mqc_cols_apply)');
                    return results.join('\\n');
                }
                
                const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                if (wasDisabled) {
                    applyButton.disabled = false;
                    applyButton.removeAttribute('disabled');
                    applyButton.classList.remove('disabled');
                }
                
                applyButton.click();
                results.push(`✅ STEP 3: Auto-applied ${wasDisabled ? '(force enabled)' : ''}`);
                
                results.push('\\n🎉 AUTO HIGHLIGHT COMPLETE!');
                results.push(`   → Pattern "${pattern}" automatically applied to MultiQC charts`);
                
                return results.join('\\n');
                
            } else if (triggered_id === 'highlight-clear-btn') {
                // HIGHLIGHT CLEAR ALL AUTOMATION
                let results = [originStatus + '=== 🗑️ HIGHLIGHT CLEAR ALL ===\\n'];
                
                const clearButton = iframeDoc.querySelector('.mqc_toolbox_clear');
                if (!clearButton) {
                    return originStatus + '❌ FAILED: Could not find .mqc_toolbox_clear button';
                }
                
                clearButton.click();
                results.push('✅ STEP 1: Clear button clicked');
                
                // Clear input field
                const input = iframeDoc.querySelector('#mqc_colour_filter');
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    results.push('✅ STEP 2: Input field cleared');
                }
                
                // Apply changes
                const applyButton = iframeDoc.querySelector('#mqc_cols_apply');
                if (applyButton) {
                    const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                    if (wasDisabled) {
                        applyButton.disabled = false;
                        applyButton.removeAttribute('disabled');
                        applyButton.classList.remove('disabled');
                    }
                    
                    applyButton.click();
                    results.push(`✅ STEP 3: Apply clicked ${wasDisabled ? '(force enabled)' : ''}`);
                }
                
                results.push('\\n🎉 HIGHLIGHT CLEAR COMPLETE!');
                return results.join('\\n');
                
                
            } else if (triggered_id === 'showhide-pattern-input' && triggered_prop === 'value') {
                // AUTO SHOW/HIDE AUTOMATION - triggered by TagsInput changes
                let results = [originStatus + '=== 👁️ AUTO SHOW/HIDE AUTOMATION ===\\n'];
                
                const patterns = (showhide_pattern && Array.isArray(showhide_pattern) && showhide_pattern.length > 0) ? showhide_pattern : [];
                const mode = showhide_mode || 'show';
                
                if (patterns.length === 0) {
                    // Clear show/hide filters when TagsInput is emptied
                    let clearResults = [originStatus + '🗑️ AUTO CLEAR SHOW/HIDE FILTERS'];
                    
                    // CRITICAL: If in "show" mode, switch to "hide" mode first
                    // Otherwise all samples will be hidden when filters are cleared
                    if (mode === 'show') {
                        const hideRadio = iframeDoc.querySelector('input[value="hide"].mqc_hidesamples_showhide');
                        if (hideRadio) {
                            hideRadio.checked = true;
                            hideRadio.dispatchEvent(new Event('change', { bubbles: true }));
                            clearResults.push('✅ STEP 1: Switched from "Show Only" to "Hide" mode (prevents all samples being hidden)');
                        }
                    }
                    
                    const clearButton = iframeDoc.querySelector('#mqc_hidesamples .mqc_toolbox_clear');
                    if (clearButton) {
                        clearButton.click();
                        clearResults.push('✅ STEP 2: Clear button clicked');
                        
                        const applyButton = iframeDoc.querySelector('#mqc_hide_apply');
                        if (applyButton) {
                            const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                            if (wasDisabled) {
                                applyButton.disabled = false;
                                applyButton.removeAttribute('disabled');
                                applyButton.classList.remove('disabled');
                            }
                            applyButton.click();
                            clearResults.push(`✅ STEP 3: Apply clicked ${wasDisabled ? '(force enabled)' : ''}`);
                        }
                        
                        clearResults.push('\\n🎉 AUTO CLEAR COMPLETE!');
                        clearResults.push('   → All show/hide filters removed');
                        clearResults.push('   → Mode set to "Hide" (all samples visible)');
                        
                        return clearResults.join('\\n');
                    }
                    return originStatus + '📝 Show/Hide TagsInput cleared but no clear button found';
                }
                
                const pattern = patterns.join('|'); // Join multiple patterns with OR for regex
                results.push(`Patterns: [${patterns.join(', ')}]`);
                results.push(`Combined Pattern: "${pattern}"`);
                results.push(`Mode: ${mode === 'show' ? '👁️ Show Only' : '🙈 Hide'}`);
                results.push(`Use Regex: ${showhide_regex ? 'Yes' : 'No'}`);
                results.push(`Trigger: TagsInput value change`);
                
                // Step 1: Select radio button
                const radioValue = mode === 'show' ? 'show' : 'hide';
                const radio = iframeDoc.querySelector(`input[value="${radioValue}"].mqc_hidesamples_showhide`);
                if (!radio) {
                    return originStatus + `❌ STEP 1 FAILED: Could not find "${radioValue}" radio button`;
                }
                
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                results.push(`✅ STEP 1: Selected "${mode === 'show' ? 'Show only' : 'Hide'}" mode`);
                
                // Step 2: Set pattern
                const hideInput = iframeDoc.querySelector('#mqc_hidesamples_filter');
                if (!hideInput) {
                    return originStatus + '❌ STEP 2 FAILED: Could not find #mqc_hidesamples_filter input';
                }
                
                hideInput.value = '';
                hideInput.value = pattern;
                hideInput.dispatchEvent(new Event('input', { bubbles: true }));
                hideInput.dispatchEvent(new Event('change', { bubbles: true }));
                results.push(`✅ STEP 2: Pattern set to "${pattern}"`);
                
                // Step 2.5: Set Regex Mode for Show/Hide (MultiQC custom switch)
                const hideRegexSwitch = iframeDoc.querySelector('.mqc_switch_wrapper[data-target="mqc_hidesamples"] .mqc_switch');
                if (hideRegexSwitch) {
                    const isCurrentlyOn = hideRegexSwitch.classList.contains('on');
                    const shouldBeOn = showhide_regex || false;
                    
                    if (isCurrentlyOn !== shouldBeOn) {
                        // Click to toggle the switch
                        hideRegexSwitch.click();
                        results.push(`✅ STEP 2.5: Show/Hide regex ${shouldBeOn ? 'enabled' : 'disabled'} (toggled)`);
                    } else {
                        results.push(`✅ STEP 2.5: Show/Hide regex already ${shouldBeOn ? 'enabled' : 'disabled'} (no change needed)`);
                    }
                } else {
                    results.push('⚠️ STEP 2.5: Show/Hide regex switch not found (selector: .mqc_switch_wrapper[data-target="mqc_hidesamples"] .mqc_switch)');
                }
                
                // Step 3: Click + button
                const hidePlusButton = iframeDoc.querySelector('#mqc_hidesamples_filter_update');
                if (!hidePlusButton) {
                    results.push('❌ STEP 3 FAILED: Could not find + button (#mqc_hidesamples_filter_update)');
                    return results.join('\\n');
                }
                
                hidePlusButton.click();
                results.push('✅ STEP 3: + Button clicked');
                
                // Step 4: Auto-Apply
                const applyButton = iframeDoc.querySelector('#mqc_hide_apply');
                if (!applyButton) {
                    results.push('❌ STEP 4 FAILED: Could not find Apply button (#mqc_hide_apply)');
                    return results.join('\\n');
                }
                
                const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                if (wasDisabled) {
                    applyButton.disabled = false;
                    applyButton.removeAttribute('disabled');
                    applyButton.classList.remove('disabled');
                }
                
                applyButton.click();
                results.push(`✅ STEP 4: Auto-applied ${wasDisabled ? '(force enabled)' : ''}`);
                
                results.push('\\n🎉 AUTO SHOW/HIDE COMPLETE!');
                results.push(`   → Pattern "${pattern}" with mode "${mode}" automatically applied`);
                
                return results.join('\\n');
                
            } else if (triggered_id === 'showhide-clear-btn') {
                // SHOW/HIDE CLEAR ALL AUTOMATION
                let results = [originStatus + '=== 🗑️ SHOW/HIDE CLEAR ALL ===\\n'];
                
                // CRITICAL: Switch to "hide" mode first if currently in "show" mode
                // This prevents all samples from being hidden after clearing filters
                const currentMode = showhide_mode || 'show';
                if (currentMode === 'show') {
                    const hideRadio = iframeDoc.querySelector('input[value="hide"].mqc_hidesamples_showhide');
                    if (hideRadio) {
                        hideRadio.checked = true;
                        hideRadio.dispatchEvent(new Event('change', { bubbles: true }));
                        results.push('✅ STEP 1: Switched from "Show Only" to "Hide" mode');
                    }
                }
                
                const clearButton = iframeDoc.querySelector('#mqc_hidesamples .mqc_toolbox_clear');
                if (!clearButton) {
                    return originStatus + '❌ FAILED: Could not find show/hide clear button';
                }
                
                clearButton.click();
                results.push('✅ STEP 2: Clear button clicked');
                
                // Clear input
                const input = iframeDoc.querySelector('#mqc_hidesamples_filter');
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    results.push('✅ STEP 2: Input field cleared');
                }
                
                // Apply
                const applyButton = iframeDoc.querySelector('#mqc_hide_apply');
                if (applyButton) {
                    const wasDisabled = applyButton.disabled || applyButton.hasAttribute('disabled');
                    if (wasDisabled) {
                        applyButton.disabled = false;
                        applyButton.removeAttribute('disabled');
                        applyButton.classList.remove('disabled');
                    }
                    
                    applyButton.click();
                    results.push(`✅ STEP 3: Apply clicked ${wasDisabled ? '(force enabled)' : ''}`);
                }
                
                results.push('\\n🎉 SHOW/HIDE CLEAR COMPLETE!');
                return results.join('\\n');
            }
            
            // Note: Old clear element button logic removed - now handled automatically by TagsInput
            
        } catch (error) {
            return `❌ ERROR: ${error.name}: ${error.message}\\n\\n` +
                   `This error suggests: ${error.name === 'SecurityError' ? 
                       'CORS/Same-Origin Policy blocking access' : 
                       'Technical issue - not necessarily CORS'}\\n\\n` +
                   `Error details:\\n${error.stack ? error.stack.split('\\n')[0] : 'No stack trace'}`;
        }
        
        return '❓ Unknown button triggered';
    }
    """,
    Output('investigation-output', 'children'),
    [# Debug buttons - Inputs
     Input('inspect-highlight-btn', 'n_clicks'),
     Input('test-sample-input-btn', 'n_clicks'),
     Input('simulate-plus-btn', 'n_clicks'),
     Input('simulate-apply-btn', 'n_clicks'),
     Input('simulate-enter-btn', 'n_clicks'),
     # Clear buttons - Inputs
     Input('highlight-clear-btn', 'n_clicks'),
     Input('showhide-clear-btn', 'n_clicks'),
     # Automatic triggers on dropdown changes - Inputs
     Input('highlight-pattern-input', 'value'),
     Input('showhide-pattern-input', 'value')],
    [# All States (for configuration)
     State('highlight-regex-switch', 'checked'),
     State('showhide-regex-switch', 'checked'),
     State('showhide-mode-control', 'value')]
)

if __name__ == '__main__':
    print("🚀 Starting minimal dash-dock + MultiQC test...")
    print("📍 http://localhost:8054")
    print("🔧 Test Flask: http://localhost:8054/test")
    print("📊 Test MultiQC: http://localhost:8054/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html")
    print("\n🧪 CRITICAL TEST: Checking if iframe access is blocked by CORS")
    print("   - If buttons show 'SAME-ORIGIN ACCESS CONFIRMED' → No CORS issues")
    print("   - If buttons show 'CORS BLOCKED' → CORS is the problem")
    app.run(debug=True, port=8054)