#!/usr/bin/env python3
"""
Mantine AppShell Debug Prototype

Find the correct selector for dashboard content in Mantine AppShell.
Uses authentication from depictio/.depictio/admin_config.yaml file.
"""

import asyncio
import json
import yaml
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# Configuration - UPDATE THESE VALUES
DASHBOARD_ID = "6824cb3b89d2b72169309737"
DASH_PORT = 5080  # Your actual dash frontend port
API_PORT = 8058   # Your API backend port

DASHBOARD_URL = f"http://localhost:{DASH_PORT}/dashboard/{DASHBOARD_ID}"
BASE_URL = f"http://localhost:{DASH_PORT}"
API_BASE_URL = f"http://localhost:{API_PORT}"
OUTPUT_DIR = Path(__file__).parent / "screenshots"
OUTPUT_DIR.mkdir(exist_ok=True)

# Path to admin config file
ADMIN_CONFIG_PATH = Path(__file__).parent.parent.parent / "depictio" / ".depictio" / "admin_config.yaml"

print(f"📍 Configuration:")
print(f"   Dashboard URL: {DASHBOARD_URL}")
print(f"   Base URL: {BASE_URL}")
print(f"   API URL: {API_BASE_URL}")
print(f"   Admin config: {ADMIN_CONFIG_PATH}")
print()


