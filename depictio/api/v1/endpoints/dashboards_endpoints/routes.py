import json
import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import DASH_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import load_dashboards_from_db
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import TokenBeanie, User

dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.get("/get/{dashboard_id}", response_model=DashboardData)
async def get_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
    """
    Fetch dashboard data related to a dashboard ID.
    """

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    # Find dashboards where current_user is either an owner or a viewer
    query = {
        "dashboard_id": dashboard_id,
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": {"$in": ["*"]}},
        ],
    }

    dashboard_data = dashboards_collection.find_one(query)

    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    logger.info(f"Dashboard data: {dashboard_data}")
    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.info(f"Dashboard data: {dashboard_data}")

    # logger.info(f"Dashboard data from mongo: {dashboard_data}")
    # dashboard_data = convert_model_to_dict(dashboard_data)
    # logger.info(f"Dashboard data from mongo: {dashboard_data}")

    return dashboard_data


@dashboards_endpoint_router.get("/list")
async def list_dashboards(
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a list of dashboards for the current user.
    """

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    result = load_dashboards_from_db(owner=user_id, admin_mode=False)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


@dashboards_endpoint_router.get("/list_all")
async def list_all_dashboards(
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a list of dashboards for the current user.
    """

    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")
    logger.info(f"Current user: {current_user}")

    result = load_dashboards_from_db(owner=user_id, admin_mode=True)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return result["dashboards"]


@dashboards_endpoint_router.post("/toggle_public_status/{dashboard_id}")
async def make_dashboard_public(
    dashboard_id: str,
    params: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Make a dashboard with the given dashboard ID public or private.
    """
    logger.info(f"Params: {params}")
    logger.info(f"Current user: {current_user}")
    logger.info(f"Dashboard ID: {dashboard_id}")

    status = bool(params.get("public", None))

    user_id = current_user.id

    if status:
        result = dashboards_collection.find_one_and_update(
            {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
            {"$set": {"permissions.viewers": ["*"]}},
            return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
        )
        logger.info(f"Dashboard with ID '{dashboard_id}' made public.")
    else:
        get_current_permissions = dashboards_collection.find_one(
            {"dashboard_id": dashboard_id, "permissions.owners._id": user_id}
        )
        result = dashboards_collection.find_one_and_update(
            {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
            {
                "$set": {
                    "permissions.viewers": [
                        e for e in get_current_permissions["permissions"]["viewers"] if e != "*"
                    ]
                }
            },
            return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
        )
        logger.info(f"Dashboard with ID '{dashboard_id}' made private.")

    if result:
        logger.info(f"Dashboard with ID '{dashboard_id}' changed status to public: {status}")
        logger.info(f"Result: {result}")
        logger.info(f"Permissions: {result['permissions']}")

        return {
            "message": f"Dashboard with ID '{dashboard_id}' changed status to public: {status}",
            "permissions": convert_objectid_to_str(result["permissions"]),
        }
    else:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )


@dashboards_endpoint_router.post("/edit_name/{dashboard_id}")
async def edit_dashboard_name(
    dashboard_id: PyObjectId,
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Edit the name of a dashboard with the given dashboard ID.
    """

    user_id = current_user.id

    new_name = data.get("new_name", None)
    if not new_name:
        raise HTTPException(status_code=400, detail="No new name provided.")

    logger.info(f"New name: {new_name}")
    logger.info(f"Dashboard ID: {dashboard_id} of type {type(dashboard_id)}")

    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
        {"$set": {"title": new_name}},
        return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )

    if result:
        logger.info(f"Dashboard name updated successfully to '{new_name}'.")
        return {"message": f"Dashboard name updated successfully to '{new_name}'."}
    else:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )


# /Users/tweber/Gits/depictio/dev/jup_nb/.jupyter/jupyter_notebook_config.py
@dashboards_endpoint_router.post("/save/{dashboard_id}")
async def save_dashboard(
    dashboard_id: PyObjectId,
    data: DashboardData,
    current_user: User = Depends(get_current_user),
):
    """
    Check if an entry with the same dashboard_id exists, if not, insert, if yes, update.
    """

    user_id = current_user.id

    logger.info(f"Dashboard data: {data}")

    # Attempt to find and update the document, or insert if it doesn't exist
    result = dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
        {"$set": data.mongo()},
        upsert=True,
        return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )

    # MongoDB should always return a document after an upsert operation
    if result:
        message = (
            "Dashboard data updated successfully."
            if result.get("dashboard_id", None) == dashboard_id
            else "Dashboard data inserted successfully."
        )
        logger.info(message)

        # Convert dashboard_id to string to ensure proper JSON serialization
        dashboard_id_str = str(dashboard_id)

        return {"message": message, "dashboard_id": dashboard_id_str}
    else:
        logger.error("Failed to insert or update dashboard data.")
        # It's unlikely to reach this point due to upsert=True, but included for completeness
        raise HTTPException(status_code=404, detail="Failed to insert or update dashboard data.")


