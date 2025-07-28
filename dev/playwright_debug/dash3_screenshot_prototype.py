#!/usr/bin/env python3
"""
Dash 3+ Screenshot Prototype - Target page-content only

This prototype tests various strategies to capture just the page-content element
in Dash 3.x applications, excluding headers, debug menus, and other UI elements.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# Configuration
DASHBOARD_URL = "http://localhost:8002/dashboard/6824cb3b89d2b72169309737"
BASE_URL = "http://localhost:8002"
OUTPUT_DIR = Path(__file__).parent / "screenshots"
OUTPUT_DIR.mkdir(exist_ok=True)

# Mock token data for testing (replace with real token)
MOCK_TOKEN_DATA = {
    "_id": "mock_id",
    "user_id": "mock_user",
    "logged_in": True,
    "expire_datetime": "2025-12-31 23:59:59",
    "created_at": "2025-01-01 00:00:00"
}


async def wait_for_page_content_strategy_1(page):
    """
    Strategy 1: Wait for page-content to be visible with specific content
    """
    print("🔍 Strategy 1: Waiting for page-content visibility...")
    
    try:
        # Wait for page-content to exist
        await page.wait_for_selector("div#page-content", timeout=10000)
        
        # Check if it has meaningful content
        content_info = await page.evaluate("""
            () => {
                const pageContent = document.querySelector('div#page-content');
                if (!pageContent) return null;
                
                return {
                    exists: true,
                    visible: pageContent.offsetParent !== null,
                    height: pageContent.offsetHeight,
                    width: pageContent.offsetWidth,
                    children: pageContent.children.length,
                    hasText: pageContent.textContent.trim().length > 0
                };
            }
        """)
        
        print(f"📊 Page-content info: {content_info}")
        
        if content_info and content_info['height'] > 100 and content_info['children'] > 0:
            print("✅ Page-content appears ready")
            return True
        else:
            print("❌ Page-content not ready")
            return False
            
    except Exception as e:
        print(f"❌ Strategy 1 failed: {e}")
        return False


async def wait_for_page_content_strategy_2(page):
    """
    Strategy 2: Wait for specific dashboard components within page-content
    """
    print("🔍 Strategy 2: Waiting for dashboard components...")
    
    dashboard_selectors = [
        "#draggable",
        ".react-grid-layout", 
        "[data-rgl]",
        ".dash-renderer"
    ]
    
    for selector in dashboard_selectors:
        try:
            print(f"  Checking for {selector}...")
            await page.wait_for_selector(selector, timeout=5000)
            
            # Check if element is meaningful
            element_info = await page.evaluate(f"""
                () => {{
                    const el = document.querySelector('{selector}');
                    return el ? {{
                        height: el.offsetHeight,
                        width: el.offsetWidth,
                        visible: el.offsetParent !== null
                    }} : null;
                }}
            """)
            
            print(f"  📊 {selector} info: {element_info}")
            
            if element_info and element_info['height'] > 50:
                print(f"✅ Found meaningful content in {selector}")
                return True
                
        except Exception as e:
            print(f"  ❌ {selector} not found: {str(e)[:50]}")
            continue
    
    print("❌ No meaningful dashboard components found")
    return False


async def wait_for_page_content_strategy_3(page):
    """
    Strategy 3: Trigger events and wait for layout recalculation
    """
    print("🔍 Strategy 3: Forcing layout recalculation...")
    
    try:
        # Trigger resize and other events that might help with layout
        await page.evaluate("""
            () => {
                // Trigger various events that might cause layout recalculation
                window.dispatchEvent(new Event('resize'));
                window.dispatchEvent(new Event('orientationchange'));
                
                // Force page-content to be visible if it exists
                const pageContent = document.querySelector('#page-content');
                if (pageContent) {
                    pageContent.style.display = 'block';
                    pageContent.style.visibility = 'visible';
                    pageContent.style.opacity = '1';
                }
                
                // Trigger any React component updates
                if (window.React && window.React.version) {
                    console.log('React version:', window.React.version);
                }
            }
        """)
        
        # Wait a bit for events to process
        await page.wait_for_timeout(2000)
        
        # Check page-content again
        return await wait_for_page_content_strategy_1(page)
        
    except Exception as e:
        print(f"❌ Strategy 3 failed: {e}")
        return False


async def take_page_content_screenshot(page, output_file):
    """
    Attempt to screenshot just the page-content element
    """
    print("📸 Attempting page-content screenshot...")
    
    try:
        page_content = await page.query_selector("div#page-content")
        if not page_content:
            raise Exception("page-content element not found")
        
        # Check if element is actually visible and has content
        is_visible = await page_content.is_visible()
        bounding_box = await page_content.bounding_box()
        
        print(f"📊 Element state: visible={is_visible}, box={bounding_box}")
        
        if not is_visible or not bounding_box or bounding_box.get('height', 0) < 50:
            raise Exception(f"page-content not suitable: visible={is_visible}, height={bounding_box.get('height', 0) if bounding_box else 0}")
        
        # Scroll into view and take screenshot
        await page_content.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        
        await page_content.screenshot(path=output_file)
        print(f"✅ Page-content screenshot saved: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Page-content screenshot failed: {e}")
        return False


async def take_fallback_screenshot(page, output_file):
    """
    Fallback screenshot strategies
    """
    print("📸 Trying fallback screenshot strategies...")
    
    # Try body element
    try:
        body = await page.query_selector("body")
        if body:
            await body.screenshot(path=output_file.replace('.png', '_body.png'))
            print("✅ Body screenshot taken")
    except Exception as e:
        print(f"❌ Body screenshot failed: {e}")
    
    # Try full page
    try:
        await page.screenshot(path=output_file.replace('.png', '_fullpage.png'), full_page=True)
        print("✅ Full page screenshot taken")
    except Exception as e:
        print(f"❌ Full page screenshot failed: {e}")


async def test_screenshot_strategies():
    """
    Test different strategies for capturing page-content in Dash 3+
    """
    print("🚀 Starting Dash 3+ Screenshot Prototype")
    print(f"Target URL: {DASHBOARD_URL}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=1000)  # Visible for debugging
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            # Set up authentication
            print("🔐 Setting up authentication...")
            await page.goto(BASE_URL)
            await page.evaluate(f"localStorage.setItem('local-store', '{json.dumps(MOCK_TOKEN_DATA)}')")
            
            # Navigate to dashboard
            print("🌐 Navigating to dashboard...")
            await page.goto(DASHBOARD_URL, timeout=30000)
            
            # Wait for initial page load
            print("⏳ Initial wait for page load...")
            await page.wait_for_timeout(5000)
            
            # Test different strategies
            strategies = [
                wait_for_page_content_strategy_1,
                wait_for_page_content_strategy_2, 
                wait_for_page_content_strategy_3
            ]
            
            successful_strategy = None
            for i, strategy in enumerate(strategies, 1):
                print(f"\n{'='*50}")
                print(f"Testing Strategy {i}")
                print(f"{'='*50}")
                
                if await strategy(page):
                    successful_strategy = i
                    break
                    
                print(f"Strategy {i} failed, trying next...")
                await page.wait_for_timeout(2000)  # Brief wait between strategies
            
            # Take screenshots based on results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = OUTPUT_DIR / f"dashboard_{timestamp}.png"
            
            if successful_strategy:
                print(f"\n✅ Strategy {successful_strategy} succeeded!")
                print("📸 Taking page-content screenshot...")
                
                if not await take_page_content_screenshot(page, str(output_file)):
                    print("📸 Page-content screenshot failed, taking fallbacks...")
                    await take_fallback_screenshot(page, str(output_file))
            else:
                print("\n❌ All strategies failed!")
                print("📸 Taking fallback screenshots...")
                await take_fallback_screenshot(page, str(output_file))
            
            # Debug information
            print(f"\n{'='*50}")
            print("DEBUG INFORMATION")
            print(f"{'='*50}")
            
            # Get page info
            page_info = await page.evaluate("""
                () => {
                    return {
                        title: document.title,
                        url: window.location.href,
                        readyState: document.readyState,
                        dashVersion: window.dash ? window.dash.version : 'not found',
                        reactVersion: window.React ? window.React.version : 'not found',
                        pageContentExists: !!document.querySelector('#page-content'),
                        draggableExists: !!document.querySelector('#draggable'),
                        bodyChildren: document.body.children.length
                    };
                }
            """)
            
            print(f"📊 Page info: {json.dumps(page_info, indent=2)}")
            
            # Keep browser open for manual inspection
            print("\n🔍 Browser will stay open for 30 seconds for manual inspection...")
            await page.wait_for_timeout(30000)
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            
        finally:
            await browser.close()
            print("🏁 Test completed")


if __name__ == "__main__":
    print("Dash 3+ Screenshot Prototype")
    print("=" * 50)
    asyncio.run(test_screenshot_strategies())