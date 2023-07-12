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

window.myNamespace = Object.assign({}, window.myNamespace, {  
    mySubNamespace: {  
        pointToLayer: function(feature, latlng, context) {  
            return L.circleMarker(latlng)  
        }  
    }  
});