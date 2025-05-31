import os
import asyncio
from pyppeteer import launch


async def capture_screenshots(url, output_folder):
    # Folder where screenshots will be saved
    output_folder = "dash/assets/screenshots"

    # Create the output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    # Launch a headless browser
    browser = await launch(headless=True)
    page = await browser.newPage()

    # Navigate to a blank page
    await page.goto(f"{url}/auth", {"waitUntil": "networkidle0"})

    # Set data in the local storage
    await page.evaluate("""() => {
        localStorage.setItem('local-store', '{"access_token":"eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbkBlbWJsLmRlIiwibmFtZSI6ImFkbWluQGVtYmwuZGVfMjAyNDA4MTMxNTExMDQiLCJ0b2tlbl9saWZldGltZSI6InNob3J0LWxpdmVkIiwiZXhwIjoxNzIzNjA1MDY0fQ.ZUPaHfeTSO2skpRFOEEyQsxYq5oOQs15R31X2nRDgqIBUfJlF_6tNiVzcIhIkR6Xx3A1OEybzvH1E-B9I401GWJnb5_bI_DGw4stDUl0wbk-7KINjMzq5S9_scu072FqUypOqJt6vM6lIUTIu1cpdip149WUrZcD0kij5A0MhjmHsOyMnSpDS-RsP4CFIbFkOCmWpfCgWL8U3RmiIPXLNy4xgYpD5f2tzhlc-Do3HWUxh8LDg8LtoCo2byYV_RckeGmqwoJvzU-Q1DDoGQSfMrbGez9K8qoBTlwbDhOvrfEoHK06ydjPgYEg1I5s6f50_pJiGG-xYu3Fwn7uFXlm3w", "logged_in": true}');
    }""")

    # Navigate to the URL
    await page.goto(url, {"waitUntil": "networkidle0"})

    # Wait for the page to load
    await page.waitForSelector("div#_dash-app-content")

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
    output_file = f"{output_folder}/TEST.png"
    await page.screenshot({"path": output_file, "fullPage": True})

    # Close the browser
    await browser.close()


url = "http://localhost:5080"
output_folder = "dash/assets/screenshots"

# Run the async function
asyncio.get_event_loop().run_until_complete(capture_screenshots(url, output_folder))
