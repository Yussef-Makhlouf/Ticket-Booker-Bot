"""
Async booking task queue for concurrent request handling.
"""
import asyncio
import time
import logging
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from data.models import BookingRequest, BookingResult

logger = logging.getLogger("booking")


@dataclass
class QueuedTask:
    """A queued booking task."""
    request: BookingRequest
    callback: Optional[Callable] = None
    queued_at: float = field(default_factory=time.time)
    priority: int = 0  # Higher = more priority


class BookingQueue:
    """
    Async task queue for booking requests.
    Limits concurrent bookings to prevent resource exhaustion.
    """

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._active: Dict[int, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._results: Dict[int, BookingResult] = {}
        self._running = False
        self._total_processed = 0
        self._total_queued = 0

    async def enqueue(self, request: BookingRequest, callback: Optional[Callable] = None):
        """Add a booking request to the queue."""
        task = QueuedTask(request=request, callback=callback)
        await self._queue.put(task)
        self._total_queued += 1
        logger.info(
            "Booking queued for user %d (queue size: %d)",
            request.user_id, self._queue.qsize(),
        )

    async def start_processing(self, executor: Callable):
        """Start the queue processing loop."""
        self._running = True
        logger.info("Booking queue started (max concurrent: %d)", self.max_concurrent)

        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                asyncio.create_task(
                    self._process_task(task, executor)
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Queue processing error: %s", e)

    async def _process_task(self, task: QueuedTask, executor: Callable):
        """Process a single booking task with concurrency control."""
        user_id = task.request.user_id

        async with self._semaphore:
            try:
                logger.info("Processing booking for user %d", user_id)
                result = await executor(task.request)
                self._results[user_id] = result
                self._total_processed += 1

                if task.callback:
                    try:
                        await task.callback(result)
                    except Exception as e:
                        logger.error("Callback error for user %d: %s", user_id, e)

            except Exception as e:
                logger.error("Task execution error for user %d: %s", user_id, e)
                self._results[user_id] = BookingResult(
                    success=False,
                    error_code="QUEUE_ERROR",
                    message=str(e),
                )

    def get_result(self, user_id: int) -> Optional[BookingResult]:
        """Get the result for a user's booking."""
        return self._results.pop(user_id, None)

    def stop(self):
        """Stop the queue processing."""
        self._running = False

    @property
    def stats(self) -> dict:
        return {
            "queue_size": self._queue.qsize(),
            "active_tasks": self.max_concurrent - self._semaphore._value,
            "max_concurrent": self.max_concurrent,
            "total_queued": self._total_queued,
            "total_processed": self._total_processed,
        }


# Global instance
booking_queue = BookingQueue()
