import hashlib
import os
from playwright.async_api import async_playwright
import logging

logger = logging.getLogger(__name__)


async def capture_screenshots(url):
    # Folder where screenshots will be saved
    output_folder = "./depictio/dash/assets/screenshots"

    logger.info(f"Dashboard URL: {url}")

    # # Create the output folder if it doesn't exist
    # os.makedirs(output_folder, exist_ok=True)

    current_user = {
        "current_access_token": "123456",
        "email": "test",
    }

    dashboard_id = "1"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            logger.info(f"Browser: {browser}")

            # Navigate to a blank page
            # await page.goto(f"https://google.com",  wait_until="networkidle")
            await page.goto(f"{url}/auth", wait_until="networkidle")
            logger.info(f"Page URL: {url}")

            token_data = {
                "access_token": current_user["current_access_token"],
                "logged_in": "true",
                # "email": current_user.email,
            }
            logger.info(f"Token data: {token_data}")

            # Set data in the local storage
            await page.evaluate("""() => {
                localStorage.setItem('local-store', '{token_data}');
            }""")

            # Navigate to the URL
            await page.goto(f"{url}/dashboard/{dashboard_id}", wait_until="networkidle")

            # Wait for the page to load
            await page.wait_for_selector("div#_dash-app-content")

            # Remove the debug menu
            await page.evaluate("""() => {
                const debugMenuOuter = document.querySelector('.dash-debug-menu__outer');
                if (debugMenuOuter) {
                    debugMenuOuter.remove();
                }
            }""")

            await page.evaluate("""() => {
                const debugMenuOuter = document.querySelector('.dash-debug-menu');
                if (debugMenuOuter) {
                    debugMenuOuter.remove();
                }
            }""")

            # Capture the screenshot
            user = current_user["email"].split("_")[0]
            # Combine dashboard name and user name to create the output file name
            dashboard_name = url.split("/")[-1]

            # Create a hash based on the combination of the user and dashboard name
            # hash = hashlib.md5(f"{user}_{dashboard_name}".encode()).hexdigest()

            output_file = f"{output_folder}/{user}_{dashboard_name}.png"
            logger.info(f"Screenshot output file: {output_file}")
            await page.screenshot(path=output_file, full_page=True)

            # Close the browser
            # await browser.close()

    except Exception as e:
        logger.error(f"Failed to capture screenshot for dashboard URL: {url} - {e}")
        raise e


url = "http://localhost:5080"
output_folder = "dash/assets/screenshots"

# Run the async function
import asyncio

asyncio.get_event_loop().run_until_complete(capture_screenshots(url))