async def get_auth_from_config():
    """
    Get authentication data from the admin_config.yaml file
    """
    print("🔐 Reading authentication from admin_config.yaml...")
    
    try:
        if not ADMIN_CONFIG_PATH.exists():
            raise FileNotFoundError(f"Admin config file not found: {ADMIN_CONFIG_PATH}")
        
        with open(ADMIN_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        
        print("✅ Loaded admin config file")
        
        # Extract user and token information
        user_info = config.get('user', {})
        token_info = user_info.get('token', {})
        
        # Create token data in the format expected by localStorage (matching screenshot endpoint format)
        # This should match exactly what token.model_dump(exclude_none=True) produces
        token_data = {
            "_id": str(token_info.get('id')),
            "user_id": str(token_info.get('user_id')),
            "logged_in": True,
            "expire_datetime": token_info.get('expire_datetime'),
            "created_at": token_info.get('created_at'),
            "refresh_expire_datetime": token_info.get('refresh_expire_datetime'),
            "access_token": token_info.get('access_token'),
            "refresh_token": token_info.get('refresh_token'),
            "name": token_info.get('name'),
            "token_lifetime": token_info.get('token_lifetime'),
            "token_type": token_info.get('token_type'),
            # Include all fields from config to match model_dump output
            "description": token_info.get('description'),
            "flexible_metadata": token_info.get('flexible_metadata'),
            "hash": token_info.get('hash')
        }
        
        print("✅ Created token structure from config:")
        print(f"   User ID: {user_info.get('id')}")
        print(f"   Email: {user_info.get('email')}")
        print(f"   Admin: {user_info.get('is_admin')}")
        print(f"   Token expires: {token_info.get('expire_datetime')}")
        
        return token_data
        
    except Exception as e:
        print(f"❌ Could not load config file: {e}")
        print("❓ Fallback options:")
        print("   1. Check that admin_config.yaml exists")
        print("   2. Verify file permissions")
        print("   3. Use manual token entry")
        
        # Ask user for manual token as fallback
        print()
        print("🔧 MANUAL TOKEN OPTION:")
        print("   1. Open your dashboard in browser")
        print("   2. Open Developer Tools > Application > Local Storage")
        print("   3. Copy the 'local-store' value")
        print("   4. Paste it when prompted")
        print()
        
        manual_token = input("Paste your localStorage token (or press Enter to skip): ").strip()
        
        if manual_token:
            try:
                token_data = json.loads(manual_token)
                print("✅ Using manual token from browser")
                return token_data
            except Exception as parse_error:
                print(f"❌ Could not parse manual token: {parse_error}")
        
        print("🔐 Using fallback mock token (may not work)")
        return {
            "_id": "mock_id",
            "user_id": "mock_user",
            "logged_in": True,
            "expire_datetime": "2025-12-31 23:59:59",
            "created_at": "2025-01-01 00:00:00"
        }


async def analyze_page_structure(page):
    """
    Analyze the page structure to find Mantine AppShell elements
    """
    print("🔍 Analyzing page structure...")
    
    # Get all elements with Mantine-related classes
    mantine_elements = await page.evaluate("""
        () => {
            const elements = [];
            const allElements = document.querySelectorAll('*');
            
            allElements.forEach(el => {
                const classList = Array.from(el.classList);
                const mantineClasses = classList.filter(cls => 
                    cls.includes('mantine') || 
                    cls.includes('AppShell') ||
                    cls.includes('page-content') ||
                    el.id === 'page-content'
                );
                
                if (mantineClasses.length > 0 || el.id === 'page-content') {
                    const rect = el.getBoundingClientRect();
                    elements.push({
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        classes: classList,
                        mantineClasses: mantineClasses,
                        width: rect.width,
                        height: rect.height,
                        x: rect.x,
                        y: rect.y,
                        visible: el.offsetParent !== null,
                        children: el.children.length,
                        hasContent: el.textContent.trim().length > 100
                    });
                }
            });
            
            return elements.sort((a, b) => (b.width * b.height) - (a.width * a.height));
        }
    """)
    
    print("\n📊 Found Mantine/AppShell elements:")
    for i, el in enumerate(mantine_elements[:10]):  # Show top 10
        print(f"{i+1:2d}. {el['tag']}#{el['id']} - {el['mantineClasses']}")
        print(f"    Size: {el['width']:.0f}x{el['height']:.0f}, Visible: {el['visible']}, Children: {el['children']}")
        print(f"    Has content: {el['hasContent']}")
        print()
    
    return mantine_elements


async def test_selectors(page, selectors):
    """
    Test various selectors to find the best one for dashboard content
    """
    print("🎯 Testing selectors...")
    
    results = []
    
    for selector in selectors:
        try:
            print(f"\nTesting: {selector}")
            
            # Check if element exists
            element = await page.query_selector(selector)
            if not element:
                print(f"  ❌ Not found")
                continue
            
            # Get element info
            info = await page.evaluate(f"""
                (selector) => {{
                    const el = document.querySelector(selector);
                    if (!el) return null;
                    
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    
                    return {{
                        width: rect.width,
                        height: rect.height,
                        x: rect.x,
                        y: rect.y,
                        visible: el.offsetParent !== null,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        children: el.children.length,
                        textLength: el.textContent.trim().length,
                        classes: Array.from(el.classList),
                        id: el.id
                    }};
                }}
            """, selector)
            
            print(f"  📊 Size: {info['width']:.0f}x{info['height']:.0f}")
            print(f"  👁️  Visible: {info['visible']}, Display: {info['display']}")
            print(f"  📝 Children: {info['children']}, Text length: {info['textLength']}")
            print(f"  🏷️  ID: {info['id']}, Classes: {info['classes'][:3]}")
            
            # Score this selector - prioritize content areas without navbar/header
            score = 0
            if info['visible']: score += 10
            if info['width'] > 1000: score += 10
            if info['height'] > 500: score += 10
            if info['children'] > 5: score += 5
            if info['textLength'] > 100: score += 5
            
            # Heavy penalty for full viewport size (likely includes navbar/header)
            if info['width'] >= 1920 and info['height'] >= 1080:
                score -= 20
                print(f"  ⚠️  Full viewport penalty applied (-20 points)")
            
            # Bonus for content-specific dimensions (excluding navbar/header)
            if 1600 <= info['width'] <= 1800 and info['height'] > 100:
                score += 15
                print(f"  ✅  Content area bonus applied (+15 points)")
                
            # Bonus for dashboard-specific selectors
            if selector in ['#draggable', '.react-grid-layout', '#page-content']:
                score += 10
                print(f"  🎯  Dashboard content bonus applied (+10 points)")
            
            results.append({
                'selector': selector,
                'info': info,
                'score': score
            })
            
            print(f"  🎯 Score: {score}/40")
            
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:50]}")
    
    # Sort by score
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n🏆 Best selectors:")
    for i, result in enumerate(results[:5]):
        print(f"{i+1}. {result['selector']} (score: {result['score']})")
    
    return results


