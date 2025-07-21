import asyncio
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

# Initialize FastAPI app
app = FastAPI(title="Screenshot Debug API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
DASH_URL = "http://localhost:7777"
SCREENSHOT_DIR = Path("screenshots")

# Ensure screenshot directory exists
SCREENSHOT_DIR.mkdir(exist_ok=True)


@app.get("/")
async def root():
    return {"message": "Screenshot Debug API", "dash_url": DASH_URL}


@app.get("/screenshot")
async def screenshot_dashboard():
    """
    Take a screenshot of the Dash application using Playwright
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_filename = f"dash_screenshot_{timestamp}.png"
    screenshot_path = SCREENSHOT_DIR / screenshot_filename

    try:
        async with async_playwright() as p:
            print(f"🚀 Launching browser...")

            # Launch browser with explicit args for better compatibility
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )

            # Set viewport size
            viewport_width = 1920
            viewport_height = 1080

            print(f"📱 Creating browser context with viewport {viewport_width}x{viewport_height}")
            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

            page = await context.new_page()

            print(f"🌐 Navigating to {DASH_URL}")

            # Navigate to Dash service with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await page.goto(DASH_URL, timeout=15000, wait_until="networkidle")
                    print(f"✅ Successfully navigated to Dash app (attempt {attempt + 1})")
                    break
                except Exception as e:
                    print(f"⚠️ Navigation attempt {attempt + 1} failed: {e}")
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(2)

            # Wait for the page to be fully loaded
            print("⏳ Waiting for page to stabilize...")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)  # Additional wait for any dynamic content

            # Check if page loaded correctly by looking for expected content
            try:
                await page.wait_for_selector("h1", timeout=5000)
                print("✅ Found page title, page seems to be loaded")
            except:
                print("⚠️ Could not find expected page title")

            # Remove any debug elements (if they exist)
            await page.evaluate("""
                () => {
                    // Remove Dash debug menu if present
                    const debugMenuOuter = document.querySelector('.dash-debug-menu__outer');
                    if (debugMenuOuter) {
                        debugMenuOuter.remove();
                        console.log('Removed debug menu outer');
                    }
                    const debugMenu = document.querySelector('.dash-debug-menu');
                    if (debugMenu) {
                        debugMenu.remove();
                        console.log('Removed debug menu');
                    }
                }
            """)

            # Take screenshot of the entire page
            print(f"📸 Taking screenshot and saving to {screenshot_path}")
            await page.screenshot(path=str(screenshot_path), full_page=True, type="png")

            # Get page title for confirmation
            page_title = await page.title()
            print(f"📋 Page title: {page_title}")

            await browser.close()
            print(f"✅ Screenshot saved successfully to {screenshot_path}")

            return {
                "success": True,
                "message": "Screenshot taken successfully",
                "screenshot_path": str(screenshot_path),
                "screenshot_filename": screenshot_filename,
                "page_title": page_title,
                "timestamp": timestamp,
                "dash_url": DASH_URL,
            }

    except Exception as e:
        print(f"❌ Error taking screenshot: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to take screenshot",
            "dash_url": DASH_URL,
        }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    print("🚀 Starting FastAPI Screenshot Debug Server...")
    print(f"📸 Screenshots will be saved to: {SCREENSHOT_DIR.absolute()}")
    print(f"🎯 Target Dash app: {DASH_URL}")

    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8888, reload=True, log_level="info")
