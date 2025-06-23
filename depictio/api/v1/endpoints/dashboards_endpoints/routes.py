import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import load_dashboards_from_db
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import TokenBeanie, User, UserBeanie

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

    # logger.info(f"Dashboard data: {dashboard_data}")
    dashboard_data = DashboardData.from_mongo(dashboard_data)
    # logger.info(f"Dashboard data: {dashboard_data}")

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
    dashboard_id: PyObjectId,
    params: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Make a dashboard with the given dashboard ID public or private.
    """
    _public_status = params.get("is_public", None)
    if not _public_status:
        return {
            "success": False,
            "message": "No public status provided. Use 'is_public' parameter.",
        }
    logger.info(f"Making dashboard public: {_public_status}")
    logger.info(f"Current user: {current_user}")
    logger.info(f"Dashboard ID: {dashboard_id}")

    user_id = current_user.id

    # if _public_status:
    dashboards_collection.find_one_and_update(
        {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
        {"$set": {"is_public": _public_status}},
        # return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    )
    logger.info(f"Dashboard with ID '{dashboard_id}' made public.")
    # else:
    #     # get_current_permissions = dashboards_collection.find_one(
    #     #     {"dashboard_id": dashboard_id, "permissions.owners._id": user_id}
    #     # )
    #     result = dashboards_collection.find_one_and_update(
    #         {"dashboard_id": dashboard_id, "permissions.owners._id": user_id},
    #         {"$set": {"is_public": False}},
    #         # return_document=True,  # Adjust based on your MongoDB driver version, some versions might use ReturnDocument.AFTER
    #     )
    #     logger.info(f"Dashboard with ID '{dashboard_id}' made private.")

    # if result:
    #     logger.info(
    #         f"Dashboard with ID '{dashboard_id}' changed status to public: {_public_status}"
    #     )
    #     logger.info(f"Result: {result}")
    #     logger.info(f"Permissions: {result['permissions']}")

    return {
        "success": True,
        "message": f"Dashboard with ID '{dashboard_id}' changed status to public: {_public_status}",
        # "permissions": convert_objectid_to_str(result["permissions"]),
        "is_public": _public_status,
    }
    # else:
    #     raise HTTPException(
    #         status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
    #     )


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

    # logger.info(f"Dashboard data: {data}")

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
    # current_user: User = Depends(get_current_user),
):
    from playwright.async_api import async_playwright

    output_folder = "/app/depictio/dash/static/screenshots"  # Directly set to the desired path
    logger.info(f"Output folder: {output_folder}")
    try:
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=True)
            # Set viewport size
            viewport_width = 1920
            viewport_height = 1080
            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height}
            )
            page = await context.new_page()

            # Navigate to Dash service
            logger.info(f"Navigating to Dash service at {settings.dash.internal_url}")
            await page.goto(settings.dash.internal_url, timeout=90000)

            # Wait for page to load
            await page.wait_for_load_state("networkidle")

            current_user = await UserBeanie.find_one({"email": "admin@example.com"})

            # current_user = await UserBeanie.find_one({"email": "admin@example.com"})
            logger.debug(f"Current user: {current_user}")

            # get the current user a functional token
            token = await TokenBeanie.find_one(
                {
                    "user_id": current_user.id,
                    # "token_lifetime": "short-lived",
                    # "expire_datetime": {"$gt": datetime.now()},
                }
            )
            logger.debug(f"Token: {token}")

            token_data = token.model_dump(exclude_none=True)
            token_data["_id"] = token_data.pop("id", None)
            token_data["logged_in"] = True
            logger.debug(f"Token: {token}")

            token_data_json = json.dumps(token_data)
            logger.debug(f"Token data: {token_data_json}")

            # Set data in the local storage
            await page.evaluate(
                f"""() => {{
                localStorage.setItem('local-store', '{token_data_json}');
            }}"""
            )
            # await asyncio.sleep(3600)  # Keeps the browser open for 1 hour

            await page.reload()

            await asyncio.sleep(3)  # Wait for the page to stabilize
            # dashboard_id = "6824cb3b89d2b72169309737"
            await page.goto(f"{settings.dash.internal_url}/dashboard/{dashboard_id}", timeout=90000)
            await page.wait_for_load_state("networkidle")
            await page.reload()
            await asyncio.sleep(3)

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

            element = await page.query_selector("div#page-content")

            # await page.screenshot(path=f"{output_folder}/dash_screenshot.png", full_page=True)
            output_file = f"{output_folder}/{str(dashboard_id)}.png"
            await element.screenshot(path=output_file)

            await browser.close()
            logger.info(f"Screenshot saved to {output_file}")

            return {
                "success": True,
                "url": settings.dash.internal_url,
                "message": "Screenshot taken successfully",
                "screenshot_path": f"{output_folder}/dash_screenshot.png",
                "token": convert_objectid_to_str(token_data),
                "user": current_user.model_dump(exclude_none=True),
            }

    except Exception as e:
        return {
            "success": False,
            "url": settings.dash.internal_url,
            "error": str(e),
            "message": "Failed to take screenshot",
        }


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
    Fetch component data related to a component ID using optimized MongoDB aggregation.

    This endpoint uses MongoDB aggregation pipeline to:
    1. Filter by dashboard_id and user permissions
    2. Filter the stored_metadata array to find only the specific component
    3. Return only the component data without loading the full dashboard
    """

    user_id = current_user.id
    logger.debug(f"Current user ID: {user_id}, fetching component: {component_id}")

    # Optimized aggregation pipeline to fetch only the specific component
    pipeline = [
        # Stage 1: Match dashboard and user permissions
        {
            "$match": {
                "dashboard_id": dashboard_id,
                "$or": [
                    {"permissions.owners._id": user_id},
                    {"permissions.viewers._id": user_id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},  # Allow public access if dashboard is public
                ],
            }
        },
        # Stage 2: Project only the filtered component from stored_metadata
        {
            "$project": {
                "_id": 1,
                "dashboard_id": 1,
                "component_metadata": {
                    "$filter": {
                        "input": "$stored_metadata",
                        "as": "metadata",
                        "cond": {"$eq": ["$$metadata.index", str(component_id)]},
                    }
                },
            }
        },
        # Stage 3: Unwind the component_metadata array to get single object
        {
            "$unwind": {
                "path": "$component_metadata",
                "preserveNullAndEmptyArrays": False,  # Skip if no matching component found
            }
        },
        # Stage 4: Replace root with just the component metadata
        {"$replaceRoot": {"newRoot": "$component_metadata"}},
    ]

    # Execute aggregation pipeline
    result = list(dashboards_collection.aggregate(pipeline))

    logger.debug(f"Aggregation result: {result}")

    if not result:
        # Check if dashboard exists vs component not found
        dashboard_exists = dashboards_collection.find_one(
            {
                "dashboard_id": dashboard_id,
                "$or": [
                    {"permissions.owners._id": user_id},
                    {"permissions.viewers._id": user_id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},  # Allow public access if dashboard is public
                ],
            },
            {"_id": 1},  # Only fetch _id to check existence
        )

        if not dashboard_exists:
            raise HTTPException(
                status_code=404,
                detail=f"Dashboard with ID '{dashboard_id}' not found or access denied.",
            )
        else:
            logger.error(f"Component with ID {component_id} not found in dashboard {dashboard_id}.")
            raise HTTPException(
                status_code=404,
                detail=f"Component with ID '{component_id}' not found in dashboard.",
            )

    # Get the component metadata
    component_metadata = result[0]

    logger.debug(f"Component metadata found for ID {component_id}")

    # Convert ObjectIds to strings for JSON serialization
    component_metadata = convert_objectid_to_str(component_metadata)

    return component_metadata
