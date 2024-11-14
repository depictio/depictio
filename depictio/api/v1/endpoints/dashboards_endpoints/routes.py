import json
import os, sys
from typing import Dict
from fastapi import Depends, HTTPException, APIRouter


from depictio.api.v1.configs.config import API_BASE_URL, DASH_BASE_URL
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import load_dashboards_from_db
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.configs.logging import logger

from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.get("/get/{dashboard_id}")
async def get_dashboard(dashboard_id: str, current_user=Depends(get_current_user)):
    """
    Fetch dashboard data related to a dashboard ID.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    # Find dashboards where current_user is either an owner or a viewer
    query = {
        "dashboard_id": str(dashboard_id),
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": {"$in": ["*"]}},
        ],
    }

    dashboard_data = dashboards_collection.find_one(query)

    logger.debug(f"Dashboard data: {dashboard_data}")

    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.debug(f"Dashboard data from mongo: {dashboard_data}")

    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found.")

    return dashboard_data


@dashboards_endpoint_router.get("/list")
async def list_dashboards(current_user=Depends(get_current_user)):
    """
    Fetch a list of dashboards for the current user.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    result = load_dashboards_from_db(owner=user_id, admin_mode=False)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]

@dashboards_endpoint_router.get("/list_all")
async def list_dashboards(current_user=Depends(get_current_user)):
    """
    Fetch a list of dashboards for the current user.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")
    logger.info(f"Current user: {current_user}")

    result = load_dashboards_from_db(owner=user_id, admin_mode=True)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


# /Users/tweber/Gits/depictio/dev/jup_nb/.jupyter/jupyter_notebook_config.py
@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(dashboard_id: str, data: dict, current_user=Depends(get_current_user)):
    """
    Check if an entry with the same dashboard_id exists, if not, insert, if yes, update.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    if not data:
        raise HTTPException(status_code=400, detail="No data provided to save.")

    user_id = current_user.id

    data = DashboardData.from_mongo(data)

    data_dict = data.mongo()

    # Attempt to find and update the document, or insert if it doesn't exist
    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
        {"$set": data_dict},
        upsert=True,
        return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )

    # MongoDB should always return a document after an upsert operation
    if result:
        message = "Dashboard data updated successfully." if result.get("dashboard_id", None) == dashboard_id else "Dashboard data inserted successfully."
        logger.info(message)

        return {"message": message, "dashboard_id": dashboard_id}
    else:
        logger.error("Failed to insert or update dashboard data.")
        # It's unlikely to reach this point due to upsert=True, but included for completeness
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")


