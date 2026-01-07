/**
 * Paste this into browser console to check if Dash knows about the components
 */

console.log("=".repeat(80));
console.log("🔍 DASH COMPONENT REGISTRY DIAGNOSTIC");
console.log("=".repeat(80));

// Check if Dash is loaded
if (typeof window.dash_clientside === 'undefined') {
    console.log("❌ Dash is not loaded!");
} else {
    console.log("✅ Dash is loaded");
}

// Check for the Store
const store = document.getElementById('interactive-values-store');
if (store) {
    console.log("\n✅ interactive-values-store EXISTS in DOM");
    console.log("   Current data:", store.textContent || '(empty)');
} else {
    console.log("\n❌ interactive-values-store NOT FOUND in DOM");
}

// Find all components with interactive-component-value in ID
const allElements = document.querySelectorAll('[id]');
const interactiveComponents = [];

allElements.forEach(el => {
    const id = el.id;
    if (id.includes('interactive-component-value')) {
        interactiveComponents.push(el);
    }
});

console.log(`\n📊 Found ${interactiveComponents.length} elements with 'interactive-component-value' in ID:`);

if (interactiveComponents.length === 0) {
    console.log("❌ NO INTERACTIVE COMPONENTS FOUND!");
    console.log("   This means the async callback isn't creating components with the right IDs");
} else {
    interactiveComponents.forEach((el, idx) => {
        console.log(`\n  ${idx + 1}. ID: ${el.id}`);
        console.log(`     Tag: ${el.tagName}`);
        console.log(`     Classes: ${el.className}`);

        // Try to parse the ID as JSON
        try {
            const idObj = JSON.parse(el.id);
            console.log(`     Parsed ID:`, idObj);
        } catch (e) {
            console.log(`     ID is not JSON`);
        }

        // Check if it has a value property
        if ('value' in el) {
            console.log(`     ✅ Has 'value' property: ${el.value}`);
        } else {
            console.log(`     ❌ No 'value' property`);
        }

        // Check if it's a Mantine component
        const mantiineEl = el.querySelector('[class*="mantine"]');
        if (mantiineEl) {
            console.log(`     Mantine component inside`);
        }
    });
}

// Check if there are any Select/Slider components
console.log("\n📋 Searching for DMC components:");
const selects = document.querySelectorAll('[class*="mantine"][class*="Select"]');
const sliders = document.querySelectorAll('[class*="mantine"][class*="Slider"]');

console.log(`   Found ${selects.length} DMC Select components`);
console.log(`   Found ${sliders.length} DMC Slider components`);

if (selects.length > 0) {
    console.log("\n   Select component IDs:");
    selects.forEach((sel, idx) => {
        // Walk up the tree to find the parent with an ID
        let parent = sel;
        while (parent && !parent.id) {
            parent = parent.parentElement;
        }
        console.log(`     ${idx + 1}. Parent ID: ${parent ? parent.id : 'NO ID'}`);
    });
}

console.log("\n" + "=".repeat(80));
console.log("✅ Diagnostic complete!");
console.log("=".repeat(80));
