from playwright.async_api import Page
from bs4 import BeautifulSoup
from typing import Dict, Optional
import re

class EventScraper:
    def __init__(self, page: Page):
        self.page = page
    
    async def extract_event_data(self) -> Dict:
        """Extract all event information from Webook page"""
        
        event_data = {
            'name': None,
            'type': None,
            'teams': [],
            'date': None,
            'time': None,
            'venue': None,
            'city': None,
            'price_range': {'min': 0, 'max': 0},
            'sections': [],
            'image_url': None,
            'description': None
        }
        
        try:
            # Wait for content to load and any h1 or h2 to appear (indicates React is done)
            await self.page.wait_for_load_state('networkidle')
            try:
                await self.page.wait_for_selector('h1, h2, .text-heading-XL', timeout=15000)
            except:
                pass # Continue anyway, the page might not have them
            
            await self.page.wait_for_timeout(3000)
            
            # Get page HTML
            html = await self.page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # 1. Extract Event Name
            name_selectors = [
                'h1',
                'h2.text-heading-XL',
                '.event-title',
                '.text-heading-L',
                '[data-event-name]',
                'title' # Fallback to page title
            ]
            for selector in name_selectors:
                elements = soup.select(selector)
                for element in elements:
                    text = element.get_text(strip=True)
                    if text and len(text) > 3 and "webook.com" not in text.lower():
                        event_data['name'] = text
                        break
                if event_data['name']:
                    break
                    
            if not event_data['name'] and soup.title:
                # E.g. "دوري روشن 25/26 - الإتفاق × الرياض - الجولة 28 | webook.com"
                title_text = soup.title.string
                if title_text:
                    event_data['name'] = title_text.split('|')[0].strip()
            
            # 2. Extract Teams (for matches)
            team_selectors = [
                '.team-name',
                '[data-team-name]',
                '.vs-container .team',
                '.match-teams .team'
            ]
            for selector in team_selectors:
                teams = soup.select(selector)
                if teams:
                    event_data['teams'] = [t.get_text(strip=True) for t in teams[:2]]
                    break
            
            # 3. Extract Date & Time
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{4}-\d{2}-\d{2})',
                r'(\d{1,2}\s+(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر|\w+)\s+\d{4})'
            ]
            
            date_selectors = [
                '.event-date',
                '[data-date]',
                '.date-time',
                'p', 'span', 'div' # Fallback to all text blocks looking for a date pattern
            ]
            
            for selector in date_selectors:
                elements = soup.select(selector)
                for element in elements:
                    text = element.get_text(strip=True)
                    for pattern in date_patterns:
                        match = re.search(pattern, text)
                        if match:
                            event_data['date'] = match.group(1)
                            break
                    if event_data['date']:
                        break
                if event_data['date']:
                    break
            
            # 4. Extract Venue
            venue_selectors = [
                '.venue-name',
                '[data-venue]',
                '.stadium-name',
                '.event-location'
            ]
            for selector in venue_selectors:
                element = soup.select_one(selector)
                if element:
                    event_data['venue'] = element.get_text(strip=True)
                    break
            
            # 5. Extract Price Range
            price_selectors = [
                '.price',
                '[data-price]',
                '.ticket-price',
                '.category-price'
            ]
            prices = []
            for selector in price_selectors:
                elements = soup.select(selector)
                for el in elements:
                    text = el.get_text(strip=True)
                    # Extract numbers from text like "30 ريال" or "SAR 50"
                    price_match = re.search(r'(\d+)', text)
                    if price_match:
                        prices.append(int(price_match.group(1)))
            
            if prices:
                event_data['price_range']['min'] = min(prices)
                event_data['price_range']['max'] = max(prices)
            
            # 6. Extract Sections
            section_selectors = [
                '.section-name',
                '[data-section]',
                '.category-name',
                '.zone-name'
            ]
            for selector in section_selectors:
                elements = soup.select(selector)
                if elements:
                    event_data['sections'] = [
                        {
                            'name': el.get_text(strip=True),
                            'id': el.get('data-section-id', '')
                        }
                        for el in elements[:10]  # Limit to 10
                    ]
                    break
            
            # 7. Extract Event Image
            img_selectors = [
                '.event-image img',
                '[data-event-image]',
                '.hero-image img',
                'meta[property="og:image"]'
            ]
            for selector in img_selectors:
                element = soup.select_one(selector)
                if element:
                    event_data['image_url'] = element.get('src') or element.get('content')
                    break
            
            # 8. Determine Event Type
            if event_data['teams'] and len(event_data['teams']) >= 2:
                event_data['type'] = 'match'
            elif 'concert' in (event_data['name'] or '').lower():
                event_data['type'] = 'concert'
            else:
                event_data['type'] = 'general'
            
        except Exception as e:
            print(f"Error extracting event data: {e}")
        
        return event_data
    
    async def get_available_teams(self) -> list:
        """Extract teams for match events"""
        teams = []
        
        try:
            team_selectors = [
                '[data-team]',
                '.team-option',
                '.team-card'
            ]
            
            for selector in team_selectors:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    for el in elements:
                        team_name = await el.get_attribute('data-team')
                        if not team_name:
                            team_name = await el.text_content()
                        if team_name:
                            teams.append(team_name.strip())
                    break
        except:
            pass
        
        return teams[:2]  # Return max 2 teams
    
    async def get_price_categories(self) -> list:
        """Extract available price categories"""
        categories = []
        
        try:
            await self.page.wait_for_selector('[class*="price"], [class*="category"]', timeout=10000)
            
            price_elements = await self.page.query_selector_all(
                '[data-price], .price-category, .ticket-category'
            )
            
            for el in price_elements[:5]:
                try:
                    price_text = await el.text_content()
                    price_match = re.search(r'(\d+)', price_text)
                    if price_match:
                        categories.append({
                            'price': int(price_match.group(1)),
                            'element': el
                        })
                except:
                    continue
        except:
            pass
        
        return categories
