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
        logger.info(f"Deleting {len(objects_to_delete['Contents'])} objects...")
        delete_keys = [{"Key": obj["Key"]} for obj in objects_to_delete["Contents"]]
        s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_keys})
        objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)

    logger.info("All objects deleted from the bucket.")

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


async def check_service_readiness(
    url: str, max_retries: int = None, delay: int = None, timeout: int = None
) -> bool:
    """
    Check if a service is ready to serve requests with retry logic.
    Similar to the init container pattern used in deployments.
    Uses environment-specific performance settings.
    """
    import httpx

    # Use environment-specific settings or fallback to defaults
    max_retries = max_retries or settings.performance.service_readiness_retries
    delay = delay or settings.performance.service_readiness_delay
    timeout_val = timeout or settings.performance.service_readiness_timeout

    timeout = httpx.Timeout(float(timeout_val))

    logger.info(
        f"🔍 Service readiness check starting for {url} (retries: {max_retries}, delay: {delay}s, timeout: {timeout_val}s)"
    )

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                response = await client.get(url)
                logger.info(
                    f"🔍 Service readiness check attempt {attempt + 1}: {url} -> {response.status_code}"
                )
                if response.status_code < 500:  # Accept any non-server error status
                    logger.info(f"✅ Service is ready: {url}")
                    return True
        except Exception as e:
            logger.warning(f"⚠️ Service readiness check attempt {attempt + 1} failed: {e}")

        if attempt < max_retries - 1:
            logger.info(f"⏳ Waiting {delay}s before retry...")
            await asyncio.sleep(delay)

    logger.error(f"❌ Service readiness check failed after {max_retries} attempts: {url}")
    return False


