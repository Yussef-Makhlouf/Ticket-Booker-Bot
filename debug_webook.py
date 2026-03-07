import asyncio
from playwright.async_api import async_playwright
import os

async def debug_webook(email, password, event_url):
    print("Starting playwright debug...")
    os.makedirs('screenshots', exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ar-SA',
            timezone_id='Asia/Riyadh'
        )
        page = await context.new_page()
        
        try:
            print("Navigating to login page...")
            await page.goto("https://webook.com/ar/login", wait_until='networkidle')
            await asyncio.sleep(5)
            await page.screenshot(path='screenshots/01_login_page.png')
            
            print("Filling credentials...")
            # Try multiple selectors
            try:
                await page.fill('input[type="email"], input[name="email"], [autocomplete="email"], #email', email)
                await page.fill('input[type="password"], input[name="password"], #password', password)
                await page.screenshot(path='screenshots/02_filled_credentials.png')
                
                await page.click('button[type="submit"], button:has-text("تسجيل الدخول"), .login-btn')
                print("Clicked submit. Waiting...")
                await asyncio.sleep(5)
                await page.screenshot(path='screenshots/03_after_submit.png')
            except Exception as e:
                print(f"Error during login form interaction: {e}")
                
            print(f"Navigating to event page: {event_url}...")
            await page.goto(event_url, wait_until='networkidle')
            await asyncio.sleep(5)
            await page.screenshot(path='screenshots/04_event_page.png')
            
            # Save HTML to analyze extraction issues
            html_content = await page.content()
            with open("debug_event_page.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("Saved HTML to debug_event_page.html")
            
        except Exception as e:
            print(f"An error occurred: {e}")
            await page.screenshot(path='screenshots/xx_error.png')
            
        await browser.close()

if __name__ == "__main__":
    email = "yussef.ali.it@gmail.com"
    password = "Yussefalo@12345"
    event_url = "https://webook.com/ar/events/rsl-al-ettifaq-vs-al-riyadh-123554/book"
    asyncio.run(debug_webook(email, password, event_url))
