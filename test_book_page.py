import asyncio
from playwright.async_api import async_playwright
import os

async def test_book_page():
    print("Starting Playwright check...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        url = 'https://webook.com/ar/events/rsl-al-ettifaq-vs-al-riyadh-123554/book'
        print(f"Navigating to {url}...")
        
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(5)
        
        # Take screenshot of what it looks like before anything
        os.makedirs('screenshots', exist_ok=True)
        await page.screenshot(path='screenshots/debug_book_page.png')
        print("Screenshot saved to screenshots/debug_book_page.png")
        
        html = await page.content()
        with open('debug_book_url.html', 'w', encoding='utf-8') as f:
            f.write(html)
            
        print("Saved HTML to debug_book_url.html")
        
        print("Final URL is:", page.url)
        
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(test_book_page())
