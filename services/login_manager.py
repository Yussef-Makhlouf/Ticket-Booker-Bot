"""
Secure session and login management.
Handles credential-based login, cookie persistence, and session restoration.
"""
import json
import asyncio
import logging
import time
from typing import Optional
from playwright.async_api import Page, BrowserContext
from config.settings import settings
from data.db import save_user_session, get_user_session
from services.anti_detect import human_delay

logger = logging.getLogger("automation")


class LoginManager:
    """Manages Webook login sessions."""

    def __init__(self):
        self._selector_chains = {
            "email": [
                'input[name="email"]',
                '[data-testid="auth_login_email_input"]',
                'input[type="email"]',
                '#email',
            ],
            "password": [
                'input[name="password"]',
                '[data-testid="auth_login_password_input"]',
                'input[type="password"]',
                '#password',
            ],
            "submit": [
                'button[id="email-login-button"]',
                '[data-testid="auth_login_submit_button"]',
                'button[type="submit"]',
            ],
        }

    async def check_login_status(self, page: Page) -> bool:
        """Check if user is currently logged in to Webook."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            current_url = page.url

            if "/login" in current_url or "/signup" in current_url:
                return False

            if "webook.com" in current_url:
                try:
                    login_btn = await page.query_selector(
                        '[data-testid="header_login_button"], a[href*="/login"]:visible'
                    )
                    if login_btn:
                        is_visible = await login_btn.is_visible()
                        if is_visible:
                            return False
                except Exception:
                    pass
                return True

            return False
        except Exception as e:
            logger.warning("check_login_status error: %s", e)
            return False

    async def login_with_credentials(self, page: Page, email: str, password: str) -> bool:
        """Attempt to log in with email and password."""
        try:
            logger.info("Attempting login for %s...", email[:5] + "***")

            await page.goto(
                "https://webook.com/ar/login",
                wait_until="networkidle",
                timeout=settings.PAGE_LOAD_TIMEOUT,
            )
            await asyncio.sleep(3)
            await self._dismiss_popups(page)

            # Fill email
            email_filled = False
            for selector in self._selector_chains["email"]:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000)
                    if el:
                        await el.fill(email, force=True)
                        email_filled = True
                        break
                except Exception:
                    continue

            if not email_filled:
                logger.error("Could not find email field")
                return False

            # Fill password
            password_filled = False
            for selector in self._selector_chains["password"]:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000)
                    if el:
                        await el.fill(password, force=True)
                        password_filled = True
                        break
                except Exception:
                    continue

            if not password_filled:
                logger.error("Could not find password field")
                return False

            await human_delay(500, 1000)

            # Click submit
            for selector in self._selector_chains["submit"]:
                try:
                    btn = await page.wait_for_selector(selector, timeout=5000)
                    if btn:
                        await btn.click(force=True)
                        break
                except Exception:
                    continue

            # Wait for redirect
            logger.info("Login submitted, waiting for redirect...")
            try:
                await page.wait_for_url(
                    lambda url: "/login" not in url, timeout=20000
                )
                logger.info("Login successful - redirected to: %s", page.url[:60])
                return True
            except Exception:
                if "/login" in page.url:
                    logger.error("Login failed - still on login page")
                    return False
                return True

        except Exception as e:
            logger.error("Login failed: %s", e)
            return False

    async def inject_cookies(self, context: BrowserContext, page: Page, cookie_string: str) -> bool:
        """Inject cookies from a string and verify login."""
        try:
            cookies = self._parse_cookie_string(cookie_string)
            if not cookies:
                return False

            await context.add_cookies(cookies)

            try:
                await page.goto(
                    "https://webook.com/ar/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(3)
            except Exception as e:
                logger.warning("Cookie inject navigation: %s", e)

            is_logged_in = await self.check_login_status(page)
            if is_logged_in:
                logger.info("Cookie injection successful")
            else:
                logger.warning("Cookie injection failed - not logged in")

            return is_logged_in

        except Exception as e:
            logger.error("Cookie injection error: %s", e)
            return False

    async def save_session(self, context: BrowserContext, user_id: int):
        """Save browser cookies for session persistence."""
        try:
            cookies = await context.cookies()
            cookie_json = json.dumps(cookies)
            save_user_session(user_id, cookie_json)
            logger.debug("Session saved for user %d", user_id)
        except Exception as e:
            logger.warning("Failed to save session for user %d: %s", user_id, e)

    async def restore_session(self, context: BrowserContext, user_id: int) -> bool:
        """Restore a previously saved session."""
        try:
            cookie_json = get_user_session(user_id)
            if not cookie_json:
                return False

            cookies = json.loads(cookie_json)
            await context.add_cookies(cookies)
            logger.info("Session restored for user %d", user_id)
            return True
        except Exception as e:
            logger.warning("Failed to restore session for user %d: %s", user_id, e)
            return False

    def _parse_cookie_string(self, cookie_string: str) -> list:
        """Parse a raw cookie header string into Playwright cookie format."""
        if cookie_string.lower().startswith("cookie:"):
            cookie_string = cookie_string[7:].strip()

        cookies = []
        pairs = cookie_string.replace("\n", ";").split(";")

        for pair in pairs:
            if "=" in pair:
                try:
                    name, value = pair.strip().split("=", 1)
                    cookies.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".webook.com",
                        "path": "/",
                    })
                except Exception:
                    continue

        return cookies

    async def _dismiss_popups(self, page: Page):
        """Dismiss cookie consent and overlay popups."""
        selectors = [
            'button:has-text("قبول الكل")',
            'button:has-text("Accept All")',
            'form#cookie_consent_settings button[type="button"]',
        ]
        for sel in selectors:
            try:
                await page.click(sel, timeout=2000, force=True)
                await asyncio.sleep(0.5)
                break
            except Exception:
                continue


# Global instance
login_manager = LoginManager()
