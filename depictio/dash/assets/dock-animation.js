// Dock-style Animation Initialization
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dock animation script loaded');

    // Function to initialize dock animations
    function initializeDockAnimations() {
        const dockContainer = document.getElementById('component-dock-container');
        if (dockContainer) {
            console.log('Dock container found, applying animations');

            // Add hover events for adjacent button effects
            const buttons = dockContainer.querySelectorAll('button, [data-button], [class*="Button"]');
            console.log('Found buttons:', buttons.length);

            buttons.forEach((button, index) => {
                button.addEventListener('mouseenter', function() {
                    console.log('Button hover enter:', index);

                    // Reset all buttons first
                    buttons.forEach(btn => {
                        if (btn !== button) {
                            btn.style.transform = '';
                            btn.classList.remove('dock-adjacent');
                        }
                    });

                    // Scale adjacent buttons symmetrically for centered dock effect
                    if (buttons[index - 1]) {
                        buttons[index - 1].style.transform = 'scale(1.02)';
                        buttons[index - 1].classList.add('dock-adjacent');
                    }
                    if (buttons[index + 1]) {
                        buttons[index + 1].style.transform = 'scale(1.02)';
                        buttons[index + 1].classList.add('dock-adjacent');
                    }

                    // Add class to current button for potential additional styling
                    button.classList.add('dock-active');
                });

                button.addEventListener('mouseleave', function() {
                    console.log('Button hover leave:', index);

                    // Reset all buttons to default state
                    buttons.forEach(btn => {
                        btn.style.transform = '';
                        btn.classList.remove('dock-adjacent', 'dock-active');
                    });
                });
            });
        } else {
            console.log('Dock container not found, retrying in 500ms');
            setTimeout(initializeDockAnimations, 500);
        }
    }

    // Initialize animations
    initializeDockAnimations();

    // Re-initialize when new components are added (for dynamic content)
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'childList') {
                const dockContainer = document.getElementById('component-dock-container');
                if (dockContainer && mutation.target.contains(dockContainer)) {
                    setTimeout(initializeDockAnimations, 100);
                }
            }
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
});
