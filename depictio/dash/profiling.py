"""
Performance profiling utilities for the Depictio Dash application.

This module provides tools to profile Dash app performance using various methods:
- Werkzeug ProfilerMiddleware for request profiling
- cProfile for function-level profiling
- Memory profiling capabilities
- Performance monitoring utilities

Usage:
    Set environment variable DEPICTIO_PROFILING_ENABLED=True to enable profiling

    Available environment variables:
    - DEPICTIO_PROFILING_ENABLED: Enable profiling (default: False)
    - DEPICTIO_PROFILING_PROFILE_DIR: Directory to save profile files (default: ./prof_files)
    - DEPICTIO_PROFILING_SORT_BY: Sorting criteria (default: cumtime,tottime)
    - DEPICTIO_PROFILING_RESTRICTIONS: Number of top functions to show (default: 50)
    - DEPICTIO_PROFILING_MEMORY_PROFILING: Enable memory profiling (default: False)
    - DEPICTIO_PROFILING_WERKZEUG_ENABLED: Enable Werkzeug request profiling (default: True)
    - DEPICTIO_PROFILING_PROFILE_CALLBACKS: Enable automatic callback profiling (default: False)
"""

import cProfile
import os
import pstats
import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Optional

from depictio.api.v1.configs.logging_init import logger

try:
    from werkzeug.middleware.profiler import ProfilerMiddleware

    WERKZEUG_AVAILABLE = True
except ImportError:
    WERKZEUG_AVAILABLE = False
    logger.warning("Werkzeug not available for profiling. Install with: pip install werkzeug")

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available for memory profiling. Install with: pip install psutil")


class DashProfiler:
    """Main profiling class for Dash applications."""

    def __init__(self, config=None):
        if config is None:
            from depictio.api.v1.configs.config import settings

            config = settings.profiling

        self.config = config
        self.profile_dir = config.profile_path
        self.sort_by = config.sort_criteria
        self.restrictions = config.restrictions
        self.memory_profiling = config.memory_profiling

        # Create profile directory
        self.profile_dir.mkdir(exist_ok=True)

        logger.info("Dash profiler initialized:")
        logger.info(f"  Profile directory: {self.profile_dir}")
        logger.info(f"  Sort by: {self.sort_by}")
        logger.info(f"  Restrictions: {self.restrictions}")
        logger.info(f"  Memory profiling: {self.memory_profiling}")
        logger.info(f"  Werkzeug enabled: {config.werkzeug_enabled}")
        logger.info(f"  Callback profiling: {config.profile_callbacks}")

    def setup_werkzeug_profiler(self, app):
        """Setup Werkzeug middleware profiler for the Flask server."""
        global _werkzeug_profiler_active

        if not self.config.werkzeug_enabled:
            logger.info("Werkzeug profiling disabled in configuration")
            return app

        if not WERKZEUG_AVAILABLE:
            logger.error("Werkzeug not available. Cannot setup request profiling.")
            return app

        # Global check for active Werkzeug profiler
        if _werkzeug_profiler_active:
            logger.warning("Werkzeug profiler already active globally, skipping...")
            return app

        # Check if profiling middleware is already setup on this app
        if hasattr(app.server, "_profiler_middleware_setup"):
            logger.warning("Werkzeug profiler middleware already setup on this app, skipping...")
            return app

        # Check if Flask's PROFILE is already set (could indicate another profiler)
        if app.server.config.get("PROFILE", False):
            logger.warning("Flask PROFILE already enabled, another profiler may be active")
            return app

        try:
            logger.info("Setting up Werkzeug ProfilerMiddleware...")

            # Test for profiler conflicts if in safe mode
            if self.config.werkzeug_safe_mode:
                # Try to create a test profiler to check for conflicts
                import cProfile

                test_profiler = cProfile.Profile()
                try:
                    test_profiler.enable()
                    test_profiler.disable()
                except ValueError as ve:
                    if "Another profiling tool is already active" in str(ve):
                        logger.warning(
                            "Profiler conflict detected. Disabling Werkzeug profiling to avoid errors."
                        )
                        logger.info(
                            "To force enable: Set DEPICTIO_PROFILING_WERKZEUG_SAFE_MODE=false"
                        )
                        return app
                    else:
                        raise ve

            # Store the original WSGI app
            original_wsgi_app = app.server.wsgi_app

            # Create the profiler middleware
            profiler_middleware = ProfilerMiddleware(
                original_wsgi_app,
                sort_by=self.sort_by,
                restrictions=[self.restrictions],
                stream=None if not self.config.werkzeug_stream else None,
                profile_dir=str(self.profile_dir),
            )

            app.server.config["PROFILE"] = True
            app.server.wsgi_app = profiler_middleware

            # Mark that we've setup the profiler middleware
            app.server._profiler_middleware_setup = True
            _werkzeug_profiler_active = True

            logger.info(
                f"✅ Werkzeug profiler enabled. Profile files will be saved to: {self.profile_dir}"
            )

        except Exception as e:
            logger.error(f"Failed to setup Werkzeug profiler: {e}")
            if "Another profiling tool is already active" in str(e):
                logger.warning(
                    "Profiler conflict detected. Try setting DEPICTIO_PROFILING_WERKZEUG_ENABLED=false"
                )
            logger.info("Continuing without Werkzeug profiling...")
            # Reset any partial setup
            _werkzeug_profiler_active = False
            if hasattr(app.server, "_profiler_middleware_setup"):
                delattr(app.server, "_profiler_middleware_setup")
            app.server.config.pop("PROFILE", None)

        return app

    @contextmanager
    def profile_function(self, func_name: str):
        """Context manager to profile a specific function or code block."""
        profiler = cProfile.Profile()
        start_time = time.time()

        if self.memory_profiling and PSUTIL_AVAILABLE:
            process = psutil.Process()
            start_memory = process.memory_info().rss / 1024 / 1024  # MB

        profiler.enable()
        try:
            yield
        finally:
            profiler.disable()
            end_time = time.time()

            # Save profile data
            profile_file = self.profile_dir / f"{func_name}_{int(time.time())}.prof"
            profiler.dump_stats(str(profile_file))

            # Generate text report
            stats = pstats.Stats(profiler)
            stats.sort_stats(*self.sort_by)
            stats.strip_dirs()

            report_file = self.profile_dir / f"{func_name}_{int(time.time())}.txt"
            with open(report_file, "w") as f:
                f.write(f"Profile Report for: {func_name}\n")
                f.write(f"Execution time: {end_time - start_time:.4f}s\n")

                if self.memory_profiling and PSUTIL_AVAILABLE:
                    end_memory = process.memory_info().rss / 1024 / 1024  # MB
                    f.write(f"Memory usage: {end_memory - start_memory:.2f}MB change\n")

                f.write("\n" + "=" * 80 + "\n")
                # Redirect stats output to file
                import sys

                old_stdout = sys.stdout
                sys.stdout = f
                try:
                    stats.print_stats(self.restrictions)
                finally:
                    sys.stdout = old_stdout

            logger.info(f"Profile saved: {profile_file}")
            logger.info(f"Report saved: {report_file}")

    def profile_callback(self, callback_func: Callable) -> Callable:
        """Decorator to profile Dash callbacks."""

        @wraps(callback_func)
        def wrapper(*args, **kwargs):
            callback_name = f"callback_{getattr(callback_func, '__name__', 'unknown')}"
            with self.profile_function(callback_name):
                return callback_func(*args, **kwargs)

        return wrapper

    def get_memory_usage(self) -> dict[str, float]:
        """Get current memory usage statistics."""
        if not PSUTIL_AVAILABLE:
            return {}

        process = psutil.Process()
        memory_info = process.memory_info()

        return {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
            "percent": process.memory_percent(),
            "cpu_percent": process.cpu_percent(),
        }

    def log_performance_stats(self):
        """Log current performance statistics."""
        if PSUTIL_AVAILABLE:
            stats = self.get_memory_usage()
            logger.info(
                f"Performance stats - Memory: {stats['rss_mb']:.1f}MB, CPU: {stats['cpu_percent']:.1f}%"
            )
        else:
            logger.info("Performance stats unavailable (psutil not installed)")


