"""
Infrastructure Diagnostics for Screenshot Performance Issues

This module provides comprehensive diagnostics to identify infrastructure bottlenecks
that cause screenshot performance degradation in production Kubernetes environments.
"""

import asyncio
import os
import socket
import time
from datetime import datetime
from typing import Dict

import httpx
from playwright.async_api import async_playwright

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


async def test_dns_resolution() -> Dict[str, any]:
    """Test DNS resolution performance for internal services."""
    dns_results = {}

    # Get actual service names from settings and environment
    services_to_test = [
        f"{settings.dash.service_name}",
        f"{settings.fastapi.service_name}",
        f"{settings.mongodb.service_name}",
        f"{settings.minio.service_name}",
    ]

    # Also try common service patterns in case settings are different
    additional_services = [
        "depictio-frontend",
        "depictio-backend",
        "mongo",
        "minio",
    ]

    # Combine and deduplicate
    all_services = list(set(services_to_test + additional_services))

    for service in all_services:
        start_time = time.time()
        try:
            # Test DNS resolution
            addr_info = socket.getaddrinfo(service, None)
            dns_time = (time.time() - start_time) * 1000  # Convert to ms

            dns_results[service] = {
                "status": "success",
                "resolution_time_ms": dns_time,
                "resolved_addresses": [addr[4][0] for addr in addr_info[:3]],  # First 3 IPs
            }
            logger.info(f"🔍 DNS {service}: {dns_time:.2f}ms -> {addr_info[0][4][0]}")

        except Exception as e:
            dns_results[service] = {
                "status": "failed",
                "error": str(e),
                "resolution_time_ms": (time.time() - start_time) * 1000,
            }
            logger.error(f"❌ DNS {service}: {e}")

    return dns_results


async def test_network_latency() -> Dict[str, any]:
    """Test network latency to internal services."""
    latency_results = {}

    services_to_test = [
        (settings.dash.internal_url, "frontend"),
        (settings.fastapi.internal_url, "backend"),
        ("http://mongo:27018", "mongodb"),
        ("http://minio:9000", "minio"),
    ]

    timeout = httpx.Timeout(10.0)

    for url, service_name in services_to_test:
        latencies = []

        # Test 5 times for average
        for i in range(5):
            start_time = time.time()
            try:
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    response = await client.get(url)
                    latency = (time.time() - start_time) * 1000
                    latencies.append(latency)
                    logger.info(
                        f"🔍 Latency {service_name} #{i + 1}: {latency:.2f}ms -> {response.status_code}"
                    )

            except Exception as e:
                latency = (time.time() - start_time) * 1000
                latencies.append(None)
                logger.warning(f"⚠️ Latency {service_name} #{i + 1}: {e}")

            await asyncio.sleep(0.5)  # Small delay between tests

        valid_latencies = [lat for lat in latencies if lat is not None]
        latency_results[service_name] = {
            "successful_requests": len(valid_latencies),
            "failed_requests": len([lat for lat in latencies if lat is None]),
            "avg_latency_ms": sum(valid_latencies) / len(valid_latencies)
            if valid_latencies
            else None,
            "min_latency_ms": min(valid_latencies) if valid_latencies else None,
            "max_latency_ms": max(valid_latencies) if valid_latencies else None,
            "all_latencies": latencies,
        }

    return latency_results


