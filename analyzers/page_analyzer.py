"""
HTML/DOM structure analysis for event pages.
Extracts structured event data from any Webook page format.

Webook uses a React SPA so event data is found in:
- <title> tag (e.g. "دوري روشن 25/26 - الإتفاق × الرياض - الجولة 28 | webook.com")
- og:title meta
- og:image meta (event poster)
- meta description
- Page title itself
"""
import re
import time
import logging
from typing import Dict, Optional
from playwright.async_api import Page
from data.models import EventData
from services.smart_cache import smart_cache

logger = logging.getLogger("automation")


class PageAnalyzer:
    """Extract event information from Webook pages."""

    def __init__(self, page: Page):
        self.page = page

    async def extract_event_data(self, event_id: str = "") -> EventData:
        """Extract all event info. Checks cache first."""
        # Check cache
        if event_id:
            cached = await smart_cache.get_event_data(event_id)
            if cached:
                logger.info("Using cached event data for %s", event_id)
                return EventData(**cached)

        start = time.perf_counter()
        event = EventData()

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            await self.page.wait_for_timeout(3000)

            # --- Strategy 1: Meta tags (most reliable for Webook React SPA) ---
            meta_data = await self.page.evaluate("""() => {
                const getMeta = (name) => {
                    const el = document.querySelector(
                        `meta[property="${name}"], meta[name="${name}"]`
                    );
                    return el ? el.getAttribute('content') : '';
                };
                return {
                    title: document.title || '',
                    ogTitle: getMeta('og:title'),
                    ogImage: getMeta('og:image') || getMeta('twitter:image'),
                    description: getMeta('description'),
                    ogUrl: getMeta('og:url'),
                    canonical: (document.querySelector('link[rel="canonical"]') || {}).href || '',
                };
            }""")

            logger.debug("Meta data extracted: title='%s', og:title='%s'",
                         meta_data.get("title", "")[:60],
                         meta_data.get("ogTitle", "")[:60])

            # Extract event name from og:title or page title
            og_title = meta_data.get("ogTitle", "")
            page_title = meta_data.get("title", "")

            # Page title format: "دوري روشن 25/26 - الإتفاق × الرياض - الجولة 28 | webook.com"
            if og_title:
                event.name = og_title.strip()
            elif page_title:
                # Remove "| webook.com" suffix
                event.name = re.sub(r'\s*\|\s*webook\.com\s*$', '', page_title).strip()

            # Extract teams from the name (pattern: "X × Y" or "X vs Y")
            event.teams = self._extract_teams_from_name(event.name)
            event.event_type = "match" if len(event.teams) >= 2 else "general"

            # Image URL (use og:image, not inline images which may be missing)
            og_image = meta_data.get("ogImage", "")
            if og_image and og_image.startswith("http"):
                event.image_url = og_image

            # Description
            event.description = meta_data.get("description", "")

            # Extract date from page content
            event.date = await self._extract_date_from_page()

            # Extract venue from page content
            event.venue = await self._extract_venue_from_page()

            # --- Strategy 2: Try to get event details from __NEXT_DATA__ or visible elements ---
            if not event.name or event.name == "webook.com":
                event.name = await self._extract_name_from_dom()

            # --- Strategy 3: Extract from URL ---
            if not event.name:
                event.name = self._extract_name_from_url(self.page.url)

            event.url = self.page.url

        except Exception as e:
            logger.error("Event data extraction error: %s", e)

        event.extraction_time = time.perf_counter() - start
        logger.info(
            "Extracted event: name='%s', type='%s', teams=%s in %.2fs",
            event.name[:50] if event.name else "?",
            event.event_type,
            event.teams,
            event.extraction_time,
        )

        # Cache the result
        if event_id and event.name:
            await smart_cache.set_event_data(event_id, {
                "name": event.name,
                "event_type": event.event_type,
                "teams": event.teams,
                "date": event.date,
                "venue": event.venue,
                "price_range": event.price_range,
                "image_url": event.image_url,
            })

        return event

    def _extract_teams_from_name(self, name: str) -> list:
        """Extract team names from event name.
        Handles patterns:
            'الإتفاق × الرياض'
            'الهلال vs الاتحاد'
            'Al Hilal vs Al Ittihad'
        """
        if not name:
            return []

        # Pattern: "Team1 × Team2" or "Team1 vs Team2" (with surrounding text)
        for sep in ["×", "vs", "ضد", " x ", "VS"]:
            if sep in name:
                parts = name.split(sep)
                if len(parts) >= 2:
                    # Clean: take the last part of left and first part of right
                    left = parts[0].strip()
                    right = parts[1].strip()

                    # Try to extract just the team name (after last dash/hyphen)
                    team1 = left.rsplit("-", 1)[-1].rsplit("–", 1)[-1].strip()
                    team2 = right.split("-")[0].split("–")[0].strip()

                    if team1 and team2:
                        return [team1, team2]

        return []

    async def _extract_date_from_page(self) -> str:
        """Extract event date from page."""
        try:
            # Try reading from visible text
            result = await self.page.evaluate("""() => {
                const datePatterns = [
                    /(\d{1,2}\/\d{1,2}\/\d{4})/,
                    /(\d{4}-\d{2}-\d{2})/,
                    /(\d{1,2}\s+(?:يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s+\d{4})/,
                    /(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})/i
                ];
                
                // Check structured data
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        if (data.startDate) return data.startDate;
                    } catch(e) {}
                }
                
                // Check visible text
                const text = document.body?.innerText || '';
                for (const p of datePatterns) {
                    const m = text.match(p);
                    if (m) return m[1];
                }
                return '';
            }""")
            return result or ""
        except Exception:
            return ""

    async def _extract_venue_from_page(self) -> str:
        """Extract venue from page."""
        try:
            result = await self.page.evaluate("""() => {
                // Check structured data first
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        if (data.location?.name) return data.location.name;
                    } catch(e) {}
                }
                
                // Check known selectors
                const selectors = ['.venue-name', '[data-venue]', '.stadium-name', '.event-location'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) return el.textContent.trim();
                }
                return '';
            }""")
            return result or ""
        except Exception:
            return ""

    async def _extract_name_from_dom(self) -> str:
        """Fallback: extract event name from DOM h1/h2 elements."""
        try:
            result = await self.page.evaluate("""() => {
                const selectors = ['h1', 'h2', '.event-title', '.text-heading-L', '.text-heading-XL'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const t = el.textContent.trim();
                        if (t && t.length > 4 && !t.includes('webook') && !t.includes('كوكيز')
                            && !t.includes('تسجيل الدخول') && t.length < 200) {
                            return t;
                        }
                    }
                }
                return '';
            }""")
            return result or ""
        except Exception:
            return ""

    def _extract_name_from_url(self, url: str) -> str:
        """Extract a human-readable name from the URL slug."""
        # URL like: /events/rsl-al-ettifaq-vs-al-riyadh-123554/book
        match = re.search(r'/events/([^/]+?)(?:-\d+)?(?:/book)?/?$', url)
        if match:
            slug = match.group(1)
            return slug.replace("-", " ").title()
        return ""

    async def get_available_teams(self) -> list:
        """Extract team options from interactive elements."""
        teams = []
        try:
            result = await self.page.evaluate("""() => {
                const teams = [];
                const selectors = ['[data-team]', '.team-option', '.team-card', 'button[class*="team"]'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const name = el.getAttribute('data-team') || el.textContent.trim();
                        if (name && name.length > 1 && name.length < 50) {
                            teams.push(name);
                        }
                    }
                    if (teams.length > 0) break;
                }
                return teams.slice(0, 2);
            }""")
            return result or []
        except Exception:
            return []
