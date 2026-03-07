import asyncio
from playwright.async_api import async_playwright
import os

async def run_test():
    url = "https://webook.com/ar/events/marina-beach" # Just a sample Webook URL, we can change it to whatever event they tried
    
    print("Starting playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage'
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await context.new_page()
        
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until='load', timeout=30000)
            await page.wait_for_timeout(5000)
            print("Page loaded. Taking screenshot...")
            os.makedirs('screenshots', exist_ok=True)
            await page.screenshot(path='screenshots/debug_load.png')
            
            # Print page title
            title = await page.title()
            print(f"Page Title: {title}")
            
            # Try to print some extracted elements
            html = await page.content()
            if "cloudflare" in html.lower():
                print("Cloudflare detected in HTML!")
            else:
                print("No Cloudflare detected.")
                
            print("Done. Saved screenshot to screenshots/debug_load.png")
            
        except Exception as e:
            print(f"Error: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_test())
