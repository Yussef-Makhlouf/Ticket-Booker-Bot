"""
Booking orchestration engine with retry logic and parallel preparation.
Central coordinator for the entire booking flow.
"""
import asyncio
import time
import logging
from typing import Optional
from data.models import (
    BookingRequest, BookingResult, BookingPrep, EventData, BookingStatus,
)
from services.browser_pool import browser_pool
from services.webook_automation import WebookAutomation
from services.login_manager import login_manager
from services.smart_cache import smart_cache
from analyzers.page_analyzer import PageAnalyzer
from utils.speed import Timer, ProgressTracker
from utils.retry import RetryContext
from utils.link_parser import extract_event_id
from config.settings import settings

logger = logging.getLogger("booking")


class BookingEngine:
    """Main booking orchestrator with retry logic and parallel prep."""

    def __init__(self):
        self._active_bookings: dict[int, bool] = {}

    async def prepare_booking(self, event_url: str, user_id: int) -> BookingPrep:
        """
        Extract event data and check login status.
        Uses parallel execution where possible.
        """
        prep = BookingPrep()
        start = time.perf_counter()
        event_id = extract_event_id(event_url) or ""

        # Ensure the URL points to the event page (not /book)
        base_url = event_url.split("?")[0]
        if base_url.endswith("/book"):
            base_url = base_url[:-5]

        # Acquire browser
        ctx, page = await browser_pool.acquire(user_id)
        automation = WebookAutomation(page)

        # Navigate to event page
        await automation.navigate_to_event(base_url)

        # Parallel: extract event data + check login
        analyzer = PageAnalyzer(page)

        event_task = asyncio.create_task(analyzer.extract_event_data(event_id))
        login_task = asyncio.create_task(automation.check_login_status())

        event_data, is_logged_in = await asyncio.gather(event_task, login_task)

        prep.event_data = event_data
        prep.event_data.url = event_url
        prep.is_logged_in = is_logged_in
        prep.prep_time = time.perf_counter() - start

        logger.info(
            "Booking prep done in %.2fs: event='%s', logged_in=%s",
            prep.prep_time, event_data.name[:40] if event_data.name else "?", is_logged_in,
        )
        return prep

    async def execute_booking(self, request: BookingRequest) -> BookingResult:
        """
        Execute the full booking flow with retry logic.

        Steps:
        1. Navigate to booking page (/book)
        2. Handle team selection (if match)
        3. Wait for seat map
        4. Click section
        5. Set ticket count + add to cart
        6. Proceed to checkout
        """
        start = time.perf_counter()
        retry = RetryContext(
            max_retries=settings.MAX_RETRIES,
            base_delay=settings.RETRY_BASE_DELAY,
        )
        tracker = ProgressTracker()
        last_error = ""

        while True:
            try:
                # Get browser session
                ctx, page = await browser_pool.acquire(request.user_id)
                automation = WebookAutomation(page)

                try:
                    return await self._execute_single_attempt(
                        request, automation, tracker, start
                    )
                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        "Booking attempt %d failed: %s",
                        retry.attempt + 1, last_error,
                    )

                    if retry.should_retry:
                        retry.record_error(e)
                        await retry.wait()
                    else:
                        break

            except RuntimeError as e:
                # Browser pool exhausted
                if retry.should_retry:
                    retry.record_error(e)
                    await retry.wait()
                else:
                    return BookingResult(
                        success=False,
                        error_code="POOL_EXHAUSTED",
                        message="خوادم الحجز مشغولة. حاول مرة أخرى.",
                        duration=time.perf_counter() - start,
                        attempts=retry.attempt + 1,
                    )

        # All retries exhausted
        return BookingResult(
            success=False,
            error_code="MAX_RETRIES",
            message=f"فشل الحجز بعد {settings.MAX_RETRIES} محاولات.\nآخر خطأ: {last_error}",
            duration=time.perf_counter() - start,
            attempts=retry.attempt + 1,
        )

    async def _execute_single_attempt(
        self,
        request: BookingRequest,
        automation: WebookAutomation,
        tracker: ProgressTracker,
        start: float,
    ) -> BookingResult:
        """Execute a single booking attempt."""
        event_id = extract_event_id(request.event_url) or ""

        # Step 1: Navigate to booking page
        with Timer("navigate") as t:
            await automation.navigate_to_event(request.booking_url)
        tracker.add_step("فتح صفحة الحجز", t.elapsed)

        # Step 2: Team selection (if applicable)
        if request.team:
            with Timer("team_select") as t:
                await automation.select_team(request.team)
            tracker.add_step("اختيار الفريق", t.elapsed)

        # Step 3: Wait for seat map
        with Timer("seat_map") as t:
            map_loaded = await automation.wait_for_seat_map()
        tracker.add_step("تحميل خريطة المقاعد", t.elapsed, success=map_loaded)

        if not map_loaded:
            raise Exception("لم تظهر خريطة المقاعد")

        # Step 4: Click section
        with Timer("click_section") as t:
            section_status = await automation.click_section(request.section, event_id)
        tracker.add_step("اختيار القسم", t.elapsed, success=(section_status != 'FAILED'))

        if section_status == 'FAILED':
            raise Exception(f"لم أتمكن من النقر على القسم {request.section}")

        # Step 5: Set ticket count + add to cart
        with Timer("tickets") as t:
            added = await automation.set_ticket_count(request.section, request.tickets, section_status)
        tracker.add_step("إضافة التذاكر", t.elapsed, success=added)

        # Step 6: Take screenshot
        screenshot = await automation.take_seat_map_screenshot(request.user_id)

        # Step 7: Checkout
        checkout_url = ""
        if added:
            with Timer("checkout") as t:
                checkout_url = await automation.proceed_to_checkout()
            tracker.add_step("الانتقال للدفع", t.elapsed)

        duration = time.perf_counter() - start
        return BookingResult(
            success=added,
            checkout_url=checkout_url,
            event_name=request.event_url,
            tickets=request.tickets,
            section=request.section,
            duration=duration,
            attempts=1,
            screenshot_path=screenshot,
            message=tracker.format_progress(),
            error_code="" if added else "ADD_TO_CART_FAILED",
        )

    async def cleanup_user(self, user_id: int):
        """Release resources for a user."""
        self._active_bookings.pop(user_id, None)
        await browser_pool.release(user_id)


# Global instance
booking_engine = BookingEngine()
