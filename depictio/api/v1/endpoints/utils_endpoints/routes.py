import asyncio
import json
from datetime import datetime
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    runs_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import (
    process_initial_data_collections,
)
from depictio.api.v1.s3 import s3_client
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.version import get_version

# Define the router
utils_endpoint_router = APIRouter()


@utils_endpoint_router.get("/create_bucket")
async def create_bucket_endpoint(current_user=Depends(get_current_user)):
    if not current_user:
        logger.error("Current user not found.")
        raise HTTPException(status_code=401, detail="Current user not found.")

    response = create_bucket(current_user)

    if response.status_code == 200:
        logger.info(response.detail)
        return response
    else:
        logger.error(response.detail)
        raise HTTPException(status_code=response.status_code, detail=response.detail)


# TODO - remove this endpoint - only for testing purposes in order to drop the S3 bucket content & the DB collections
@utils_endpoint_router.get("/drop_S3_content")
async def drop_S3_content(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    bucket_name = settings.minio.bucket

    # List and delete all objects in the bucket
    objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)
    while objects_to_delete.get("Contents"):
        print(f"Deleting {len(objects_to_delete['Contents'])} objects...")
        delete_keys = [{"Key": obj["Key"]} for obj in objects_to_delete["Contents"]]
        s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_keys})
        objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)

    print("All objects deleted from the bucket.")

    # FIXME: remove this - only for testing purposes
    # Delete directory content directly from the file system
    # shutil.rmtree(settings.minio.data_dir)

    return {"message": "S3 bucket content dropped"}