# Global profiler instance and registry
_profiler: Optional[DashProfiler] = None
_werkzeug_profiler_active = False


def get_profiler() -> Optional[DashProfiler]:
    """Get the global profiler instance."""
    global _profiler
    if _profiler is None and is_profiling_enabled():
        _profiler = DashProfiler()
    return _profiler


def is_profiling_enabled() -> bool:
    """Check if profiling is enabled via settings."""
    try:
        from depictio.api.v1.configs.config import settings

        return settings.profiling.enabled
    except Exception:
        # Fallback to environment variable for backwards compatibility
        return os.environ.get("DEPICTIO_PROFILING_ENABLED", "false").lower() == "true"


def setup_profiling(app):
    """Setup profiling for the Dash application."""
    if not is_profiling_enabled():
        logger.info("Profiling disabled. Set DEPICTIO_PROFILING_ENABLED=True to enable.")
        return app

    logger.info("Setting up Dash application profiling...")
    profiler = get_profiler()

    if profiler:
        app = profiler.setup_werkzeug_profiler(app)

        # Log initial performance stats
        profiler.log_performance_stats()

        logger.info("Dash profiling setup complete!")
        logger.info("Usage instructions:")
        logger.info("  1. Navigate through your Dash app to generate profile data")
        logger.info(f"  2. Profile files will be saved to: {profiler.profile_dir}")
        logger.info("  3. Use 'snakeviz <profile_file>' for interactive visualization")
        logger.info("  4. Or use 'python -m pstats <profile_file>' for command-line analysis")

    return app


def profile_function(func_name: str):
    """Decorator to profile a specific function."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            profiler = get_profiler()
            if profiler:
                with profiler.profile_function(func_name or getattr(func, "__name__", "unknown")):
                    return func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        return wrapper

    return decorator


def profile_callback(func: Callable) -> Callable:
    """Decorator to profile Dash callbacks."""
    profiler = get_profiler()
    if profiler:
        return profiler.profile_callback(func)
    return func


@contextmanager
def profile_code_block(block_name: str):
    """Context manager to profile a code block."""
    profiler = get_profiler()
    if profiler:
        with profiler.profile_function(block_name):
            yield
    else:
        yield


def log_memory_usage(label: str = ""):
    """Log current memory usage with optional label."""
    profiler = get_profiler()
    if profiler:
        stats = profiler.get_memory_usage()
        logger.info(f"Memory usage {label}: {stats.get('rss_mb', 0):.1f}MB")
