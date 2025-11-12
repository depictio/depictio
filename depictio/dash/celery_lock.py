"""
Redis-based distributed locking for Celery background callbacks.
Prevents duplicate execution when multiple Inputs trigger the same callback.
"""

import hashlib
import time
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

import redis
from dash import no_update

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

if TYPE_CHECKING:
    from typing import Protocol

    class CallbackFunc(Protocol):
        __name__: str

        def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class CeleryCallbackLock:
    """
    Distributed lock for Celery background callbacks using Redis.

    Features:
    - Atomic lock acquisition with SET NX (set if not exists)
    - Auto-expiry with TTL to prevent deadlocks
    - Lock key based on callback function + component index
    - Graceful fallback if Redis unavailable

    Usage:
        @app.callback(...)
        @callback_lock(ttl_seconds=30)
        def my_callback(...):
            # Only one execution per component at a time
            pass
    """

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 30):
        """
        Initialize Redis lock manager.

        Args:
            redis_url: Redis connection URL (defaults to Celery broker)
            ttl_seconds: Lock expiry time in seconds (prevents deadlocks)
        """
        self.redis_url = redis_url or settings.celery.broker_url
        self.ttl_seconds = ttl_seconds
        self._redis_client = None

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy Redis client initialization."""
        if self._redis_client is None:
            self._redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis_client

    def generate_lock_key(self, callback_name: str, component_index: str) -> str:
        """
        Generate unique lock key for callback + component.

        Args:
            callback_name: Callback function name
            component_index: Component index from pattern-matching ID

        Returns:
            Redis key for lock (e.g., "depictio:callback_lock:render_card:abc123")
        """
        # Use hash for shorter keys
        key_parts = f"{callback_name}:{component_index}"
        key_hash = hashlib.md5(key_parts.encode()).hexdigest()[:12]
        return f"depictio:callback_lock:{callback_name}:{key_hash}"

    def acquire(self, lock_key: str, worker_id: str) -> bool:
        """
        Attempt to acquire lock atomically.

        Args:
            lock_key: Redis key for lock
            worker_id: Unique identifier for this worker/task

        Returns:
            True if lock acquired, False if already locked
        """
        try:
            # SET NX EX: Set if Not eXists with EXpiry
            # Returns True only if key didn't exist (lock acquired)
            acquired = self.redis_client.set(
                lock_key,
                worker_id,
                nx=True,  # Only set if key doesn't exist
                ex=self.ttl_seconds,  # Auto-expire after TTL
            )

            if acquired:
                logger.debug(f"🔒 Lock acquired: {lock_key} by {worker_id}")
            else:
                existing_owner = self.redis_client.get(lock_key)
                logger.info(
                    f"⏭️  Lock already held: {lock_key} by {existing_owner} "
                    f"(skipping duplicate execution)"
                )

            return bool(acquired)

        except redis.RedisError as e:
            # Graceful fallback: allow execution if Redis unavailable
            logger.warning(f"⚠️  Redis unavailable for lock {lock_key}: {e} (allowing execution)")
            return True

    def release(self, lock_key: str, worker_id: str) -> bool:
        """
        Release lock if still owned by this worker.

        Args:
            lock_key: Redis key for lock
            worker_id: Unique identifier for this worker/task

        Returns:
            True if lock released, False if not owned or already expired
        """
        try:
            # Only delete if we still own the lock (prevents race condition)
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """

            released = self.redis_client.eval(lua_script, 1, lock_key, worker_id)

            if released:
                logger.debug(f"🔓 Lock released: {lock_key} by {worker_id}")
            else:
                logger.debug(f"⏭️  Lock expired or not owned: {lock_key}")

            return bool(released)

        except redis.RedisError as e:
            logger.warning(f"⚠️  Redis error releasing lock {lock_key}: {e}")
            return False


def callback_lock(
    ttl_seconds: int = 30,
    return_on_locked: Any = no_update,
    extract_index: Optional[Callable[[dict], str]] = None,
):
    """
    Decorator for Celery background callbacks to prevent duplicate execution.

    Usage:
        @app.callback(
            Output(...),
            Input(...),
            background=True,
        )
        @callback_lock(ttl_seconds=30)
        def my_callback(...):
            # Only one execution per component at a time
            pass

    Args:
        ttl_seconds: Lock expiry time (prevents deadlocks if worker crashes)
        return_on_locked: Value to return if lock already held (default: no_update)
        extract_index: Function to extract component index from callback_context

    Returns:
        Decorated callback function with distributed locking
    """

    def decorator(func: "CallbackFunc") -> "CallbackFunc":
        lock_manager = CeleryCallbackLock(ttl_seconds=ttl_seconds)
        func_cast = cast(Any, func)  # Cast for type checker

        @wraps(func_cast)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from dash import callback_context as ctx

            # Extract component index from callback context
            component_index: str
            try:
                # Check if callback_context is available
                ctx_dict = getattr(ctx, "to_dict", None)
                if ctx_dict is None or not callable(ctx_dict):
                    component_index = "global"
                elif extract_index:
                    component_index = extract_index(ctx_dict())
                else:
                    # Default: extract from triggered_id
                    triggered = ctx_dict().get("triggered", [])
                    if triggered and len(triggered) > 0:
                        triggered_id = triggered[0].get("prop_id", "").split(".")[0]
                        # Try to parse as JSON (pattern-matching ID)
                        import json

                        try:
                            id_dict = json.loads(triggered_id)
                            component_index = str(id_dict.get("index", "unknown"))
                        except (json.JSONDecodeError, AttributeError):
                            # Simple string ID
                            component_index = triggered_id or "unknown"
                    else:
                        component_index = "unknown"
            except Exception as e:
                logger.warning(f"Failed to extract component index: {e}, using 'global'")
                component_index = "global"

            # Generate lock key and worker ID
            func_name = func_cast.__name__
            lock_key = lock_manager.generate_lock_key(func_name, component_index)
            worker_id = f"{func_name}:{time.time()}"

            # Try to acquire lock
            if not lock_manager.acquire(lock_key, worker_id):
                logger.info(
                    f"⏭️  {func_name}[{component_index}]: "
                    f"Skipping duplicate execution (another task already running)"
                )
                return return_on_locked

            try:
                # Execute callback with lock held
                logger.info(f"✅ {func_name}[{component_index}]: Executing (lock acquired)")
                result = func_cast(*args, **kwargs)
                return result

            finally:
                # Always release lock
                lock_manager.release(lock_key, worker_id)

        return cast("CallbackFunc", wrapper)

    return decorator
