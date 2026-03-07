"""
Dynamic seat detection and mapping engine.
Multi-strategy: DOM → Canvas → API intercept.

SeatCloud iframe structure (from debug):
- Canvas: #canvas (rendered seat map)
- Section tooltip: #sectionTooltip (appears on hover over sections)
- Seat tooltip: #seatTooltip (appears on hover over individual seats)
- GA Popup: #ga-popup (appears after clicking a section)
  - #ga-title: section name
  - #ga-category: pricing category
  - #ga-increase-seats / #ga-decrease-seats: quantity controls
  - #ga-seat-count: quantity input
  - #ga-confirm-seats: confirm button
  - #ga-cancel-popup: cancel button
"""
import asyncio
import re
import time
import logging
from typing import List, Optional, Dict, Tuple
from playwright.async_api import Page, Frame
from data.models import Seat, SeatMap, SeatSource
from config.settings import settings
from services.smart_cache import smart_cache

logger = logging.getLogger("automation")


class SeatMapper:
    """
    Intelligent seat detection that adapts to any Webook event page.
    Uses SeatCloud iframe with canvas-based seat maps.
    """

    def __init__(self, page: Page):
        self.page = page
        self._frame: Optional[Frame] = None
        self._canvas_size: Optional[dict] = None

    def _get_seatcloud_frame(self) -> Optional[Frame]:
        """Find the SeatCloud iframe."""
        for frame in self.page.frames:
            if "seatcloud.com" in frame.url or "chart" in frame.url:
                return frame
        return None

    async def wait_for_seat_map(self, timeout_ms: int = None) -> bool:
        """Wait for the SeatCloud canvas to fully load."""
        timeout_ms = timeout_ms or settings.SEAT_MAP_WAIT_TIMEOUT
        logger.info("Waiting for seat map to load...")

        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await asyncio.sleep(5)

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            self._frame = self._get_seatcloud_frame()
            if self._frame:
                logger.info("Found SeatCloud frame: %s", self._frame.url[:60])
                try:
                    canvas = await self._frame.wait_for_selector("#canvas", timeout=15000)
                    if canvas:
                        await asyncio.sleep(5)  # Let canvas finish rendering
                        self._canvas_size = await self._get_canvas_size()
                        logger.info(
                            "Canvas ready: %dx%d",
                            self._canvas_size.get("cssW", 0),
                            self._canvas_size.get("cssH", 0),
                        )
                        return True
                except Exception:
                    pass

            await asyncio.sleep(2)

        # Fallback
        if "/book" in self.page.url:
            await asyncio.sleep(5)
            self._frame = self._get_seatcloud_frame()
            return self._frame is not None

        return False

    async def _get_canvas_size(self) -> dict:
        """Get the canvas CSS rendered dimensions."""
        if not self._frame:
            return {}
        try:
            return await self._frame.evaluate("""() => {
                const c = document.getElementById('canvas');
                if (!c) return {};
                const rect = c.getBoundingClientRect();
                return {
                    attrW: c.width, attrH: c.height,
                    cssW: rect.width, cssH: rect.height
                };
            }""")
        except Exception:
            return {}

    async def analyze_seat_structure(self, event_id: str = "") -> SeatMap:
        """
        Auto-detect seats/sections using multiple strategies.
        Returns a SeatMap with discovered sections and their coordinates.
        """
        start = time.perf_counter()

        # Check cache first
        if event_id:
            cached_coords = await smart_cache.get_section_coordinates(event_id)
            if cached_coords:
                logger.info("Using cached section coordinates for event %s", event_id)
                return SeatMap(
                    source=SeatSource.CANVAS,
                    sections=list(cached_coords.keys()),
                    section_coordinates=cached_coords,
                    scan_time=0.0,
                )

        # Strategy 1: Canvas grid scanning (primary for SeatCloud)
        seat_map = await self._scan_canvas_sections()

        # Strategy 2: DOM-based detection
        if not seat_map.sections:
            dom_sections = await self._parse_dom_sections()
            if dom_sections:
                seat_map.sections = dom_sections
                seat_map.source = SeatSource.DOM

        seat_map.scan_time = time.perf_counter() - start
        logger.info(
            "Seat analysis: %d sections found via %s in %.2fs",
            len(seat_map.sections), seat_map.source.value, seat_map.scan_time,
        )

        # Cache coordinates
        if event_id and seat_map.section_coordinates:
            await smart_cache.set_section_coordinates(event_id, seat_map.section_coordinates)

        return seat_map

    async def _scan_canvas_sections(self) -> SeatMap:
        """Scan the SeatCloud canvas by hovering grid points.
        Uses BOTH #sectionTooltip and #seatTooltip for detection."""
        sections: List[str] = []
        section_coords: Dict[str, Tuple[float, float]] = {}

        frame = self._frame or self._get_seatcloud_frame()
        if not frame:
            return SeatMap()

        size = self._canvas_size or await self._get_canvas_size()
        if not size:
            return SeatMap()

        cw = size.get("cssW", 0)
        ch = size.get("cssH", 0)
        if cw == 0 or ch == 0:
            return SeatMap()

        steps_x = settings.SEAT_SCAN_GRID_X
        steps_y = settings.SEAT_SCAN_GRID_Y
        found: set = set()

        logger.debug("Scanning canvas %dx%d with grid %dx%d...", cw, ch, steps_x, steps_y)

        for row in range(steps_y):
            for col in range(steps_x):
                lx = cw * (col + 0.5) / steps_x
                ly = ch * (row + 0.5) / steps_y

                tooltip = await self._hover_canvas(frame, lx, ly)
                if tooltip and 0 < len(tooltip) <= 40:
                    # Parse section name from tooltip
                    section = self._parse_section_from_tooltip(tooltip)
                    if section and len(section) <= 10:
                        section_upper = section.upper()
                        if section_upper not in found:
                            found.add(section_upper)
                            sections.append(section_upper)
                            section_coords[section_upper] = (lx, ly)
                            logger.debug("Found section '%s' at (%.0f, %.0f) tooltip='%s'", section_upper, lx, ly, tooltip)

        return SeatMap(
            source=SeatSource.CANVAS,
            sections=sections,
            section_coordinates=section_coords,
            canvas_width=cw,
            canvas_height=ch,
        )

    def _parse_section_from_tooltip(self, tooltip: str) -> Optional[str]:
        """Extract a clean section name from tooltip text.
        Handles formats like:
            'D9'
            'D9 - متاح'
            'القسم D9'
            'Section D9 - Available'
            'D9\n50 ريال'
            'مقصورة D9'
        """
        tooltip = tooltip.strip()
        if not tooltip:
            return None

        # Try direct match: one or two letters + digits (like D9, A1, B4, VIP)
        match = re.search(r'\b([A-Za-z]{1,4}\d{0,3})\b', tooltip)
        if match:
            return match.group(1)

        # Try digits + letter (like 9D)
        match = re.search(r'\b(\d{1,3}[A-Za-z]{1,3})\b', tooltip)
        if match:
            return match.group(1)

        # Try just "VIP", "VVIP", "Platform" etc.
        match = re.search(r'\b(VIP|VVIP|PLATFORM|CAT\s*\d+)\b', tooltip, re.IGNORECASE)
        if match:
            return match.group(1)

        # If very short, use as-is
        if len(tooltip) <= 5:
            return tooltip

        return None

    async def _hover_canvas(self, frame: Frame, cx: float, cy: float) -> str:
        """Hover over canvas and read ALL tooltip divs (sectionTooltip, seatTooltip, zoneTooltip)."""
        try:
            canvas_locator = frame.locator("#canvas")
            await canvas_locator.hover(position={"x": cx, "y": cy}, force=True)
            await asyncio.sleep(0.02)  # Significantly reduced from 0.15s to speed up scanning

            # Read all possible tooltip elements
            tooltip = await frame.evaluate("""() => {
                // Priority order: sectionTooltip > seatTooltip > zoneTooltip > objectTooltip
                const tooltips = ['sectionTooltip', 'seatTooltip', 'zoneTooltip', 'objectTooltip'];
                for (const id of tooltips) {
                    const el = document.getElementById(id);
                    if (el) {
                        const style = window.getComputedStyle(el);
                        const text = el.textContent.trim();
                        // Check if tooltip is visible and has content
                        if (text && style.visibility !== 'hidden' && style.display !== 'none' && el.offsetWidth > 0) {
                            return text;
                        }
                    }
                }
                return '';
            }""")
            return tooltip or ""
        except Exception:
            return ""

    async def click_section(self, section_name: str, event_id: str = "") -> bool:
        """Find and click a section on the SeatCloud canvas."""
        target = section_name.strip().upper()
        logger.info("Searching for section: %s", target)

        frame = self._frame or self._get_seatcloud_frame()
        if not frame:
            logger.error("SeatCloud frame not found")
            return False

        # Check cached coordinates first
        if event_id:
            cached_coords = await smart_cache.get_section_coordinates(event_id)
            if cached_coords and target in cached_coords:
                cx, cy = cached_coords[target]
                logger.info("Using cached coordinates for %s: (%.0f, %.0f)", target, cx, cy)
                success = await self._click_and_confirm_section(frame, cx, cy, target)
                if success:
                    return True
                logger.warning("Cached coords failed, falling back to scan")

        # Full canvas scan to find the section
        size = self._canvas_size or await self._get_canvas_size()
        if not size:
            return False

        cw = size.get("cssW", 0)
        ch = size.get("cssH", 0)
        if cw == 0 or ch == 0:
            return False

        # Use finer grid for section search
        steps_x = max(settings.SEAT_SCAN_GRID_X, 25)
        steps_y = max(settings.SEAT_SCAN_GRID_Y, 20)

        logger.info("Scanning canvas %dx%d with grid %dx%d for section %s...", cw, ch, steps_x, steps_y, target)

        # Scan outward from center (spiral search) because sections are usually centered
        center_row, center_col = steps_y / 2.0, steps_x / 2.0
        search_coords = []
        for row in range(steps_y):
            for col in range(steps_x):
                distance = (row - center_row)**2 + (col - center_col)**2
                search_coords.append((distance, row, col))
        
        # Sort by distance to center
        search_coords.sort(key=lambda x: x[0])

        for _, row, col in search_coords:
            lx = cw * (col + 0.5) / steps_x
            ly = ch * (row + 0.5) / steps_y

            tooltip = await self._hover_canvas(frame, lx, ly)
            if tooltip:
                parsed = self._parse_section_from_tooltip(tooltip)
                if parsed and parsed.upper() == target:
                    if "لا توجد" in tooltip or "unavailable" in tooltip.lower() or "sold" in tooltip.lower():
                        logger.warning("%s is unavailable at (%.0f,%.0f)", target, lx, ly)
                        continue

                    logger.info("Found %s at (%.0f, %.0f), tooltip='%s'", target, lx, ly, tooltip)
                    success = await self._click_and_confirm_section(frame, lx, ly, target)

                    if success:
                        # Cache the coordinates
                        if event_id:
                            coords = await smart_cache.get_section_coordinates(event_id) or {}
                            coords[target] = (lx, ly)
                            await smart_cache.set_section_coordinates(event_id, coords)
                        return True

        logger.warning("Section %s not found in canvas scan", target)
        return False

    async def _click_and_confirm_section(self, frame: Frame, cx: float, cy: float, section_name: str) -> bool:
        """Click canvas at position, then handle the GA popup that appears."""
        try:
            canvas_locator = frame.locator("#canvas")
            await canvas_locator.click(position={"x": cx, "y": cy}, force=True)
            logger.info("Clicked canvas at (%.0f, %.0f)", cx, cy)
            await asyncio.sleep(2)

            # Check if GA popup appeared (SeatCloud's section selection popup)
            ga_visible = await self._is_ga_popup_visible(frame)
            if ga_visible:
                logger.info("GA popup appeared for section %s", section_name)
                return True  # Popup is visible, caller will handle quantity

            # Try clicking again with a small offset
            await canvas_locator.click(position={"x": cx + 2, "y": cy + 2}, force=True)
            await asyncio.sleep(2)
            ga_visible = await self._is_ga_popup_visible(frame)
            if ga_visible:
                logger.info("GA popup appeared on second click for section %s", section_name)
                return True

            return False
        except Exception as e:
            logger.error("Click error: %s", e)
            return False

    async def _is_ga_popup_visible(self, frame: Frame) -> bool:
        """Check if the SeatCloud GA popup is visible."""
        try:
            return await frame.evaluate("""() => {
                const popup = document.getElementById('ga-popup');
                if (!popup) return false;
                const style = window.getComputedStyle(popup);
                return style.display !== 'none' && style.visibility !== 'hidden' && popup.offsetHeight > 0;
            }""")
        except Exception:
            return False

    async def set_quantity_in_ga_popup(self, frame: Frame, quantity: int) -> bool:
        """Set ticket quantity in the SeatCloud GA popup and confirm rapidly using JS."""
        try:
            logger.info("GA popup: target quantity=%d", quantity)

            # Rapidly click buttons using isolated JS context evaluation to avoid python sleep latency
            final = await frame.evaluate("""(targetQuantity) => {
                return new Promise((resolve) => {
                    const input = document.getElementById('ga-seat-count');
                    const increaseBtn = document.getElementById('ga-increase-seats');
                    const decreaseBtn = document.getElementById('ga-decrease-seats');
                    
                    if (!input) return resolve(0);
                    
                    let attempts = 0;
                    const clickUntil = () => {
                        let current = parseInt(input.value) || 0;
                        if (current === targetQuantity || attempts > 25) {
                            resolve(current);
                            return;
                        }
                        
                        const btn = current < targetQuantity ? increaseBtn : decreaseBtn;
                        if (!btn || btn.disabled) {
                            resolve(current);
                            return;
                        }
                        
                        btn.click();
                        attempts++;
                        setTimeout(clickUntil, 15);
                    };
                    
                    clickUntil();
                });
            }""", quantity)

            logger.info("GA popup: final quantity evaluated as %d", final)

            # Click Confirm
            await asyncio.sleep(0.1)
            # Try JS click first for speed
            await frame.evaluate("""() => { 
                const b = document.getElementById('ga-confirm-seats'); 
                if(b) b.click(); 
            }""")
            
            # Fallback to playwright click just in case
            try:
                await frame.click("#ga-confirm-seats", force=True, timeout=1000)
            except Exception:
                pass
                
            await asyncio.sleep(1)

            logger.info("GA popup confirmed with %d tickets", final)
            return True

        except Exception as e:
            logger.error("GA popup interaction error: %s", e)
            return False

    async def _parse_dom_sections(self) -> List[str]:
        """Extract sections from DOM elements."""
        sections = []
        patterns = [
            "[data-section]",
            ".section-name",
            "[data-seat-id]",
            '[aria-label*="مقعد"]',
        ]
        for pattern in patterns:
            try:
                elements = await self.page.query_selector_all(pattern)
                if elements:
                    for el in elements[:20]:
                        text = await el.get_attribute("data-section") or await el.text_content()
                        if text and len(text.strip()) <= 8:
                            sections.append(text.strip().upper())
                    if sections:
                        break
            except Exception:
                continue
        return list(set(sections))

    async def take_screenshot(self, user_id: int) -> str:
        """Take screenshot of the seat map area."""
        import os
        os.makedirs("screenshots", exist_ok=True)
        filename = f"screenshots/seatmap_{user_id}_{int(time.time())}.png"

        try:
            frame = self._get_seatcloud_frame()
            if frame:
                iframe_el = await self.page.query_selector(
                    '#seats-iframe, iframe[src*="seatcloud"], iframe[src*="chart"]'
                )
                if iframe_el:
                    await iframe_el.screenshot(path=filename)
                    logger.info("SeatCloud screenshot saved: %s", filename)
                    return filename

            await self.page.screenshot(path=filename, full_page=False)
            logger.info("Full page screenshot saved: %s", filename)

        except Exception as e:
            logger.error("Screenshot error: %s", e)
            try:
                await self.page.screenshot(path=filename)
            except Exception:
                pass

        return filename