async def test_browser_performance() -> Dict[str, any]:
    """Test browser startup and basic performance in the container environment."""
    browser_results = {}

    try:
        logger.info("🔍 Testing browser startup performance...")

        # Test browser startup time
        browser_start = time.time()
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
            browser_startup_time = (time.time() - browser_start) * 1000

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = await context.new_page()

            # Test simple page load
            simple_load_start = time.time()
            await page.goto("data:text/html,<html><body><h1>Test</h1></body></html>")
            simple_load_time = (time.time() - simple_load_start) * 1000

            # Test screenshot performance
            screenshot_start = time.time()
            await page.screenshot(path="/tmp/test_screenshot.png", type="png")
            screenshot_time = (time.time() - screenshot_start) * 1000

            await browser.close()

            browser_results = {
                "browser_startup_ms": browser_startup_time,
                "simple_page_load_ms": simple_load_time,
                "screenshot_capture_ms": screenshot_time,
                "total_browser_test_ms": (time.time() - browser_start) * 1000,
            }

            logger.info(f"✅ Browser startup: {browser_startup_time:.2f}ms")
            logger.info(f"✅ Simple load: {simple_load_time:.2f}ms")
            logger.info(f"✅ Screenshot: {screenshot_time:.2f}ms")

    except Exception as e:
        browser_results = {"error": str(e)}
        logger.error(f"❌ Browser performance test failed: {e}")

    return browser_results


async def test_resource_constraints() -> Dict[str, any]:
    """Test system resource availability and constraints."""
    resource_results = {}

    try:
        # Try to use psutil if available, otherwise use basic system info
        try:
            import psutil

            # CPU information
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory information
            memory = psutil.virtual_memory()

            # Disk information
            disk = psutil.disk_usage("/")

            resource_results.update(
                {
                    "cpu_cores": cpu_count,
                    "cpu_usage_percent": cpu_percent,
                    "memory_total_gb": memory.total / (1024**3),
                    "memory_available_gb": memory.available / (1024**3),
                    "memory_usage_percent": memory.percent,
                    "disk_total_gb": disk.total / (1024**3),
                    "disk_free_gb": disk.free / (1024**3),
                    "disk_usage_percent": (disk.used / disk.total) * 100,
                }
            )

            logger.info(
                f"🔍 Resources - CPU: {cpu_count} cores ({cpu_percent}%), Memory: {memory.available / (1024**3):.1f}GB available"
            )

        except ImportError:
            logger.warning("⚠️ psutil not available, using basic resource detection")

            # Basic CPU detection
            try:
                with open("/proc/cpuinfo", "r") as f:
                    cpu_count = f.read().count("processor")
                resource_results["cpu_cores"] = cpu_count
            except Exception:
                resource_results["cpu_cores"] = "unknown"

            # Basic memory detection
            try:
                with open("/proc/meminfo", "r") as f:
                    meminfo = f.read()
                    for line in meminfo.split("\n"):
                        if "MemTotal:" in line:
                            total_kb = int(line.split()[1])
                            resource_results["memory_total_gb"] = total_kb / (1024**2)
                        elif "MemAvailable:" in line:
                            available_kb = int(line.split()[1])
                            resource_results["memory_available_gb"] = available_kb / (1024**2)
            except Exception:
                resource_results["memory_total_gb"] = "unknown"
                resource_results["memory_available_gb"] = "unknown"

        # Container limits (if available)
        memory_limit = None
        cpu_limit = None

        try:
            # Try to read cgroup limits
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
                memory_limit = int(f.read().strip())
                if memory_limit >= 2**63 - 1:  # Unlimited
                    memory_limit = None
        except Exception:
            pass

        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r") as f:
                quota = int(f.read().strip())
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r") as f:
                period = int(f.read().strip())
            if quota > 0:
                cpu_limit = quota / period
        except Exception:
            pass

        resource_results.update(
            {
                "cpu_limit": cpu_limit,
                "memory_limit_gb": memory_limit / (1024**3) if memory_limit else None,
            }
        )

    except Exception as e:
        resource_results = {"error": str(e)}
        logger.error(f"❌ Resource constraint test failed: {e}")

    return resource_results


