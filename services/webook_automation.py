"""
Webook-specific automation: navigation, team selection, ticket count,
cart management, checkout. Uses SeatMapper with GA popup handling.

SeatCloud flow:
1. Navigate to /book
2. (Optional) Select team → accept terms → click Next
3. Wait for SeatCloud iframe + canvas
4. Click section on canvas
5. GA popup appears inside iframe with quantity controls
6. Set quantity in GA popup → click Confirm
7. After confirm, tickets are added → proceed to checkout on main page
"""
import asyncio
import os
import time
import re
import logging
from typing import Optional, List
from playwright.async_api import Page, Frame
from services.anti_detect import human_delay
from services.seat_mapper import SeatMapper

logger = logging.getLogger("automation")


class WebookAutomation:
    """High-level Webook page automation."""

    def __init__(self, page: Page):
        self.page = page
        self.seat_mapper = SeatMapper(page)

    # ── Navigation ──

    async def dismiss_popups(self):
        """Dismiss cookie consent and overlay popups."""
        selectors = [
            'button:has-text("قبول الكل")',
            'button:has-text("Accept All")',
            'form#cookie_consent_settings button[type="button"]',
            'button:has-text("Accept")',
        ]
        for sel in selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info("Dismissed popup: %s", sel)
                    break
            except Exception:
                continue

    async def navigate_to_event(self, event_url: str):
        """Navigate to an event page."""
        logger.info("Navigating to: %s", event_url[:80])
        try:
            await self.page.goto(
                event_url, wait_until="domcontentloaded", timeout=60000
            )
        except Exception as e:
            logger.warning("Navigation warning: %s", e)

        await asyncio.sleep(3)
        await self.dismiss_popups()
        await asyncio.sleep(1)

    # ── Login Check ──

    async def check_login_status(self) -> bool:
        """Check if user is logged in on the current page."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            current_url = self.page.url

            if "/login" in current_url or "/signup" in current_url:
                return False

            if "webook.com" in current_url:
                # Check for login button visibility
                result = await self.page.evaluate("""() => {
                    // If we see the login form, we're not logged in
                    const loginForm = document.getElementById('email-login');
                    if (loginForm) {
                        const formStyle = window.getComputedStyle(loginForm);
                        if (formStyle.display !== 'none') return false;
                    }
                    
                    // Check for header login button
                    const loginBtns = document.querySelectorAll(
                        '[data-testid="header_login_button"], a[href*="/login"]'
                    );
                    for (const btn of loginBtns) {
                        if (btn.offsetWidth > 0 && btn.offsetHeight > 0) return false;
                    }
                    
                    // If the booking page has a SeatCloud iframe, user is logged in
                    const frames = document.querySelectorAll('iframe');
                    for (const f of frames) {
                        if (f.src && (f.src.includes('seatcloud') || f.src.includes('chart'))) {
                            return true;
                        }
                    }
                    
                    return true;  // Default: assume logged in if no login indicators
                }""")
                return result

            return False
        except Exception as e:
            logger.warning("Login check error: %s", e)
            return False

    # ── Team Selection ──

    async def select_team(self, team: str):
        """Select fan side/team on the booking page."""
        logger.info("Selecting team: %s", team)
        team_keywords = [team]
        # Generate variations
        if team.startswith("ال"):
            team_keywords.append(team[2:])  # Without "ال"
        if "نادي " in team:
            team_keywords.append(team.replace("نادي ", ""))

        for kw in team_keywords:
            try:
                btn = await self.page.query_selector(
                    f'button:has-text("{kw}"), [data-team*="{kw}"], '
                    f'div:has-text("{kw}"):not(nav):not(header)'
                )
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(2)
                    logger.info("Selected team: %s", kw)
                    break
            except Exception:
                continue

        # Accept terms checkbox
        try:
            checkbox = await self.page.query_selector(
                'input[type="checkbox"]:not(:checked)'
            )
            if checkbox and await checkbox.is_visible():
                await checkbox.click(force=True)
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Click Next
        next_selectors = [
            'button:has-text("التالي")',
            'button:has-text("Next")',
            'button:has-text("استمر")',
            'button:has-text("Continue")',
        ]
        for sel in next_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(3)
                    break
            except Exception:
                continue

    # ── Seat Map ──

    async def wait_for_seat_map(self, timeout: int = None) -> bool:
        """Wait for seat map to load (delegates to SeatMapper)."""
        return await self.seat_mapper.wait_for_seat_map(timeout)

    async def get_available_sections(self) -> List[str]:
        """Get available sections from the seat map."""
        seat_map = await self.seat_mapper.analyze_seat_structure()
        return seat_map.sections

    async def click_section(self, section_name: str, event_id: str = "") -> bool:
        """Click a section on the seat map."""
        return await self.seat_mapper.click_section(section_name, event_id)

    async def take_seat_map_screenshot(self, user_id: int) -> str:
        """Take screenshot of seat map."""
        return await self.seat_mapper.take_screenshot(user_id)

    # ── Ticket Quantity (via GA Popup in SeatCloud) ──

    async def set_ticket_count(self, section_name: str, count: int) -> bool:
        """Set ticket quantity using the SeatCloud GA popup.
        
        After clicking a section, the GA popup appears inside the iframe with:
        - #ga-increase-seats / #ga-decrease-seats buttons
        - #ga-seat-count input
        - #ga-confirm-seats button
        """
        frame = self.seat_mapper._get_seatcloud_frame()
        if not frame:
            logger.warning("No SeatCloud frame found for ticket count")
            return await self._set_ticket_count_fallback(count)

        # Check if GA popup is visible
        ga_visible = await self.seat_mapper._is_ga_popup_visible(frame)
        if ga_visible:
            logger.info("Setting quantity to %d in GA popup", count)
            return await self.seat_mapper.set_quantity_in_ga_popup(frame, count)
        else:
            logger.warning("GA popup not visible, trying fallback")
            return await self._set_ticket_count_fallback(count)

    async def _set_ticket_count_fallback(self, count: int) -> bool:
        """Fallback: try to set ticket count using main page controls."""
        await asyncio.sleep(2)

        # Try increment buttons on the main page
        for i in range(count - 1):
            increment_selectors = [
                'button:has-text("+")',
                '[aria-label*="add"]',
                '[aria-label*="زيادة"]',
                '[data-testid*="increment"]',
                '[class*="increment"]',
                '[class*="plus"]',
            ]
            for sel in increment_selectors:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click(force=True)
                        await asyncio.sleep(0.4)
                        break
                except Exception:
                    continue

        # Try to add to cart
        add_selectors = [
            'button:has-text("أضف للسلة")',
            'button:has-text("إضافة")',
            'button:has-text("Add to Cart")',
            'button:has-text("أضف")',
            'button:has-text("Checkout")',
            'button:has-text("التالي")',
        ]
        for sel in add_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(2)
                    logger.info("Fallback add-to-cart: %s", sel)
                    return True
            except Exception:
                continue

        return False

    # ── Checkout ──

    async def proceed_to_checkout(self) -> str:
        """Click checkout button and return the payment URL.
        After GA popup confirm, we wait for the main page to update."""
        await asyncio.sleep(3)

        # Try clicking checkout/payment/next buttons
        checkout_selectors = [
            'button:has-text("الدفع")',
            'button:has-text("إتمام الشراء")',
            'button:has-text("Checkout")',
            'button:has-text("التالي: الدفع")',
            'button:has-text("متابعة")',
            'button:has-text("التالي")',
            'button:has-text("Next")',
            'button:has-text("Proceed")',
            '[data-testid*="checkout"]',
            ".checkout-btn",
        ]

        for sel in checkout_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(4)
                    logger.info("Clicked checkout: %s", sel)
                    break
            except Exception:
                continue

        checkout_url = self.page.url
        logger.info("Checkout URL: %s", checkout_url[:80])
        return checkout_url

    async def close(self):
        """Close the page."""
        try:
            if not self.page.is_closed():
                await self.page.close()
        except Exception:
            pass
