document.addEventListener('DOMContentLoaded', function () {
    var cy = window.cy = cytoscape({
        container: document.getElementById('cytoscape-graph'),
        /* other graph parameters */
    });

    cy.on('tap', 'node', function (evt) {
        var node = evt.target;
        var href = node.data('href');
        window.open(href, '_blank');
    });
});
