import asyncio
import json
from datetime import datetime
from pathlib import Path

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
from depictio.api.v1.endpoints.utils_endpoints.core_functions import (
    cleanup_orphaned_s3_files,
    create_bucket,
)
from depictio.api.v1.endpoints.utils_endpoints.infrastructure_diagnostics import (
    run_comprehensive_diagnostics,
)
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

    if response.status_code == 200:  # type: ignore[unresolved-attribute]
        logger.info(response.detail)  # type: ignore[unresolved-attribute]
        return response
    else:
        logger.error(response.detail)  # type: ignore[unresolved-attribute]
        raise HTTPException(status_code=response.status_code, detail=response.detail)  # type: ignore[unresolved-attribute]


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


@utils_endpoint_router.post("/cleanup-orphaned-s3-files")
async def cleanup_orphaned_s3_files_endpoint(
    dry_run: bool = True,
    force: bool = False,
    current_user: UserBeanie = Depends(get_current_user),
):
    """
    Clean up S3 files from data collections that no longer exist in MongoDB.

    This endpoint requires admin privileges.

    Args:
        dry_run: If True, only report what would be deleted without actually deleting (default: True)
        force: If True, bypass safety check when all prefixes appear orphaned (default: False)
        current_user: Authenticated user (must be admin)

    Returns:
        Cleanup results with statistics
    """
    # Validate user is an admin
    if not current_user.is_admin:
        logger.warning(f"Unauthorized S3 cleanup attempt by user: {current_user.email}")
        raise HTTPException(status_code=403, detail="Admin privileges required")

    logger.info(
        f"S3 cleanup requested by admin {current_user.email} (dry_run={dry_run}, force={force})"
    )

    results = await cleanup_orphaned_s3_files(dry_run=dry_run, force=force)

    return results


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
    url: str, max_retries: int | None = None, delay: int | None = None, timeout: int | None = None
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

    timeout_obj = httpx.Timeout(float(timeout_val))  # type: ignore[invalid-assignment]

    logger.info(
        f"🔍 Service readiness check starting for {url} (retries: {max_retries}, delay: {delay}s, timeout: {timeout_val}s)"
    )

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout_obj, verify=False) as client:
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


async def wait_for_network_idle(page, timeout: int = 30000) -> bool:
    """
    Wait for network to be idle (no ongoing requests) to ensure content is fully loaded.
    Based on the ERR_CONNECTION_TIMED_OUT error in logs.
    """
    try:
        logger.info("⏳ Waiting for network to be idle...")
        await page.wait_for_load_state("networkidle", timeout=timeout)
        logger.info("✅ Network is idle - all requests completed")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Network idle wait failed: {e}")
        return False