async def test_storage_performance() -> Dict[str, any]:
    """Test storage I/O performance for screenshot operations."""
    storage_results = {}

    try:
        test_file = "/tmp/storage_test.bin"
        test_size = 10 * 1024 * 1024  # 10MB test file

        # Write test
        write_start = time.time()
        with open(test_file, "wb") as f:
            f.write(b"0" * test_size)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        write_time = (time.time() - write_start) * 1000

        # Read test
        read_start = time.time()
        with open(test_file, "rb") as f:
            _ = f.read()  # Read but don't store data
        read_time = (time.time() - read_start) * 1000

        # Delete test
        delete_start = time.time()
        os.unlink(test_file)
        delete_time = (time.time() - delete_start) * 1000

        storage_results = {
            "write_10mb_ms": write_time,
            "read_10mb_ms": read_time,
            "delete_ms": delete_time,
            "write_speed_mbps": (test_size / (1024 * 1024)) / (write_time / 1000),
            "read_speed_mbps": (test_size / (1024 * 1024)) / (read_time / 1000),
        }

        logger.info(f"🔍 Storage - Write: {write_time:.2f}ms, Read: {read_time:.2f}ms")

    except Exception as e:
        storage_results = {"error": str(e)}
        logger.error(f"❌ Storage performance test failed: {e}")

    return storage_results


async def run_comprehensive_diagnostics() -> Dict[str, any]:
    """Run all diagnostic tests and return comprehensive results."""
    logger.info("🚀 Starting comprehensive infrastructure diagnostics...")

    start_time = datetime.now()

    # Run all tests
    dns_results = await test_dns_resolution()
    latency_results = await test_network_latency()
    browser_results = await test_browser_performance()
    resource_results = await test_resource_constraints()
    storage_results = await test_storage_performance()

    total_time = (datetime.now() - start_time).total_seconds()

    diagnostics = {
        "timestamp": start_time.isoformat(),
        "total_diagnostic_time_seconds": total_time,
        "environment": {
            "kubernetes_namespace": os.getenv("KUBERNETES_NAMESPACE", "unknown"),
            "pod_name": os.getenv("HOSTNAME", "unknown"),
            "node_name": os.getenv("KUBERNETES_NODE_NAME", "unknown"),
        },
        "dns_resolution": dns_results,
        "network_latency": latency_results,
        "browser_performance": browser_results,
        "resource_constraints": resource_results,
        "storage_performance": storage_results,
    }

    logger.info(f"✅ Comprehensive diagnostics completed in {total_time:.2f}s")

    # Generate summary
    issues_found = []

    # Check for DNS issues
    dns_failures = [k for k, v in dns_results.items() if v.get("status") == "failed"]
    if dns_failures:
        issues_found.append(f"DNS resolution failures: {dns_failures}")

    slow_dns = [k for k, v in dns_results.items() if v.get("resolution_time_ms", 0) > 1000]
    if slow_dns:
        issues_found.append(f"Slow DNS resolution (>1s): {slow_dns}")

    # Check for network latency issues
    for service, data in latency_results.items():
        avg_latency = data.get("avg_latency_ms", 0)
        if avg_latency and avg_latency > 5000:  # >5s average
            issues_found.append(f"High network latency to {service}: {avg_latency:.0f}ms avg")
        if data.get("failed_requests", 0) > 0:
            issues_found.append(
                f"Network failures to {service}: {data['failed_requests']}/5 requests failed"
            )

    # Check for browser performance issues
    browser_startup = browser_results.get("browser_startup_ms", 0)
    if browser_startup and browser_startup > 10000:  # >10s startup
        issues_found.append(f"Slow browser startup: {browser_startup:.0f}ms")

    # Check for resource constraints
    memory_usage = resource_results.get("memory_usage_percent", 0)
    cpu_usage = resource_results.get("cpu_usage_percent", 0)
    if memory_usage and memory_usage > 90:
        issues_found.append(f"High memory usage: {memory_usage:.1f}%")
    if cpu_usage and cpu_usage > 90:
        issues_found.append(f"High CPU usage: {cpu_usage:.1f}%")

    # Check for storage performance issues
    write_time = storage_results.get("write_10mb_ms", 0)
    if write_time and write_time > 5000:  # >5s for 10MB write
        issues_found.append(f"Slow storage write: {write_time:.0f}ms for 10MB")

    diagnostics["summary"] = {
        "issues_found": issues_found,
        "total_issues": len(issues_found),
        "overall_health": "degraded" if issues_found else "healthy",
    }

    return diagnostics