async def capture_network_activity(page, duration_ms: int = 5000):
    """
    Capture network activity for debugging slow page loads.
    """
    network_logs = []

    def log_request(request):
        network_logs.append(
            {
                "type": "request",
                "url": request.url,
                "method": request.method,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def log_response(response):
        network_logs.append(
            {
                "type": "response",
                "url": response.url,
                "status": response.status,
                "timestamp": datetime.now().isoformat(),
            }
        )

    page.on("request", log_request)
    page.on("response", log_response)

    # Wait and capture network activity
    await asyncio.sleep(duration_ms / 1000)

    # Log summary
    requests = [log for log in network_logs if log["type"] == "request"]
    responses = [log for log in network_logs if log["type"] == "response"]

    logger.info(
        f"📊 Network activity captured: {len(requests)} requests, {len(responses)} responses"
    )
    for req in requests[:5]:  # Log first 5 requests
        logger.info(f"🌐 Request: {req['method']} {req['url']}")

    return network_logs


async def navigate_for_screenshot(page, url: str) -> tuple[bool, str]:
    """
    Navigate specifically optimized for screenshot generation.
    Uses environment-specific performance settings for production optimization.

    Strategy: Skip complex wait strategies and use a content-based approach:
    1. Navigate with minimal wait
    2. Wait for specific DOM elements that indicate page is ready for screenshot
    3. Much faster than waiting for full resource loading
    """
    logger.info(f"📸 Using screenshot-optimized navigation for: {url}")

    # Use environment-specific timeouts
    nav_timeout = settings.performance.screenshot_navigation_timeout
    content_timeout = settings.performance.screenshot_content_wait
    stabilization_wait = (
        settings.performance.screenshot_stabilization_wait / 1000
    )  # Convert ms to seconds

    logger.info(
        f"🎯 Performance settings - Nav: {nav_timeout}ms, Content: {content_timeout}ms, Stabilization: {stabilization_wait}s"
    )

    try:
        # Phase 1: Quick navigation without waiting for full load
        logger.info("⚡ Phase 1: Quick navigation with 'commit' wait strategy...")
        start_time = datetime.now()

        await page.goto(
            url, timeout=nav_timeout, wait_until="commit"
        )  # Just wait for navigation to commit
        navigation_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"⏱️ Navigation committed in {navigation_time:.2f} seconds")

        # Phase 2: Wait for essential content to appear (much faster than full page load)
        logger.info("⏳ Phase 2: Waiting for essential dashboard content...")

        # Wait for basic page structure with environment-specific timeout
        await page.wait_for_selector("body", timeout=content_timeout)
        logger.info("✅ Page body loaded")

        # For dashboard pages, wait for main content
        if "/dashboard/" in url:
            selectors_to_try = [
                "div#page-content",  # Main content div
                "div[data-dash-app]",  # Dash app container
                "div#app",  # Alternative app container
                "main",  # Generic main content
            ]

            for selector in selectors_to_try:
                try:
                    await page.wait_for_selector(selector, timeout=content_timeout)
                    logger.info(f"✅ Found dashboard content: {selector}")
                    break
                except Exception:
                    logger.info(f"⏳ Selector {selector} not found, trying next...")
                    continue
            else:
                logger.warning("⚠️ No specific dashboard content found, using fallback wait")
                await asyncio.sleep(stabilization_wait)  # Use environment-specific fallback wait
        else:
            # For root pages, shorter wait
            await asyncio.sleep(
                stabilization_wait / 2
            )  # Half the stabilization wait for root pages

        # Phase 3: Brief wait for dynamic content (environment-specific)
        logger.info("⏳ Phase 3: Brief wait for dynamic content...")
        await asyncio.sleep(stabilization_wait)

        total_time = (datetime.now() - start_time).total_seconds()
        success_method = f"screenshot_optimized_total_{total_time:.1f}s"
        logger.info(f"✅ Screenshot-optimized navigation completed in {total_time:.2f}s")

        return True, success_method

    except Exception as e:
        logger.error(f"❌ Screenshot-optimized navigation failed: {e}")
        return False, f"screenshot_navigation_failed_{str(e)[:50]}"


async def navigate_with_hybrid_strategy(page, url: str, max_retries: int = 2) -> tuple[bool, str]:
    """
    Navigate to URL with hybrid approach: optimized strategies first, proven fallbacks second.
    Returns (success, method_used)
    Uses environment-specific performance settings for production optimization.

    Strategy:
    1. Try optimized page-specific strategies (fast)
    2. If all fail, fall back to proven working methods (slower but reliable)
    3. Capture network activity to debug slow loads
    """
    # Use environment-specific timeouts
    nav_timeout = settings.performance.browser_navigation_timeout
    page_load_timeout = settings.performance.browser_page_load_timeout

    # Phase 1: Optimized strategies based on URL pattern (environment-aware)
    if "/dashboard/" in url:
        optimized_strategies = [
            ("domcontentloaded", nav_timeout),  # Fast for dashboard pages
            ("load", nav_timeout + 15000),  # Quick fallback with buffer
        ]
        page_type = "dashboard"
    else:
        optimized_strategies = [
            ("load", nav_timeout),  # Primary for root pages
            ("domcontentloaded", nav_timeout - 15000),  # Quick fallback
        ]
        page_type = "root"

    # Phase 2: Proven fallback strategies (environment-aware for production)
    proven_strategies = [
        ("load", page_load_timeout),  # Use environment-specific page load timeout
        ("domcontentloaded", page_load_timeout - 30000),  # Shorter fallback
    ]

    logger.info(f"🎯 Using hybrid navigation for {page_type} page: {url}")

    # Phase 1: Try optimized strategies
    logger.info("⚡ Phase 1: Trying optimized strategies...")
    for retry in range(max_retries):
        for i, (wait_until, timeout) in enumerate(optimized_strategies):
            try:
                logger.info(
                    f"🌐 Optimized attempt {retry + 1}, strategy {i + 1}: {wait_until} (timeout: {timeout}ms)"
                )

                # Capture timing information
                start_time = datetime.now()
                await page.goto(url, timeout=timeout, wait_until=wait_until)
                navigation_time = (datetime.now() - start_time).total_seconds()

                logger.info(
                    f"⏱️ Navigation took {navigation_time:.2f} seconds to reach {wait_until} state"
                )
                success_method = f"{page_type}_optimized_retry_{retry + 1}_strategy_{wait_until}_timeout_{timeout}ms"
                logger.info(f"✅ Successfully navigated with optimized strategy: {success_method}")

                # Capture post-navigation network activity to debug slow loads
                logger.info("🔍 Capturing post-navigation network activity...")
                await capture_network_activity(page, duration_ms=10000)

                return True, success_method
            except Exception as e:
                logger.warning(f"⚠️ Optimized navigation failed with {wait_until}: {e}")
                if "timeout" in str(e).lower():
                    logger.info("⏳ Timeout detected, trying next optimized strategy...")
                    continue
                else:
                    logger.warning(f"❌ Non-timeout error in optimized strategy: {e}")
                    break

        if retry < max_retries - 1:
            logger.info(f"🔄 Retrying optimized strategies {retry + 2}/{max_retries}...")
            await asyncio.sleep(2)

    # Phase 2: Fall back to proven strategies
    logger.warning("🛡️ Phase 2: Optimized strategies failed, trying proven fallback strategies...")
    for i, (wait_until, timeout) in enumerate(proven_strategies):
        try:
            logger.info(f"🌐 Proven fallback strategy {i + 1}: {wait_until} (timeout: {timeout}ms)")
            await page.goto(url, timeout=timeout, wait_until=wait_until)
            success_method = (
                f"{page_type}_proven_fallback_strategy_{wait_until}_timeout_{timeout}ms"
            )
            logger.info(f"✅ Successfully navigated with proven fallback: {success_method}")

            # Capture post-navigation network activity to debug slow loads
            logger.info("🔍 Capturing post-navigation network activity...")
            await capture_network_activity(page, duration_ms=10000)
            return True, success_method
        except Exception as e:
            logger.warning(f"⚠️ Proven strategy failed with {wait_until}: {e}")
            continue

    logger.error(f"❌ All navigation strategies (optimized + proven) failed for {url}")
    return False, "all_strategies_failed"


@utils_endpoint_router.get("/screenshot-dash-fixed/{dashboard_id}")
async def screenshot_dash_fixed(dashboard_id: str = "6824cb3b89d2b72169309737"):
    """
    Fixed screenshot endpoint with proper authentication handling, retries, and service readiness checks
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

        logger.info(f"🔑 Current user: {current_user.email} ; {current_user.id}")

        # Fetch all  tokens for the current user
        logger.info("🔑 Fetching all tokens for the current user...")
        tokens = await TokenBeanie.find({"user_id": ObjectId(current_user.id)}).to_list()
        logger.info(f"🔑 Found {len(tokens)} tokens for user {current_user.email}")
        for token in tokens:
            logger.info(f"🔑 Token: {token.access_token} ; Expire: {token.expire_datetime}")

        # Show current datetime for debugging
        logger.info(f"🔑 Current datetime: {datetime.now()}")

        logger.info(
            f"🔑 Current datetime strftime : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        token = await TokenBeanie.find_one(
            {
                "user_id": ObjectId(current_user.id),
                "expire_datetime": {"$gt": datetime.now()},
            }
        )

        logger.info(f"🔑 Selected token: {token.access_token if token else 'None'}")
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

            # Set up console and error logging
            def log_console(msg):
                logger.info(f"🖥️ Browser Console [{msg.type}]: {msg.text}")

            def log_page_error(error):
                logger.error(f"❌ Browser Error: {error}")

            page.on("console", log_console)
            page.on("pageerror", log_page_error)

            working_base_url = settings.dash.internal_url
            # working_base_url = "http://depictio-frontend:5080"
            dashboard_url = f"{working_base_url}/dashboard/{dashboard_id}"

            # Step 0: Check service readiness before attempting screenshot (environment-aware)
            logger.info("🔍 Step 0: Checking service readiness...")
            if not await check_service_readiness(working_base_url):
                raise HTTPException(
                    status_code=503, detail=f"Frontend service not ready: {working_base_url}"
                )

            logger.info("🚀 Step 1: Navigate to root page first")
            # First, go to the root page to establish session with screenshot-optimized navigation
            root_success, root_method = await navigate_for_screenshot(page, working_base_url)
            if not root_success:
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to navigate to frontend service: {working_base_url}",
                )
            logger.info(f"📊 Root navigation successful with: {root_method}")
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
            # Now navigate to the dashboard with screenshot-optimized navigation
            dashboard_success, dashboard_method = await navigate_for_screenshot(page, dashboard_url)
            if not dashboard_success:
                logger.warning("⚠️ Failed to navigate to dashboard, attempting fallback methods...")
                # Fallback: try basic navigation without retries
                try:
                    await page.goto(
                        dashboard_url, timeout=120000, wait_until="domcontentloaded"
                    )  # Longer timeout
                    dashboard_method = "fallback_basic_navigation_120s_timeout"
                    logger.info(
                        f"📊 Dashboard navigation successful with fallback: {dashboard_method}"
                    )
                except Exception as e:
                    logger.error(f"❌ Dashboard navigation failed completely: {e}")
                    raise HTTPException(
                        status_code=503, detail=f"Failed to navigate to dashboard: {dashboard_url}"
                    )
            else:
                logger.info(f"📊 Dashboard navigation successful with: {dashboard_method}")
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

                # Try navigating to dashboard again with hybrid strategy
                retry_success, retry_method = await navigate_with_hybrid_strategy(
                    page, dashboard_url, max_retries=1
                )
                if not retry_success:
                    logger.warning("⚠️ Retry navigation to dashboard failed")
                else:
                    logger.info(f"📊 Retry navigation successful with: {retry_method}")
                    dashboard_method = f"auth_retry_{retry_method}"
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

            # Wait for dashboard content to load with environment-specific timeouts
            logger.info("⏳ Waiting for dashboard content...")
            element_timeout = settings.performance.browser_element_timeout
            stabilization_wait = (
                settings.performance.screenshot_stabilization_wait / 1000
            )  # Convert ms to seconds

            try:
                # Wait for dashboard-specific content with environment-specific timeout
                await page.wait_for_selector("div#page-content", timeout=element_timeout)
                logger.info("✅ Found page-content div")
            except Exception:
                logger.warning("⚠️ page-content div not found, trying alternative selectors...")
                # Try waiting for other common dashboard elements
                alternative_selectors = ["div#app", "div[data-dash-app]", "body"]
                for selector in alternative_selectors:
                    try:
                        await page.wait_for_selector(
                            selector, timeout=element_timeout // 3
                        )  # Shorter timeout for alternatives
                        logger.info(f"✅ Found alternative selector: {selector}")
                        break
                    except Exception:
                        continue
                else:
                    logger.warning("⚠️ No dashboard elements found, continuing anyway...")

            # Give extra time for any dynamic content to load (environment-specific)
            logger.info("⏳ Waiting for dynamic content to stabilize...")
            await asyncio.sleep(
                stabilization_wait * 2
            )  # Double stabilization wait for final content

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
                "message": "Screenshot taken with improved resilience and retry logic",
                "dashboard_url": dashboard_url,
                "final_url": final_url,
                "redirected_to_auth": "/auth" in final_url,
                "screenshot_path": output_file,
                "screenshot_size": Path(output_file).stat().st_size,
                "auth_method": "localStorage with fallbacks",
                "navigation_methods": {
                    "root_navigation": root_method,
                    "dashboard_navigation": dashboard_method,
                },
                "timestamp": datetime.now().isoformat(),
            }

    except Exception as e:
        logger.error(f"❌ Screenshot failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")
