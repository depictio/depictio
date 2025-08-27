// Dash-dock fullscreen functionality module
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    dashDock: {
        injectFullscreenButton: function(n_intervals) {
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
                    
                    // Create simple expand icon - much cleaner
                    fullscreenBtn.innerHTML = `
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                            <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                        </svg>
                    `;
                    
                    // Add click handler for viewport expand toggle
                    window.dashDockFullscreen = window.dashDockFullscreen || {};
                    window.dashDockFullscreen.isExpanded = false;
                    window.dashDockFullscreen.originalStyles = {};
                    
                    fullscreenBtn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        window.dash_clientside.dashDock.toggleFullscreen();
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
        },

        toggleFullscreen: function() {
            const container = document.getElementById('dock-container');
            const body = document.body;
            const fullscreenBtn = document.getElementById('custom-fullscreen-btn');
            
            if (!window.dashDockFullscreen.isExpanded) {
                // Store original styles
                window.dashDockFullscreen.originalStyles = {
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
                
                window.dashDockFullscreen.isExpanded = true;
                fullscreenBtn.title = 'Restore to normal size';
                
                // Keep the same clean icon for both states
                fullscreenBtn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                        <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                    </svg>
                `;
            } else {
                // Restore original styles
                const originalStyles = window.dashDockFullscreen.originalStyles;
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
                
                window.dashDockFullscreen.isExpanded = false;
                fullscreenBtn.title = 'Expand to full browser window';
                
                // Change icon back to expand - simple and clean
                fullscreenBtn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="var(--color-icon)" style="width: 1em; height: 1em; display: flex; align-items: center;">
                        <path d="M2 2h6v2H4v4H2V2zm10 0h6v6h-2V4h-4V2zM2 18V12h2v4h4v2H2zm16 0h-6v-2h4v-4h2v6z"/>
                    </svg>
                `;
            }
        },

        setupEscapeKeyHandler: function() {
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    const fullscreenBtn = document.getElementById('custom-fullscreen-btn');
                    if (fullscreenBtn && window.dashDockFullscreen && window.dashDockFullscreen.isExpanded) {
                        window.dash_clientside.dashDock.toggleFullscreen();
                    }
                }
            });
            return 'ESC handler setup complete';
        }
    }
});