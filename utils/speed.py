"""
Performance optimization helpers: timers, parallel execution, throttling.
"""
import asyncio
import time
import logging
from typing import Any, Callable, Coroutine, List
from contextlib import asynccontextmanager

logger = logging.getLogger("booking")


class Timer:
    """Precision timer for performance tracking."""

    def __init__(self, label: str = ""):
        self.label = label
        self.start_time: float = 0
        self.end_time: float = 0
        self.elapsed: float = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end_time = time.perf_counter()
        self.elapsed = self.end_time - self.start_time
        if self.label:
            logger.debug("%s: %.3fs", self.label, self.elapsed)

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed * 1000


@asynccontextmanager
async def async_timer(label: str = ""):
    """Async context manager for timing operations."""
    start = time.perf_counter()
    result = {"elapsed": 0.0}
    try:
        yield result
    finally:
        result["elapsed"] = time.perf_counter() - start
        if label:
            logger.debug("%s: %.3fs", label, result["elapsed"])


async def parallel_execute(*tasks: Coroutine) -> List[Any]:
    """
    Execute multiple coroutines in parallel and return results.
    Uses TaskGroup for structured concurrency.
    """
    results = [None] * len(tasks)

    async def _run(index: int, coro: Coroutine):
        results[index] = await coro

    try:
        async with asyncio.TaskGroup() as tg:
            for i, task in enumerate(tasks):
                tg.create_task(_run(i, task))
    except* Exception as eg:
        # Log individual exceptions but don't lose results
        for exc in eg.exceptions:
            logger.error("Parallel task failed: %s", exc)

    return results


class Throttle:
    """Rate limiter to prevent overwhelming the target server."""

    def __init__(self, min_interval: float = 0.5):
        self.min_interval = min_interval
        self._last_call: float = 0
        self._lock = asyncio.Lock()

    async def wait(self):
        """Wait until enough time has passed since last call."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_call = time.time()


class ProgressTracker:
    """Track and format progress for user-facing messages."""

    def __init__(self):
        self.steps: List[dict] = []
        self.start_time = time.perf_counter()

    def add_step(self, name: str, duration: float, success: bool = True):
        self.steps.append({
            "name": name,
            "duration": duration,
            "success": success
        })

    @property
    def total_time(self) -> float:
        return time.perf_counter() - self.start_time

    def format_progress(self) -> str:
        """Format progress as Arabic status message."""
        lines = []
        for step in self.steps:
            icon = "✅" if step["success"] else "❌"
            lines.append(f"  {icon} {step['name']}: {step['duration']:.1f}s")
        lines.append(f"\n⏱️ <b>الوقت الإجمالي: {self.total_time:.1f}s</b>")
        return "\n".join(lines)