@dashboards_endpoint_router.get("/screenshot/{dashboard_id}")
async def screenshot_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
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

    playwright_dev_mode = not os.getenv("DEPICTIO_PLAYWRIGHT_DEV_MODE", "False").lower() == "true"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=playwright_dev_mode)
            # browser = await p.chromium.launch(headless=True, executable_path="/home/mambauser/.cache/ms-playwright/chromium-1140/chrome-linux/chrome")

            # Define the viewport size (browser window size)
            viewport_width = 1920
            viewport_height = 1080

            # Create a new context with the specified viewport size
            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height}
            )

            page = await context.new_page()
            logger.info(f"Browser: {browser}")

            # Navigate to the URL
            await page.goto(f"{url}/auth", wait_until="networkidle")
            logger.info(f"Page URL: {url}/auth")

            # get the current user a functional token
            token = await TokenBeanie.find_one(
                {
                    "user_id": current_user.id,
                    "token_lifetime": "short-lived",
                    "expire_datetime": {"$gt": datetime.now()},
                }
            )
            logger.info(f"Token: {token}")

            token_data = token.model_dump(exclude_none=True)
            token_data["_id"] = token_data.pop("id", None)
            token_data["logged_in"] = True
            logger.info(f"Token: {token}")

            token_data_json = json.dumps(token_data)
            logger.info(f"Token data: {token_data_json}")

            # Set data in the local storage
            await page.evaluate(
                f"""() => {{
                localStorage.setItem('local-store', '{token_data_json}');
            }}"""
            )
            # await asyncio.sleep(3600)  # Keeps the browser open for 1 hour

            await page.reload()

            # Navigate to the target dashboard page
            await page.goto(f"{url}/dashboard/{str(dashboard_id)}", wait_until="networkidle")
            logger.info(f"Page URL: {url}/dashboard/{str(dashboard_id)}")

            # Wait for the page content to load
            await page.wait_for_selector("div#page-content")
            logger.info("Wait for selector: div#page-content")

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
            await page.evaluate(
                """() => {
                const debugMenuOuter = document.querySelector('.dash-debug-menu__outer');
                if (debugMenuOuter) {
                    debugMenuOuter.remove();
                }
                const debugMenu = document.querySelector('.dash-debug-menu');
                if (debugMenu) {
                    debugMenu.remove();
                }
            }"""
            )
            logger.info("Removed debug menu")

            # Capture a screenshot of the content below the 'div#page-content'
            element = await page.query_selector("div#page-content")

            if element:
                # await page.wait_for_timeout(3000)
                # logger.info(f"Wait for timeout: 3000")

                # user = current_user.email.split("_")[0]
                # user_id = current_user.id

                # find corresponding mongoid for the dashboard

                output_file = f"{output_folder}/{str(dashboard_id)}.png"
                logger.info(f"Output file: {output_file}")
                await element.screenshot(path=output_file)
                logger.info(f"Screenshot captured for dashboard ID: {str(dashboard_id)}")
            else:
                logger.error("Could not find 'div#page-content' element")

            # Close the browser
            await browser.close()

    except Exception as e:
        logger.error(f"Failed to capture screenshot for dashboard URL: {url} - {e}")
        raise e


@dashboards_endpoint_router.delete("/delete/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_current_user),
):
    """
    Delete a dashboard with the given dashboard ID.
    """

    user_id = current_user.id

    result = dashboards_collection.delete_one(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id}
    )

    if result.deleted_count > 0:
        return {"message": f"Dashboard with ID '{str(dashboard_id)}' deleted successfully."}
    else:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )


@dashboards_endpoint_router.get("/get_component_data/{dashboard_id}/{component_id}")
async def get_component_data_endpoint(
    dashboard_id: PyObjectId,
    component_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Fetch component data related to a component ID.
    """

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}")

    # Find dashboards where current_user is either an owner or a viewer
    query = {
        "dashboard_id": dashboard_id,
        "$or": [
            {"permissions.owners._id": user_id},
            {"permissions.viewers._id": user_id},
            {"permissions.viewers": "*"},
        ],
    }

    dashboard_data = dashboards_collection.find_one(query)

    logger.debug(f"Dashboard data: {dashboard_data}")

    dashboard_data = DashboardData.from_mongo(dashboard_data)
    logger.debug(f"Dashboard data from mongo: {dashboard_data}")

    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Extract stored_metadata
    stored_metadata = dashboard_data.stored_metadata
    if not stored_metadata:
        logger.error(f"No stored_metadata found in dashboard {dashboard_id}.")
        return None

    # Find the component metadata by component_id
    component_metadata = next(
        (item for item in stored_metadata if item.get("index") == str(component_id)),
        None,
    )
    if not component_metadata:
        logger.error(f"Component with ID {str(component_id)} not found in stored_metadata.")
        return None

    logger.info(f"Component metadata found: {component_metadata}")

    component_metadata = convert_objectid_to_str(component_metadata)

    return component_metadata