async def check_dashboard_health(page, url: str) -> tuple[bool, str]:
    """
    Check if dashboard is actually healthy and rendering properly.
    Based on log analysis showing dashboard content not loading.
    """
    try:
        # Check page title
        page_title = await page.title()
        current_url = page.url

        logger.info(f"🔍 Dashboard health check - Title: '{page_title}', URL: {current_url}")

        # Check for error indicators
        error_indicators = [
            ("title", "error", page_title.lower()),
            ("title", "404", page_title.lower()),
            ("title", "not found", page_title.lower()),
            # ("url", "auth", current_url.lower()),
            # ("url", "login", current_url.lower()),
            # ("url", "error", current_url.lower()),
        ]

        for check_type, error_text, content in error_indicators:
            if error_text in content:
                logger.error(
                    f"❌ Dashboard health check failed: {error_text} found in {check_type}"
                )
                return False, f"error_detected_{error_text}_in_{check_type}"

        # Check for loading spinners that might be stuck
        stuck_loading_selectors = [
            ".loading-spinner:not([style*='display: none'])",
            ".dash-loading:not([style*='display: none'])",
            "[data-dash-loading='true']",
        ]

        for selector in stuck_loading_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    logger.warning(f"⚠️ Found stuck loading indicator: {selector}")
                    return (
                        False,
                        f"stuck_loading_{selector.replace('[', '').replace(']', '').replace(':', '_')}",
                    )
            except Exception:
                continue

        # Check for JavaScript errors in console
        console_errors = []

        def log_js_error(msg):
            if msg.type in ["error", "warning"]:
                console_errors.append(f"{msg.type}: {msg.text}")

        page.on("console", log_js_error)
        await asyncio.sleep(2)  # Give time for console errors to appear
        page.remove_listener("console", log_js_error)

        if console_errors:
            logger.warning(
                f"⚠️ JavaScript errors detected: {console_errors[:3]}"
            )  # Log first 3 errors

        logger.info("✅ Dashboard health check passed")
        return True, "healthy"

    except Exception as e:
        logger.error(f"❌ Dashboard health check error: {e}")
        return False, f"health_check_failed_{str(e)[:50]}"


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

        # For dashboard pages, wait for main content with better error handling
        if "/dashboard/" in url:
            selectors_to_try = [
                ("div#page-content", "Main dashboard content"),
                ("div[data-dash-app]", "Dash app container"),
                ("div#app", "App container"),
                (".dash-renderer", "Dash renderer"),
                ("main", "Main content"),
                ("[data-testid='dashboard']", "Dashboard test ID"),
            ]

            dashboard_ready = False
            for selector, description in selectors_to_try:
                try:
                    # Wait for selector to be present and visible
                    await page.wait_for_selector(selector, state="visible", timeout=content_timeout)
                    logger.info(f"✅ Found dashboard content: {description} ({selector})")
                    dashboard_ready = True
                    break
                except Exception as e:
                    logger.info(f"⏳ {description} ({selector}) not found: {str(e)[:100]}")
                    continue

            if not dashboard_ready:
                logger.warning("⚠️ No dashboard content found, checking for loading states...")

                # Check if we're stuck in loading state
                loading_selectors = [
                    ".loading-spinner",
                    ".dash-loading",
                    "[data-dash-loading]",
                    ".spinner",
                ]

                for loading_selector in loading_selectors:
                    try:
                        loading_element = await page.query_selector(loading_selector)
                        if loading_element:
                            logger.warning(
                                f"⏳ Found loading indicator: {loading_selector}, waiting longer..."
                            )
                            await asyncio.sleep(
                                stabilization_wait * 2
                            )  # Wait longer for loading to complete
                            break
                    except Exception:
                        continue
                else:
                    # Check page source for debugging
                    page_title = await page.title()
                    current_url = page.url
                    logger.warning(
                        f"⚠️ Dashboard not loading properly. Title: '{page_title}', URL: {current_url}"
                    )

                    # Check if we're redirected to auth or error page
                    if "auth" in current_url.lower() or "login" in current_url.lower():
                        logger.error("❌ Redirected to auth page - authentication failed")
                        return False, "auth_redirect_detected"

                    # Fallback wait with longer duration for slow loading
                    logger.info("⏳ Using extended fallback wait for slow dashboard loading...")
                    await asyncio.sleep(stabilization_wait * 3)
        else:
            # For root pages, shorter wait
            await asyncio.sleep(
                stabilization_wait / 2
            )  # Half the stabilization wait for root pages

        # Phase 3: Wait for network to be idle (addresses ERR_CONNECTION_TIMED_OUT)
        logger.info("⏳ Phase 3: Waiting for network requests to complete...")
        network_idle = await wait_for_network_idle(page, content_timeout)

        if not network_idle:
            logger.warning("⚠️ Network not idle, but continuing with screenshot...")

        # Phase 4: Health check for dashboard (addresses content loading issues from logs)
        logger.info("⏳ Phase 4: Performing dashboard health check...")
        dashboard_healthy, health_status = await check_dashboard_health(page, url)

        if not dashboard_healthy:
            logger.error(f"❌ Dashboard health check failed: {health_status}")
            return False, f"health_check_failed_{health_status}"

        # Phase 5: Brief final wait for dynamic content (environment-specific)
        logger.info("⏳ Phase 5: Final wait for dynamic content...")
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
    Minimal screenshot endpoint - just take a full page screenshot
    """
    from playwright.async_api import async_playwright

    output_folder = "/app/depictio/dash/static/screenshots"
    output_file = f"{output_folder}/{str(dashboard_id)}.png"
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    try:
        # Get auth token
        current_user = await UserBeanie.find_one({"email": "admin@example.com"})
        if not current_user:
            raise HTTPException(status_code=404, detail="Admin user not found")

        token = await TokenBeanie.find_one(
            {
                "user_id": current_user.id,
                "refresh_expire_datetime": {"$gt": datetime.now()},
            }
        )
        if not token:
            raise HTTPException(status_code=404, detail="Valid token not found")

        # Prepare token data
        token_data = token.model_dump(exclude_none=True)
        token_data["_id"] = str(token_data.pop("id", None))
        token_data["user_id"] = str(token_data["user_id"])
        token_data["logged_in"] = True

        if isinstance(token_data.get("expire_datetime"), datetime):
            token_data["expire_datetime"] = token_data["expire_datetime"].strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        if isinstance(token_data.get("created_at"), datetime):
            token_data["created_at"] = token_data["created_at"].strftime("%Y-%m-%d %H:%M:%S")

        token_data_json = json.dumps(token_data)

        # Simple browser screenshot
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            dashboard_url = f"{settings.dash.internal_url}/dashboard/{dashboard_id}"
            logger.info(f"📸 Taking screenshot of: {dashboard_url}")

            # Set auth and navigate
            await page.goto(settings.dash.internal_url)
            await page.evaluate(f"localStorage.setItem('local-store', '{token_data_json}')")
            await page.goto(dashboard_url, timeout=30000)

            # Wait for dashboard content to render
            await page.wait_for_timeout(5000)

            # Wait for dashboard components to render with proper dimensions
            try:
                await page.wait_for_function(
                    """
                    () => {
                        const components = document.querySelectorAll('.react-grid-item');
                        if (components.length === 0) return false;

                        // Check if at least one component has meaningful dimensions
                        for (let component of components) {
                            const rect = component.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                return true;
                            }
                        }
                        return false;
                    }
                """,
                    timeout=10000,
                )
                logger.info("✅ Dashboard components rendered with proper dimensions")
            except Exception as e:
                logger.warning(f"⚠️ Timeout waiting for components to render: {e}")

            # Direct dashboard content targeting, excluding navbar and header
            try:
                # Hide navbar AND header elements, and adjust layout before screenshot
                await page.evaluate("""
                    () => {
                        // Hide navbar
                        const navbar = document.querySelector('.mantine-AppShell-navbar');
                        if (navbar) {
                            navbar.style.display = 'none';
                        }

                        // Hide header (badges, title, buttons)
                        const header = document.querySelector('.mantine-AppShell-header');
                        if (header) {
                            header.style.display = 'none';
                        }

                        // Remove any padding/margin from page-content to eliminate white space
                        const pageContent = document.querySelector('#page-content');
                        if (pageContent) {
                            pageContent.style.padding = '0';
                            pageContent.style.margin = '0';
                        }

                        // Remove padding from AppShell-main and ensure it takes full width
                        const appShellMain = document.querySelector('.mantine-AppShell-main');
                        if (appShellMain) {
                            appShellMain.style.padding = '0';
                            appShellMain.style.paddingLeft = '0';
                            appShellMain.style.margin = '0';
                        }
                    }
                """)

                # Simple approach: screenshot the AppShell-main element directly
                # This captures the full viewport content without navbar/header
                main_element = await page.query_selector(".mantine-AppShell-main")
                if main_element:
                    await main_element.screenshot(path=output_file)
                    logger.info("📸 Screenshot taken from .mantine-AppShell-main")
                    screenshot_taken = True
                else:
                    raise Exception("Could not find .mantine-AppShell-main element")

                if not screenshot_taken:
                    raise Exception("Screenshot was not taken")

            except Exception as e:
                logger.warning(f"Component-based screenshot failed: {e}, trying fallback")
                # Fallback to AppShell main
                try:
                    main_element = await page.query_selector(".mantine-AppShell-main")
                    if main_element:
                        await main_element.screenshot(path=output_file)
                        logger.info("📸 AppShell main screenshot taken (fallback)")
                    else:
                        # Final fallback to full page
                        await page.screenshot(path=output_file, full_page=True)
                        logger.info("📸 Full page screenshot taken (final fallback)")
                except Exception as fallback_e:
                    logger.warning(f"All screenshot methods failed: {fallback_e}")
                    await page.screenshot(path=output_file, full_page=True)

            await browser.close()
            logger.info("📸 Screenshot taken")

        return {
            "success": True,
            "message": f"Screenshot saved to {output_file}",
            "screenshot_path": output_file,
        }

    except Exception as e:
        logger.error(f"❌ Screenshot error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")


@utils_endpoint_router.get("/infrastructure-diagnostics")
async def infrastructure_diagnostics(current_user=Depends(get_current_user)):
    """
    Run comprehensive infrastructure diagnostics to identify performance bottlenecks.

    This endpoint helps identify the root cause of screenshot performance issues by testing:
    - DNS resolution performance
    - Network latency between services
    - Browser performance in container environment
    - System resource constraints
    - Storage I/O performance

    Use this to compare performance between working (laptop/minikube) and problematic
    (production K8s) environments.
    """
    if not current_user:
        logger.error("Current user not found.")
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Only allow admin users to run diagnostics
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required for diagnostics.")

    try:
        logger.info("🔍 Starting infrastructure diagnostics requested by admin...")
        diagnostics = await run_comprehensive_diagnostics()

        # Log summary for immediate visibility
        summary = diagnostics.get("summary", {})
        if summary.get("issues_found"):
            logger.warning(f"⚠️ Infrastructure issues detected: {summary['issues_found']}")
        else:
            logger.info("✅ No infrastructure issues detected")

        return {
            "success": True,
            "message": "Infrastructure diagnostics completed",
            "diagnostics": diagnostics,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"❌ Infrastructure diagnostics failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Diagnostics failed: {str(e)}")
