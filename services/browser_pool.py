"""
Managed browser instance pool with pre-warming, rotation, and health checks.
Replaces the old singleton BrowserManager.
"""
import asyncio
import random
import logging
import time
from typing import Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from config.settings import settings

logger = logging.getLogger("browser")

# Rotating user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

BrowserSession = Tuple[BrowserContext, Page]


class BrowserPool:
    """
    Pre-warmed browser pool for instant booking sessions.

    Usage:
        pool = BrowserPool()
        await pool.initialize()
        ctx, page = await pool.acquire(user_id=123)
        # ... use page ...
        await pool.release(user_id=123)
    """

    def __init__(self, max_instances: int = None):
        self.max_instances = max_instances or settings.MAX_BROWSER_INSTANCES
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._pool: asyncio.Queue[BrowserSession] = asyncio.Queue(maxsize=self.max_instances)
        self._active_sessions: dict[int, BrowserSession] = {}  # user_id -> session
        self._lock = asyncio.Lock()
        self._initialized = False
        self._total_created = 0
        self._total_acquired = 0
        self._total_released = 0

    async def initialize(self):
        """Start Playwright and create the browser instance."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info("Initializing browser pool (max=%d)...", self.max_instances)
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.BROWSER_HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                ]
            )

            # Pre-warm instances
            warmup_count = min(settings.BROWSER_WARMUP_COUNT, self.max_instances)
            for i in range(warmup_count):
                try:
                    session = await self._create_session()
                    await self._pool.put(session)
                    logger.debug("Pre-warmed browser instance %d/%d", i + 1, warmup_count)
                except Exception as e:
                    logger.warning("Failed to pre-warm instance %d: %s", i + 1, e)

            self._initialized = True
            logger.info(
                "Browser pool ready: %d pre-warmed, %d max",
                self._pool.qsize(), self.max_instances
            )

    async def _create_session(self) -> BrowserSession:
        """Create a new browser context and page."""
        ua = random.choice(USER_AGENTS)
        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=ua,
            locale="ar-SA",
            timezone_id="Asia/Riyadh",
            bypass_csp=True,
            java_script_enabled=True,
        )

        # Apply stealth patches
        await self._apply_stealth(context)

        page = await context.new_page()
        self._total_created += 1
        return context, page

    async def _apply_stealth(self, context: BrowserContext):
        """Apply anti-detection JavaScript patches."""
        stealth_js = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['ar-SA', 'ar', 'en-US', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        window.chrome = {runtime: {}};
        Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
        """
        await context.add_init_script(stealth_js)

    async def acquire(self, user_id: int) -> BrowserSession:
        """
        Get a browser session for a user.
        Returns existing session if one exists, otherwise creates/recycles one.
        """
        await self.initialize()

        # Check for existing session
        if user_id in self._active_sessions:
            ctx, page = self._active_sessions[user_id]
            if not page.is_closed():
                return ctx, page
            else:
                # Session died, clean up
                del self._active_sessions[user_id]

        # Try to get from pool
        try:
            ctx, page = await asyncio.wait_for(
                self._pool.get(),
                timeout=settings.BROWSER_ACQUIRE_TIMEOUT
            )
            # Verify the page is still alive
            if page.is_closed():
                ctx, page = await self._create_session()
        except asyncio.TimeoutError:
            # Pool empty — create new if under limit
            if len(self._active_sessions) < self.max_instances:
                ctx, page = await self._create_session()
                logger.info("Pool empty, created new instance (active=%d)", len(self._active_sessions) + 1)
            else:
                raise RuntimeError("Browser pool exhausted. Try again later.")

        self._active_sessions[user_id] = (ctx, page)
        self._total_acquired += 1
        logger.debug("Acquired session for user %d (active=%d)", user_id, len(self._active_sessions))
        return ctx, page

    async def release(self, user_id: int, keep_warm: bool = True):
        """Release a browser session back to the pool or close it."""
        session = self._active_sessions.pop(user_id, None)
        if not session:
            return

        ctx, page = session
        self._total_released += 1

        try:
            if keep_warm and not page.is_closed() and self._pool.qsize() < self.max_instances:
                # Reset page and return to pool
                try:
                    await page.goto("about:blank", timeout=5000)
                except Exception:
                    pass
                await self._pool.put((ctx, page))
                logger.debug("Released session for user %d back to pool", user_id)
            else:
                await self._cleanup_session(ctx, page)
                logger.debug("Closed session for user %d", user_id)
        except Exception as e:
            logger.warning("Error releasing session for user %d: %s", user_id, e)

    async def _cleanup_session(self, ctx: BrowserContext, page: Page):
        """Safely close a browser context and page."""
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass
        try:
            await ctx.close()
        except Exception:
            pass

    async def close_all(self):
        """Shutdown the entire pool and browser."""
        logger.info("Shutting down browser pool...")

        # Close active sessions
        for user_id in list(self._active_sessions.keys()):
            await self.release(user_id, keep_warm=False)

        # Drain the pool
        while not self._pool.empty():
            try:
                ctx, page = self._pool.get_nowait()
                await self._cleanup_session(ctx, page)
            except asyncio.QueueEmpty:
                break

        # Close browser
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

        self._initialized = False
        logger.info(
            "Browser pool shutdown. Stats: created=%d, acquired=%d, released=%d",
            self._total_created, self._total_acquired, self._total_released
        )

    @property
    def stats(self) -> dict:
        """Get pool statistics."""
        return {
            "active_sessions": len(self._active_sessions),
            "pool_available": self._pool.qsize(),
            "max_instances": self.max_instances,
            "total_created": self._total_created,
            "total_acquired": self._total_acquired,
            "total_released": self._total_released,
            "initialized": self._initialized,
        }


# Global singleton
browser_pool = BrowserPool()
