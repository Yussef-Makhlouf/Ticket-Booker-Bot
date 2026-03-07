"""
Intelligent retry decorator with exponential backoff.
"""
import asyncio
import functools
import logging
from typing import Tuple, Type, Optional, Callable

logger = logging.getLogger("booking")


def retry_async(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Async retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback(attempt, exception) called before each retry
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            "Retry %d/%d for %s: %s (waiting %.1fs)",
                            attempt + 1, max_retries, func.__name__, str(e), delay
                        )
                        if on_retry:
                            try:
                                on_retry(attempt + 1, e)
                            except Exception:
                                pass
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "All %d retries exhausted for %s: %s",
                            max_retries, func.__name__, str(e)
                        )
            raise last_exception
        return wrapper
    return decorator


class RetryContext:
    """Context manager for retry logic in imperative code."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.attempt = 0
        self.last_error: Optional[Exception] = None

    @property
    def should_retry(self) -> bool:
        return self.attempt < self.max_retries

    @property
    def delay(self) -> float:
        return min(self.base_delay * (2 ** self.attempt), self.max_delay)

    async def wait(self):
        """Wait for the backoff delay before next retry."""
        d = self.delay
        logger.info("Retry %d/%d - waiting %.1fs...", self.attempt + 1, self.max_retries, d)
        await asyncio.sleep(d)
        self.attempt += 1

    def record_error(self, error: Exception):
        self.last_error = error