@dashboards_endpoint_router.get("/screenshot/{dashboard_id}")
async def screenshot_dashboard(dashboard_id: str, current_user=Depends(get_current_user)):
    from playwright.async_api import async_playwright

    # Folder where screenshots will be saved
    # output_folder = "/app/depictio/dash/assets/screenshots"

    # Define the shared static directory
    output_folder = "/app/depictio/dash/static/screenshots"  # Directly set to the desired path
    logger.info(f"Output folder: {output_folder}")

    # Ensure the directory exists
    os.makedirs(output_folder, exist_ok=True)

    # DASH_BASE_URL = "http://localhost:5080"
    url = f"{DASH_BASE_URL}"
    # url = f"{DASH_BASE_URL}/{dashboard_id}"
    logger.info(f"Dashboard URL: {url}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path="/home/mambauser/.cache/ms-playwright/chromium-1140/chrome-linux/chrome")

            # Define the viewport size (browser window size)
            viewport_width = 1920
            viewport_height = 1080

            # Create a new context with the specified viewport size
            context = await browser.new_context(viewport={"width": viewport_width, "height": viewport_height})

            page = await context.new_page()
            logger.info(f"Browser: {browser}")

            # Navigate to the URL
            await page.goto(f"{url}/auth", wait_until="networkidle")
            logger.info(f"Page URL: {url}/auth")

            token_data = {
                "access_token": current_user.current_access_token,
                "logged_in": True,
            }

            token_data_json = json.dumps(token_data)
            logger.info(f"Token data: {token_data_json}")

            # Set data in the local storage
            await page.evaluate(f"""() => {{
                localStorage.setItem('local-store', '{token_data_json}');
            }}""")

            await page.reload()

            # Navigate to the target dashboard page
            await page.goto(f"{url}/dashboard/{dashboard_id}", wait_until="networkidle")
            logger.info(f"Page URL: {url}/dashboard/{dashboard_id}")

            # Wait for the page content to load
            await page.wait_for_selector("div#page-content")
            logger.info(f"Wait for selector: div#page-content")

            # # Check if the iframe is present
            # iframe_element = await page.query_selector('iframe[src*="jbrowse"]')  # Adjust the selector to match the iframe's source or other attributes

            # if iframe_element:
            #     # If the iframe is present, wait for its content to load
            #     iframe = await iframe_element.content_frame()
            #     await iframe.wait_for_selector("")  # Replace with a specific element inside the iframe
            #     logger.info(f"Iframe loaded with element 'your-element-inside-iframe'")
            # else:
            #     logger.info("Iframe not found, proceeding without waiting for iframe content")

            # Remove the debug menu if it exists
            await page.evaluate("""() => {
                const debugMenuOuter = document.querySelector('.dash-debug-menu__outer');
                if (debugMenuOuter) {
                    debugMenuOuter.remove();
                }
                const debugMenu = document.querySelector('.dash-debug-menu');
                if (debugMenu) {
                    debugMenu.remove();
                }
            }""")
            logger.info(f"Removed debug menu")

            # Capture a screenshot of the content below the 'div#page-content'
            element = await page.query_selector("div#page-content")

            if element:
                # await page.wait_for_timeout(3000)
                # logger.info(f"Wait for timeout: 3000")

                user = current_user.email.split("_")[0]
                user_id = current_user.id

                # find corresponding mongoid for the dashboard
                dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id, "permissions.owners._id": user_id})
                logger.debug(f"Dashboard data: {dashboard_data}")
                dashboard_mongo_id = dashboard_data["_id"]

                output_file = f"{output_folder}/{dashboard_mongo_id}.png"
                logger.info(f"Output file: {output_file}")
                await element.screenshot(path=output_file)
                logger.info(f"Screenshot captured for dashboard ID: {dashboard_id}")
            else:
                logger.error("Could not find 'div#page-content' element")

            # Close the browser
            await browser.close()

    except Exception as e:
        logger.error(f"Failed to capture screenshot for dashboard URL: {url} - {e}")
        raise e


@dashboards_endpoint_router.delete("/delete/{dashboard_id}")
async def delete_dashboard(dashboard_id: str, current_user=Depends(get_current_user)):
    """
    Delete a dashboard with the given dashboard ID.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id

    result = dashboards_collection.delete_one({"dashboard_id": dashboard_id, "permissions.owners._id": user_id})

    if result.deleted_count > 0:
        return {"message": f"Dashboard with ID '{dashboard_id}' deleted successfully."}
    else:
        raise HTTPException(status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found.")


@dashboards_endpoint_router.get("/get_component_data/{dashboard_id}/{component_id}")
async def get_component_data_endpoint(dashboard_id: str, component_id: str, current_user=Depends(get_current_user)):
    """
    Fetch component data related to a component ID.
    """

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    # Find dashboards where current_user is either an owner or a viewer
    query = {
        "dashboard_id": str(dashboard_id),
        "$or": [{"permissions.owners._id": user_id}, {"permissions.viewers._id": user_id}, {"permissions.viewers": "*"}],
    }

    dashboard_data = dashboards_collection.find_one(query)

    logger.debug(f"Dashboard data: {dashboard_data}")

    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.debug(f"Dashboard data from mongo: {dashboard_data}")

    if not dashboard_data:
        raise HTTPException(status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found.")

    # Extract stored_metadata
    stored_metadata = dashboard_data.stored_metadata
    if not stored_metadata:
        logger.error(f"No stored_metadata found in dashboard {dashboard_id}.")
        return None

    # Find the component metadata by component_id
    component_metadata = next((item for item in stored_metadata if item.get("index") == component_id), None)
    if not component_metadata:
        logger.error(f"Component with ID {component_id} not found in stored_metadata.")
        return None

    logger.info(f"Component metadata found: {component_metadata}")

    return component_metadata
