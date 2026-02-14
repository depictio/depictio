// Global fullscreen handlers
// This file is automatically loaded by Dash from the assets folder

// ESC key to exit fullscreen
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const fullscreenItem = document.querySelector('.chart-fullscreen-active');
        if (fullscreenItem) {
            console.log('🖥️ ESC pressed, exiting fullscreen');
            fullscreenItem.classList.remove('chart-fullscreen-active');
            document.body.classList.remove('fullscreen-mode');

            // Resize Plotly after exiting
            setTimeout(() => {
                const plotlyDiv = fullscreenItem.querySelector('.js-plotly-plot');
                if (plotlyDiv && window.Plotly) {
                    window.Plotly.Plots.resize(plotlyDiv);
                }
            }, 100);
        }
    }
});