async def take_test_screenshots(page, best_selectors):
    """
    Take screenshots with the best selectors
    """
    print("\n📸 Taking test screenshots...")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Strategy 1: Screenshot individual dashboard components
    try:
        print("📸 Strategy 1: Finding and screenshotting individual dashboard components...")
        
        # Get all dashboard components
        components = await page.query_selector_all('.react-grid-item')
        print(f"   Found {len(components)} dashboard components")
        
        if components:
            for i, component in enumerate(components):
                try:
                    # Get component info
                    component_info = await component.bounding_box()
                    if component_info and component_info['width'] > 0 and component_info['height'] > 0:
                        component_file = OUTPUT_DIR / f"component_{i+1}_{timestamp}.png"
                        await component.screenshot(path=str(component_file))
                        print(f"   ✅ Component {i+1}: {component_file.name} ({component_info['width']:.0f}x{component_info['height']:.0f})")
                    else:
                        print(f"   ❌ Component {i+1}: Invalid dimensions")
                except Exception as e:
                    print(f"   ❌ Component {i+1}: Screenshot failed - {e}")
            
            # Try to create a composite view if multiple components exist
            if len(components) > 1:
                print("📸 Strategy 1b: Creating composite view of all components...")
                try:
                    # Create a temporary container to hold all components visually
                    composite_element = await page.evaluate("""
                        () => {
                            const components = document.querySelectorAll('.react-grid-item');
                            if (components.length === 0) return null;
                            
                            // Get bounding box of all components
                            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                            
                            components.forEach(component => {
                                const rect = component.getBoundingClientRect();
                                minX = Math.min(minX, rect.left);
                                minY = Math.min(minY, rect.top);
                                maxX = Math.max(maxX, rect.right);
                                maxY = Math.max(maxY, rect.bottom);
                            });
                            
                            // Create an invisible div that encompasses all components
                            const container = document.createElement('div');
                            container.id = 'temp-screenshot-container';
                            container.style.position = 'absolute';
                            container.style.left = minX + 'px';
                            container.style.top = minY + 'px';
                            container.style.width = (maxX - minX) + 'px';
                            container.style.height = (maxY - minY) + 'px';
                            container.style.pointerEvents = 'none';
                            container.style.border = '2px solid transparent';
                            container.style.zIndex = '-1';
                            
                            document.body.appendChild(container);
                            
                            return {
                                width: maxX - minX,
                                height: maxY - minY,
                                componentCount: components.length
                            };
                        }
                    """)
                    
                    if composite_element:
                        # Screenshot the temporary container
                        temp_container = await page.query_selector('#temp-screenshot-container')
                        if temp_container:
                            composite_file = OUTPUT_DIR / f"dashboard_composite_{timestamp}.png"
                            await temp_container.screenshot(path=str(composite_file))
                            print(f"   ✅ Composite view: {composite_file.name}")
                            print(f"   📐 Area: {composite_element['width']:.0f}x{composite_element['height']:.0f}")
                        
                        # Clean up the temporary element
                        await page.evaluate("document.getElementById('temp-screenshot-container')?.remove()")
                        
                except Exception as e:
                    print(f"   ❌ Composite screenshot failed: {e}")
        else:
            print("   ❌ No dashboard components found")
            
    except Exception as e:
        print(f"❌ Strategy 1 failed: {e}")
    
    # Strategy 2: Screenshot individual selectors (original approach)
    for i, result in enumerate(best_selectors[:3]):
        selector = result['selector']
        safe_name = selector.replace('#', '_').replace('.', '_').replace(' ', '_').replace('>', '_')
        output_file = OUTPUT_DIR / f"test_{timestamp}_{i+1}_{safe_name}.png"
        
        try:
            element = await page.query_selector(selector)
            if element:
                await element.screenshot(path=str(output_file))
                print(f"✅ Screenshot saved: {output_file.name}")
            else:
                print(f"❌ Element not found for {selector}")
        except Exception as e:
            print(f"❌ Screenshot failed for {selector}: {e}")
    
    # Also take a full page reference
    full_page_file = OUTPUT_DIR / f"fullpage_{timestamp}.png"
    await page.screenshot(path=str(full_page_file), full_page=True)
    print(f"📄 Full page reference: {full_page_file.name}")


