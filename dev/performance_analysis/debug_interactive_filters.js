/**
 * Debug script for interactive filter issue
 *
 * Paste this into the browser console to diagnose why filters aren't triggering
 */

console.log("=".repeat(80));
console.log("🔍 INTERACTIVE FILTER DIAGNOSTIC");
console.log("=".repeat(80));

// 1. Find all interactive components
const interactiveComponents = document.querySelectorAll('[id*="interactive-component-value"]');
console.log(`\n📊 Found ${interactiveComponents.length} interactive components:`);

interactiveComponents.forEach((el, idx) => {
    try {
        const idStr = el.id;
        const idObj = JSON.parse(idStr);
        console.log(`\n  ${idx + 1}. Type: ${idObj.type}, Index: ${idObj.index}`);
        console.log(`     Tag: ${el.tagName}`);
        console.log(`     Class: ${el.className}`);
        console.log(`     Has value property: ${el.value !== undefined}`);

        // Check if it's a DMC component
        const dmc = el.querySelector('[class*="mantine"]');
        if (dmc) {
            console.log(`     DMC component detected: ${dmc.className.split(' ')[0]}`);
        }

        // Check parent structure
        console.log(`     Parent ID: ${el.parentElement?.id || 'none'}`);
    } catch (e) {
        console.log(`  ${idx + 1}. ID: ${el.id} (not JSON parseable)`);
    }
});

// 2. Check the Store callback exists
console.log("\n📦 Checking for Store callback...");
if (window.dash_clientside) {
    console.log("✅ dash_clientside is available");
} else {
    console.log("❌ dash_clientside is NOT available");
}

// 3. Check interactive-values-store
const store = document.getElementById('interactive-values-store');
if (store) {
    console.log("\n✅ interactive-values-store exists");
    try {
        const storeData = JSON.parse(store.textContent || '{}');
        console.log(`   Store data:`, storeData);
    } catch (e) {
        console.log("   Store data: (empty or invalid JSON)");
    }
} else {
    console.log("\n❌ interactive-values-store NOT FOUND");
}

// 4. Monitor for value changes
console.log("\n👀 Setting up value change monitor...");
console.log("   Try changing a filter now and watch the console!");

interactiveComponents.forEach((el, idx) => {
    el.addEventListener('change', (e) => {
        console.log(`\n🎯 VALUE CHANGED on component ${idx + 1}!`);
        console.log(`   ID: ${el.id}`);
        console.log(`   New value: ${e.target.value}`);
    });

    // Also monitor input events (for text inputs)
    el.addEventListener('input', (e) => {
        console.log(`\n🎯 INPUT EVENT on component ${idx + 1}!`);
        console.log(`   ID: ${el.id}`);
        console.log(`   New value: ${e.target.value}`);
    });
});

console.log("\n" + "=".repeat(80));
console.log("✅ Diagnostic complete! Now try changing a filter.");
console.log("=".repeat(80));
