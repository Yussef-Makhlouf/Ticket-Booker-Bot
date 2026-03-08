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

    async def scan_all_sections_with_availability(self) -> Dict[str, Dict]:
        """
        Scan the entire canvas and return all sections with their availability status.
        Returns: Dict[section_name] = {status: 'available'|'unavailable', coordinates: (x, y), tooltip: str}
        """
        sections_info: Dict[str, Dict] = {}
        
        frame = self._frame or self._get_seatcloud_frame()
        if not frame:
            logger.warning("No SeatCloud frame found for section scanning")
            return sections_info
        
        size = self._canvas_size or await self._get_canvas_size()
        if not size:
            return sections_info
        
        cw = size.get("cssW", 0)
        ch = size.get("cssH", 0)
        if cw == 0 or ch == 0:
            return sections_info
        
        # Use a finer grid to scan all sections
        steps_x = 30
        steps_y = 25
        found: set = set()
        
        logger.info(f"Scanning all sections with availability on {cw}x{ch} canvas...")
        
        for row in range(steps_y):
            for col in range(steps_x):
                lx = cw * (col + 0.5) / steps_x
                ly = ch * (row + 0.5) / steps_y
                
                tooltip = await self._hover_canvas(frame, lx, ly)
                # Allow longer tooltips - some contain price info
                if not tooltip or len(tooltip) > 80:
                    continue
                
                # Parse section name
                section = self._parse_section_from_tooltip(tooltip)
                if not section or len(section) > 12:
                    continue
                
                section_upper = section.upper()
                if section_upper in found:
                    continue
                found.add(section_upper)
                
                # Determine availability
                is_available = True
                if "لا توجد" in tooltip or "unavailable" in tooltip.lower() or "sold" in tooltip.lower() or "غير متاح" in tooltip:
                    is_available = False
                
                sections_info[section_upper] = {
                    "status": "available" if is_available else "unavailable",
                    "coordinates": (lx, ly),
                    "tooltip": tooltip,
                    "full_text": tooltip
                }
                logger.info(f"Section {section_upper}: {'AVAILABLE' if is_available else 'UNAVAILABLE'} - {tooltip[:40]}")
        
        logger.info(f"Found {len(sections_info)} unique sections")
        return sections_info

    async def scan_seats_in_section(self, frame: Frame = None) -> List[Dict]:
        """
        After clicking a section and zooming in, scan for individual seats.
        Returns list of seats with their details (row, seat, price, availability).
        """
        seats = []
        
        if not frame:
            frame = self._frame or self._get_seatcloud_frame()
        if not frame:
            logger.warning("No SeatCloud frame for seat scanning")
            return seats
        
        size = await self._get_canvas_size()
        if not size:
            return seats
        
        cw = size.get("cssW", 0)
        ch = size.get("cssH", 0)
        if cw == 0 or ch == 0:
            return seats
        
        # Fine grid for seat detection
        steps_x, steps_y = 40, 40
        found_seats: set = set()
        
        logger.info(f"Scanning for individual seats on {cw}x{ch} canvas...")
        
        for row in range(steps_y):
            for col in range(steps_x):
                lx = cw * (col + 0.5) / steps_x
                ly = ch * (row + 0.5) / steps_y
                
                tooltip = await self._hover_canvas(frame, lx, ly)
                if not tooltip:
                    continue
                
                tooltip_lower = tooltip.lower()
                
                # Check if this is a seat (look for row, seat, price indicators)
                is_seat = False
                seat_info = {}
                
                # Try to extract row and seat number
                # Patterns: "الصف 1، المقعد 5" or "Row 1, Seat 5" or just "1-5"
                row_match = re.search(r'(?:الصف|row|صف)\s*[:\-\s]*(\d+)', tooltip_lower)
                seat_match = re.search(r'(?:مقعد|seat|座位)\s*[:\-\s]*(\d+)', tooltip_lower)
                
                if row_match or seat_match:
                    is_seat = True
                    seat_info["row"] = row_match.group(1) if row_match else ""
                    seat_info["seat"] = seat_match.group(1) if seat_match else ""
                
                # Try to extract price
                price_match = re.search(r'(\d+)\s*(?:ريال|sar|ر\.س)', tooltip_lower)
                if price_match:
                    seat_info["price"] = price_match.group(1)
                    is_seat = True
                
                # Check availability
                is_available = True
                if "لا توجد" in tooltip or "unavailable" in tooltip_lower or "sold" in tooltip_lower or "غير متاح" in tooltip:
                    is_available = False
                elif "متاح" in tooltip or "available" in tooltip_lower or "انقر" in tooltip:
                    is_available = True
                
                if is_seat and (seat_info.get("row") or seat_info.get("seat")):
                    seat_key = f"{seat_info.get('row', '')}-{seat_info.get('seat', '')}"
                    if seat_key not in found_seats:
                        found_seats.add(seat_key)
                        seat_info["available"] = is_available
                        seat_info["coordinates"] = (lx, ly)
                        seat_info["tooltip"] = tooltip
                        seats.append(seat_info)
                        status_str = "✓ متاح" if is_available else "✗ غير متاح"
                        logger.info(f"Seat {seat_info.get('row', '')}-{seat_info.get('seat', '')}: {status_str} - {tooltip[:30]}")
        
        logger.info(f"Found {len(seats)} individual seats")
        return seats

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

    def _parse_section_from_tooltip(self, tooltip: str, target_section: str = None) -> Optional[str]:
        """Extract a clean section name from tooltip text.
        Handles formats like:
            'D9'
            'D9 - متاح'
            'القسم D9'
            'Section D9 - Available'
            'D9\n50 ريال'
            'مقصورة D9'
            'D910CAT 1 - R' (section D9, category 10)
        
        If target_section is provided, performs fuzzy matching to find it.
        """
        tooltip = tooltip.strip()
        if not tooltip:
            return None
        
        # If we have a target section, do fuzzy matching
        if target_section:
            tooltip_upper = tooltip.upper()
            target_upper = target_section.upper()
            
            # Direct match - check if target is in tooltip
            if target_upper in tooltip_upper:
                # Find the position and verify it's a proper section match
                pos = tooltip_upper.find(target_upper)
                if pos >= 0:
                    # Check what comes before and after
                    before = tooltip_upper[:pos] if pos > 0 else ''
                    after = tooltip_upper[pos + len(target_upper):] if pos + len(target_upper) < len(tooltip_upper) else ''
                    # Valid if: at start OR preceded by non-letter, at end OR followed by non-digit
                    valid = (pos == 0 or not before[-1:].isalpha()) and (len(after) == 0 or not after[:1].isdigit())
                    if valid:
                        return target_section
            
            # Check if target is prefix of found section (e.g., D9 in D910CAT)
            all_sections = re.findall(r'\b([A-Za-z]{1,4}\d{1,3})\b', tooltip)
            for section in all_sections:
                section_upper = section.upper()
                # D9 matches D910, D99, etc. but not D10
                if section_upper.startswith(target_upper) or target_upper.startswith(section_upper):
                    # Prefer the shorter match (the target)
                    if len(section) >= len(target_section):
                        return target_section
                    return section
        
        # Try direct match: one or two letters + digits (like D9, A1, B4)
        # Force at least one digit to avoid matching pure text words like 'SAR'
        match = re.search(r'\b([A-Za-z]{1,4}\d{1,3})\b', tooltip)
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
            # SeatCloud hit-testing JS relies on mouse move debouncing. 0.15s is the minimum safe delay.
            # Faster speeds (like 0.08s) break JS debouncers causing tooltips to remain invisible.
            await asyncio.sleep(0.15) 

            # Read all possible tooltip elements
            tooltip = await frame.evaluate("""() => {
                // Priority order: sectionTooltip > seatTooltip > zoneTooltip > objectTooltip
                const tooltips = ['sectionTooltip', 'seatTooltip', 'zoneTooltip', 'objectTooltip'];
                for (const id of tooltips) {
                    const el = document.getElementById(id);
                    if (el) {
                        const style = window.getComputedStyle(el);
                        let text = (el.innerText || el.textContent || '').trim();
                        text = text.replace(/\\n|\\r/g, ' ');
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

    async def click_section(self, section_name: str, event_id: str = "") -> str:
        """Find and click a section on the SeatCloud canvas. Returns status string."""
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
                status = await self._click_and_confirm_section(frame, cx, cy, target)
                if status != 'FAILED':
                    return status
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
                logger.info("Scanned (%.0f, %.0f) -> '%s'", lx, ly, tooltip.replace('\n', ' '))
                # Pass target section for fuzzy matching (e.g., D9 in D910CAT)
                parsed = self._parse_section_from_tooltip(tooltip, target)
                tooltip_upper = tooltip.upper()
                # Check if the parsed section matches, OR if the target is explicitly mentioned as a word in the tooltip
                if (parsed and parsed.upper() == target) or (re.search(rf'\b{re.escape(target)}\b', tooltip_upper)):
                    if "لا توجد" in tooltip or "unavailable" in tooltip.lower() or "sold" in tooltip.lower() or "إلغاء" in tooltip:
                        logger.warning("%s is unavailable at (%.0f,%.0f)", target, lx, ly)
                        continue

                    logger.info("Found %s at (%.0f, %.0f), tooltip='%s'", target, lx, ly, tooltip)
                    status = await self._click_and_confirm_section(frame, lx, ly, target)

                    if status != 'FAILED':
                        # Cache the coordinates
                        if event_id:
                            coords = await smart_cache.get_section_coordinates(event_id) or {}
                            coords[target] = (lx, ly)
                            await smart_cache.set_section_coordinates(event_id, coords)
                        return status

        logger.warning("Section %s not found in canvas scan", target)
        return 'FAILED'

    async def _click_and_confirm_section(self, frame: Frame, cx: float, cy: float, section_name: str) -> str:
        """Click canvas at position, then handle the GA popup or Zoom that occurs."""
        try:
            canvas_locator = frame.locator("#canvas")
            
            # Record old canvas state to detect zoom
            old_size = await self._get_canvas_size()
            
            await canvas_locator.click(position={"x": cx, "y": cy}, force=True)
            logger.info("Clicked canvas at (%.0f, %.0f)", cx, cy)
            await asyncio.sleep(2)

            # Check if GA popup appeared (SeatCloud's section selection popup)
            ga_visible = await self._is_ga_popup_visible(frame)
            if ga_visible:
                logger.info("GA popup appeared for section %s", section_name)
                return 'GA_POPUP'
                
            # If no GA popup, check if the canvas changed/zoomed or a side panel appeared
            # For SeatCloud, usually zooming in changes the visual representation on the canvas.
            # We assume if the click didn't fail and didn't open GA, we bounded into Reserved seating.
            logger.info("No GA popup for section %s. Assuming zoomed into Reserved Seating.", section_name)
            return 'ZOOMED'
            
        except Exception as e:
            logger.error("Click error: %s", e)
            return 'FAILED'

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

    async def select_reserved_seats(self, frame: Frame, required_count: int) -> bool:
        """
        Scan the zoomed-in canvas to find and click individual reserved seats.
        Uses fast JS pixel analysis to find green seats as a priority,
        falling back to a spiral grid scan if needed.
        """
        logger.info("Scanning for %d individual reserved seats...", required_count)
        
        # Wait a moment for zoom transition to finish
        await asyncio.sleep(2)
        
        size = await self._get_canvas_size()
        if not size:
            return False

        cw = size.get("cssW", 0)
        ch = size.get("cssH", 0)
        aw = size.get("attrW", 0)
        ah = size.get("attrH", 0)
        if cw == 0 or ch == 0 or aw == 0 or ah == 0:
            return False

        selected_count = 0
        clicked_coords = set()
        canvas_locator = frame.locator("#canvas")

        # STRATEGY 1: VERY FAST PIXEL ANALYSIS VIA JS
        # Look for green pixels in the canvas
        logger.info("Attempting fast JS pixel scan for available seats...")
        pixel_centers = []
        try:
            # Inject JS to find green pixels and cluster them
            js_script = """(args) => {
                const canvas = document.getElementById('canvas');
                if (!canvas) return {error: "No canvas"};
                
                try {
                    const ctx = canvas.getContext('2d', { willReadFrequently: true });
                    const w = canvas.width;
                    const h = canvas.height;
                    const imgData = ctx.getImageData(0, 0, w, h);
                    const data = imgData.data;
                    
                    const points = [];
                    // Available seats are usually bright green in SeatCloud
                    for (let i = 0; i < data.length; i += 4) {
                        const r = data[i];
                        const g = data[i+1];
                        const b = data[i+2];
                        const a = data[i+3];
                        
                        // Condition for the green seat color
                        if (a > 200 && g > 150 && r < 100 && b < 100) {
                            const p = i / 4;
                            const x = p % w;
                            const y = Math.floor(p / w);
                            
                            // Scale to CSS coordinates
                            const cssX = x * (args.cw / w);
                            const cssY = y * (args.ch / h);
                            points.push({x: cssX, y: cssY});
                        }
                    }
                    
                    if (points.length === 0) return {centers: []};
                    
                    // Simple clustering (group points within 15px CSS distance)
                    const centers = [];
                    const threshold = 15;
                    
                    for (const p of points) {
                        let foundCluster = false;
                        for (const c of centers) {
                            const dx = c.x - p.x;
                            const dy = c.y - p.y;
                            if (Math.sqrt(dx*dx + dy*dy) < threshold) {
                                // Add to cluster, update average
                                c.x = (c.x * c.count + p.x) / (c.count + 1);
                                c.y = (c.y * c.count + p.y) / (c.count + 1);
                                c.count++;
                                foundCluster = true;
                                break;
                            }
                        }
                        if (!foundCluster) {
                            centers.push({x: p.x, y: p.y, count: 1});
                        }
                    }
                    
                    // Filter out noise (clusters with very few points)
                    const validCenters = centers.filter(c => c.count > 10).map(c => ({x: c.x, y: c.y}));
                    
                    // Sort centers: we want seats near the center of the viewport first
                    const midX = args.cw / 2;
                    const midY = args.ch / 2;
                    validCenters.sort((a,b) => {
                        const da = Math.pow(a.x - midX, 2) + Math.pow(a.y - midY, 2);
                        const db = Math.pow(b.x - midX, 2) + Math.pow(b.y - midY, 2);
                        return da - db;
                    });
                    
                    return {centers: validCenters};
                } catch(e) {
                    return {error: e.toString()};
                }
            }"""
            
            result = await frame.evaluate(js_script, {"cw": cw, "ch": ch})
            
            if "error" not in result and "centers" in result and result["centers"]:
                pixel_centers = result["centers"]
                logger.info("JS pixel scan found %d potential green seat clusters.", len(pixel_centers))
            else:
                logger.warning("JS pixel scan returned no clusters or error: %s", result.get('error', 'None'))
        except Exception as e:
            logger.warning("JS pixel scan failed: %s", e)

        # Process the pixel centers if any
        for center in pixel_centers:
            if selected_count >= required_count:
                break
                
            lx, ly = center['x'], center['y']
            
            tooltip = await self._hover_canvas(frame, lx, ly)
            if not tooltip:
                continue
                
            tooltip_lower = tooltip.lower()
            
            is_available = False
            if "متاح" in tooltip or "انقر" in tooltip or "available" in tooltip_lower:
                is_available = True
            elif re.search(r'\d+\s*(ريال|sar|sar)', tooltip_lower):
                is_available = True
                
            if "لا توجد" in tooltip or "unavailable" in tooltip_lower or "sold" in tooltip_lower or "إلغاء" in tooltip:
                is_available = False
                
            is_seat = False
            if is_available:
                if re.search(r'\d+\s*(ريال|sar)', tooltip_lower) or "صف" in tooltip_lower or "مقعد" in tooltip_lower or "row" in tooltip_lower or "seat" in tooltip_lower:
                    is_seat = True
            
            if is_available:
                logger.info("Found %s at (%.0f, %.0f), tooltip='%s'", "Seat" if is_seat else "Sub-block", lx, ly, tooltip.replace('\n', ' '))
                try:
                    await canvas_locator.click(position={"x": lx, "y": ly}, force=True)
                    clicked_coords.add((lx, ly))
                    
                    if is_seat:
                        selected_count += 1
                        logger.info("Successfully clicked seat %d/%d", selected_count, required_count)
                        await asyncio.sleep(0.5) 
                    else:
                        logger.info("Clicked Sub-block. Zooming in deeper to find seats...")
                        await asyncio.sleep(2) 
                        return await self.select_reserved_seats(frame, required_count)
                        
                except Exception as e:
                    logger.error("Failed to click at (%.0f, %.0f): %s", lx, ly, e)

        if selected_count >= required_count:
            logger.info("Successfully selected %d reserved seats.", selected_count)
            return True

        # STRATEGY 2: FALLBACK TO SPIRAL SEARCH
        if selected_count < required_count:
            logger.info("Pixel clustering insufficient. Falling back to spiral grid scan...")
            
            steps_x, steps_y = 25, 25
            
            center_row, center_col = steps_y / 2.0, steps_x / 2.0
            search_coords = []
            for row in range(steps_y):
                for col in range(steps_x):
                    distance = (row - center_row)**2 + (col - center_col)**2
                    search_coords.append((distance, row, col))
            
            search_coords.sort(key=lambda x: x[0])

            for _, row, col in search_coords:
                if selected_count >= required_count:
                    break
                    
                lx = cw * (col + 0.5) / steps_x
                ly = ch * (row + 0.5) / steps_y
                
                is_too_close = False
                for dx, dy in clicked_coords:
                    if abs(dx - lx) < (cw / steps_x) * 1.5 and abs(dy - ly) < (ch / steps_y) * 1.5:
                        is_too_close = True
                        break
                if is_too_close:
                    continue

                tooltip = await self._hover_canvas(frame, lx, ly)
                if not tooltip:
                    continue
                    
                tooltip_lower = tooltip.lower()
                
                is_available = False
                if "متاح" in tooltip or "انقر" in tooltip or "available" in tooltip_lower:
                    is_available = True
                elif re.search(r'\d+\s*(ريال|sar|sar)', tooltip_lower):
                    is_available = True
                    
                if "لا توجد" in tooltip or "unavailable" in tooltip_lower or "sold" in tooltip_lower or "إلغاء" in tooltip:
                    is_available = False
                    
                is_seat = False
                if is_available:
                    if re.search(r'\d+\s*(ريال|sar)', tooltip_lower) or "صف" in tooltip_lower or "مقعد" in tooltip_lower or "row" in tooltip_lower or "seat" in tooltip_lower:
                        is_seat = True
                
                if is_available:
                    logger.info("Found %s at (%.0f, %.0f), tooltip='%s'", "Seat" if is_seat else "Sub-block", lx, ly, tooltip.replace('\n', ' '))
                    try:
                        await canvas_locator.click(position={"x": lx, "y": ly}, force=True)
                        clicked_coords.add((lx, ly))
                        
                        if is_seat:
                            selected_count += 1
                            logger.info("Successfully clicked seat %d/%d", selected_count, required_count)
                            await asyncio.sleep(0.5) 
                        else:
                            logger.info("Clicked Sub-block. Zooming in deeper to find seats...")
                            await asyncio.sleep(2) 
                            return await self.select_reserved_seats(frame, required_count)
                            
                    except Exception as e:
                        logger.error("Failed to click at (%.0f, %.0f): %s", lx, ly, e)

        if selected_count >= required_count:
            logger.info("Successfully selected %d reserved seats.", selected_count)
            return True
        else:
            logger.warning("Could only select %d/%d reserved seats in visible area.", selected_count, required_count)
            return selected_count > 0 # Return True if we managed to get at least some seats

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