async def main():
    """
    Main debug function
    """
    print("🚀 Mantine AppShell Debug Prototype")
    print(f"Target: {DASHBOARD_URL}")
    
    async with async_playwright() as p:
        # Launch browser with visible window for debugging
        browser = await p.chromium.launch(
            headless=False, 
            slow_mo=500,
            args=['--start-maximized']
        )
        
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            # Get auth token from config
            token_data = await get_auth_from_config()
            
            # Set up auth
            print("🔐 Setting up authentication...")
            await page.goto(BASE_URL)
            
            # Debug: Print what we're setting in localStorage
            token_json = json.dumps(token_data)
            print(f"🔍 Setting localStorage with: {token_json[:100]}...")
            
            await page.evaluate(f"localStorage.setItem('local-store', '{token_json}')")
            
            # Verify localStorage was set
            stored_data = await page.evaluate("localStorage.getItem('local-store')")
            print(f"🔍 Verified localStorage contains: {stored_data[:100] if stored_data else 'None'}...")
            
            # Navigate to dashboard
            print("🌐 Navigating to dashboard...")
            await page.goto(DASHBOARD_URL, timeout=30000)
            
            # Check current URL after navigation
            current_url = page.url
            print(f"🔍 Current URL after navigation: {current_url}")
            
            if "/auth" in current_url:
                print("❌ Redirected to auth page - authentication failed")
                print("🔍 Checking page content for auth modal...")
                
                # Check if auth modal is present
                auth_modal = await page.query_selector("#auth-modal-body")
                if auth_modal:
                    print("❌ Auth modal detected - token not valid")
                else:
                    print("🔍 No auth modal found")
            
            # Wait for page to load
            print("⏳ Waiting for page to load...")
            await page.wait_for_timeout(8000)
            
            # Wait specifically for dashboard content to render with proper dimensions
            print("⏳ Waiting for dashboard content to render...")
            try:
                # Wait for draggable content to have proper height
                await page.wait_for_function("""
                    () => {
                        const draggable = document.querySelector('#draggable');
                        const pageContent = document.querySelector('#page-content');
                        const gridLayout = document.querySelector('.react-grid-layout');
                        
                        // Check if any of these elements have meaningful height
                        if (draggable && draggable.offsetHeight > 100) return true;
                        if (pageContent && pageContent.offsetHeight > 100) return true;
                        if (gridLayout && gridLayout.offsetHeight > 100) return true;
                        
                        return false;
                    }
                """, timeout=10000)
                print("✅ Dashboard content rendered with proper dimensions")
            except Exception as e:
                print(f"⚠️ Timeout waiting for content to render: {e}")
                print("⏳ Continuing with additional wait...")
                await page.wait_for_timeout(5000)
            
            # Analyze page structure
            mantine_elements = await analyze_page_structure(page)
            
            # Test various selectors - prioritizing content-only areas
            selectors_to_test = [
                # Dashboard content selectors (should exclude navbar/header)
                "#draggable",
                ".react-grid-layout",
                "#page-content",
                "div#page-content",
                "[id='page-content']",
                
                # Data-specific selectors
                "[data-rgl]",
                ".draggable-grid-container",
                
                # Mantine AppShell selectors (full area including navbar/header)
                ".mantine-AppShell-main",
                "[class*='mantine-AppShell-main']",
                "[class*='AppShell-main']",
                "main",
                
                # Generic content selectors
                "[role='main']",
                ".dash-renderer",
                
                # Try the specific ID you mentioned
                "#m_8983817",
                "[id*='m_'][class*='mantine-AppShell-main']"
            ]
            
            best_selectors = await test_selectors(page, selectors_to_test)
            
            # Take screenshots with best selectors
            if best_selectors:
                await take_test_screenshots(page, best_selectors)
            
            # Keep browser open for manual inspection
            print("\n🔍 Browser will stay open for manual inspection...")
            print("Press Ctrl+C to exit")
            
            try:
                await page.wait_for_timeout(300000)  # 5 minutes
            except KeyboardInterrupt:
                print("\n👋 Exiting...")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())