@utils_endpoint_router.get("/drop_all_collections")
async def drop_all_collections(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    deltatables_collection.drop()
    dashboards_collection.drop()
    return {"message": "All collections dropped"}


@utils_endpoint_router.get("/status")
async def status():
    """
    Check if the server is online.
    This endpoint is public and does not require authentication.
    """
    logger.info("Checking server status...")
    logger.info("Server is online.")

    return {"status": "online", "version": get_version()}


@utils_endpoint_router.post("/process_initial_data_collections")
async def process_initial_data_collections_endpoint(
    background_tasks: BackgroundTasks, current_user=Depends(get_current_user)
):
    """
    Process the initial data collections for the first project.
    This endpoint should be called after the API is fully started.

    The processing is done in the background to avoid blocking the request.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    # Add the task to the background tasks
    background_tasks.add_task(process_initial_data_collections)

    return {
        "message": "Processing initial data collections in the background. Check the logs for progress."
    }


@utils_endpoint_router.get("/screenshot-dash-fixed/{dashboard_id}")
async def screenshot_dash_fixed(dashboard_id: str = "6824cb3b89d2b72169309737"):
    """
    Fixed screenshot endpoint with proper authentication handling
    """
    from playwright.async_api import async_playwright

    output_folder = "/app/depictio/dash/static/screenshots"
    output_file = f"{output_folder}/{str(dashboard_id)}.png"
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    try:
        # Get authentication data
        current_user = await UserBeanie.find_one({"email": "admin@example.com"})
        if not current_user:
            raise HTTPException(status_code=404, detail="Admin user not found")

        token = await TokenBeanie.find_one(
            {
                "user_id": ObjectId(current_user.id),
                "expire_datetime": {"$gt": datetime.now()},
            }
        )
        if not token:
            raise HTTPException(status_code=404, detail="Valid token not found")

        # Prepare token data for localStorage
        token_data = token.model_dump(exclude_none=True)
        token_data["_id"] = str(token_data.pop("id", None))
        token_data["user_id"] = str(token_data["user_id"])
        token_data["logged_in"] = True

        # Convert datetime objects to strings
        if isinstance(token_data.get("expire_datetime"), datetime):
            token_data["expire_datetime"] = token_data["expire_datetime"].strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        if isinstance(token_data.get("created_at"), datetime):
            token_data["created_at"] = token_data["created_at"].strftime("%Y-%m-%d %H:%M:%S")

        token_data_json = json.dumps(token_data)
        logger.info(f"🔑 Token data prepared: {token_data}")

        async with async_playwright() as p:
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

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = await context.new_page()

            working_base_url = "http://depictio-frontend:5080"
            dashboard_url = f"{working_base_url}/dashboard/{dashboard_id}"

            logger.info("🚀 Step 1: Navigate to root page first")
            # First, go to the root page to establish session
            await page.goto(working_base_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            logger.info("🔑 Step 2: Set authentication in localStorage")
            # Set the authentication token
            await page.evaluate(f"""
                () => {{
                    localStorage.setItem('local-store', '{token_data_json}');
                    console.log('Token set in localStorage:', localStorage.getItem('local-store'));
                }}
            """)

            logger.info("🔄 Step 3: Navigate to dashboard with auth")
            # Now navigate to the dashboard
            await page.goto(dashboard_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Check if we're still on the auth page
            current_url = page.url
            logger.info(f"📍 Current URL after navigation: {current_url}")

            if "/auth" in current_url:
                logger.warning("⚠️ Still on auth page, trying additional auth methods...")

                # Try setting additional auth data
                await page.evaluate(f"""
                    () => {{
                        // Try different localStorage keys that might be used
                        localStorage.setItem('auth-token', '{token.access_token}');
                        localStorage.setItem('user-data', '{json.dumps(current_user.model_dump(exclude_none=True))}');
                        localStorage.setItem('authenticated', 'true');

                        // Also try sessionStorage
                        sessionStorage.setItem('local-store', '{token_data_json}');
                        sessionStorage.setItem('auth-token', '{token.access_token}');

                        console.log('Additional auth data set');
                    }}
                """)

                # Try reloading the page
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)

                # Try navigating to dashboard again
                await page.goto(dashboard_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                current_url = page.url
                logger.info(f"📍 URL after auth retry: {current_url}")

                # If still on auth page, try a different approach
                if "/auth" in current_url:
                    logger.warning("⚠️ Auth page persistent, trying direct dashboard access...")

                    # Try setting the URL directly and forcing navigation
                    await page.evaluate(f"""
                        () => {{
                            window.history.pushState(null, '', '{dashboard_url}');
                            window.location.href = '{dashboard_url}';
                        }}
                    """)
                    await asyncio.sleep(5)

            # Wait for dashboard content to load
            logger.info("⏳ Waiting for dashboard content...")
            try:
                # Wait for dashboard-specific content
                await page.wait_for_selector("div#page-content", timeout=15000)
                logger.info("✅ Found page-content div")
            except Exception:
                logger.warning("⚠️ page-content div not found, continuing...")

            # Give extra time for any dynamic content
            await asyncio.sleep(5)

            # Remove debug elements
            await page.evaluate("""
                () => {
                    const debugMenus = document.querySelectorAll('.dash-debug-menu, .dash-debug-menu__outer');
                    debugMenus.forEach(menu => menu.remove());
                }
            """)

            # Take screenshot
            logger.info("📸 Taking screenshot...")
            final_url = page.url

            try:
                # Try to screenshot the main content area
                element = await page.query_selector("div#page-content")
                if element and await element.is_visible():
                    await element.screenshot(path=output_file, type="png")
                    logger.info("📸 Screenshot of page-content taken")
                else:
                    # Fallback to full page
                    await page.screenshot(path=output_file, full_page=True, type="png")
                    logger.info("📸 Full page screenshot taken (fallback)")
            except Exception as e:
                logger.warning(f"⚠️ Screenshot error: {e}")
                await page.screenshot(path=output_file, full_page=True, type="png")
                logger.info("📸 Basic screenshot taken")

            await browser.close()

            # Verify screenshot was created
            if not Path(output_file).exists():
                raise HTTPException(status_code=500, detail="Screenshot file was not created")

            return {
                "success": True,
                "message": "Screenshot taken with fixed authentication",
                "dashboard_url": dashboard_url,
                "final_url": final_url,
                "redirected_to_auth": "/auth" in final_url,
                "screenshot_path": output_file,
                "screenshot_size": Path(output_file).stat().st_size,
                "auth_method": "localStorage with fallbacks",
                "timestamp": datetime.now().isoformat(),
            }

    except Exception as e:
        logger.error(f"❌ Screenshot failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")
