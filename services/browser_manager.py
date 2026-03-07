from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from typing import Dict, Optional
import asyncio

class BrowserManager:
    _instance = None
    _browser: Optional[Browser] = None
    _contexts: Dict[int, BrowserContext] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        if self._browser is None:
            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )

    async def create_session(self, user_id: int) -> tuple[BrowserContext, Page]:
        context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ar-SA',
            timezone_id='Asia/Riyadh'
        )

        page = await context.new_page()
        self._contexts[user_id] = context

        return context, page

    async def get_session(self, user_id: int) -> Optional[tuple[BrowserContext, Page]]:
        if user_id in self._contexts:
            context = self._contexts[user_id]
            page = context.pages[0] if context.pages else None
            return context, page
        return None

    async def close_session(self, user_id: int):
        if user_id in self._contexts:
            await self._contexts[user_id].close()
            del self._contexts[user_id]

    async def close_all(self):
        if self._browser:
            await self._browser.close()
