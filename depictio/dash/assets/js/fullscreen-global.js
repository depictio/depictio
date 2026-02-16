// Exit fullscreen mode when ESC is pressed.
// Loaded automatically by Dash from the assets folder.
document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;

    var fullscreenItem = document.querySelector('.chart-fullscreen-active');
    if (!fullscreenItem) return;

    fullscreenItem.classList.remove('chart-fullscreen-active');
    document.body.classList.remove('fullscreen-mode');

    // Resize Plotly chart after the layout change settles
    setTimeout(function () {
        var plotlyDiv = fullscreenItem.querySelector('.js-plotly-plot');
        if (plotlyDiv && window.Plotly) {
            window.Plotly.Plots.resize(plotlyDiv);
        }
    }, 100);
});
