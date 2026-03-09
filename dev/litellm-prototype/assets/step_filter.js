/**
 * Clientside callback: filter execution trace steps by status.
 * Listens to the chip-group value and hides/shows accordion items.
 */
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    step_filter: {
        filter_steps: function(filterValue) {
            // Small delay to let DOM render
            setTimeout(function() {
                var items = document.querySelectorAll('[data-step-status]');
                items.forEach(function(item) {
                    var status = item.getAttribute('data-step-status');
                    if (filterValue === 'all') {
                        item.style.display = '';
                    } else if (filterValue === 'errors') {
                        item.style.display = (status === 'error' || status === 'warning') ? '' : 'none';
                    } else if (filterValue === 'code') {
                        item.style.display = (status === 'success') ? '' : 'none';
                    }
                });
            }, 50);
            // Return empty div (no-op output)
            return '';
        }
    }
});
