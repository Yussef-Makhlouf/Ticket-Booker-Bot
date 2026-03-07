"""Debug script: login then navigate to /book and extract the IFRAME structure"""
import asyncio
from playwright.async_api import async_playwright

EMAIL = "yussef.ali.it@gmail.com"
PASSWORD = "Yussefalo@12345"
BOOK_URL = "https://webook.com/ar/events/rsl-al-ettifaq-vs-al-riyadh-123554/book"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        print("1. Logging in...")
        await page.goto("https://webook.com/ar/login", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[id="email-login-button"]', force=True)
        try:
            await page.wait_for_url(lambda url: '/login' not in url, timeout=20000)
            print(f"   Logged in! URL: {page.url}")
        except:
            print(f"   URL: {page.url}")
        
        print("2. Navigating to /book...")
        await page.goto(BOOK_URL, wait_until="domcontentloaded")
        await asyncio.sleep(10)  # Wait for iframe to load
        
        import os
        os.makedirs('screenshots', exist_ok=True)
        await page.screenshot(path="screenshots/book_page_debug.png", full_page=True)
        
        # List all frames in the page
        print("\n=== ALL FRAMES IN PAGE ===")
        all_frames = page.frames
        print(f"Total frames: {len(all_frames)}")
        for i, frame in enumerate(all_frames):
            print(f"  Frame {i}: url={frame.url[:80]}, name={frame.name}")
        
        # Find seats iframe
        seats_frame = None
        for frame in all_frames:
            url = frame.url
            if 'seat' in url.lower() or 'tickets' in url.lower() or 'chart' in url.lower() or 'booking' in url.lower():
                seats_frame = frame
                print(f"\n🎯 Found likely seat frame: {url}")
                break
        
        # If not found by URL, try by iframe element ID
        if not seats_frame:
            iframe_el = await page.query_selector('#seats-iframe, iframe')
            if iframe_el:
                seats_frame = await iframe_el.content_frame()
                print(f"\n🎯 Found iframe element, frame URL: {seats_frame.url if seats_frame else 'N/A'}")
        
        if seats_frame:
            print(f"\n=== INSPECTING SEATS IFRAME ===")
            print(f"Iframe URL: {seats_frame.url}")
            
            await asyncio.sleep(3)  # Wait for iframe content
            
            try:
                result = await seats_frame.evaluate('''() => {
                    return {
                        svgCount: document.querySelectorAll('svg').length,
                        svgGroupIds: Array.from(document.querySelectorAll('svg g[id]')).map(e => ({id: e.id, class: e.className?.baseVal || ''})).slice(0, 30),
                        svgTexts: Array.from(document.querySelectorAll('svg text, svg tspan')).map(e => ({
                            text: e.textContent.trim(),
                            id: e.id,
                            parentId: e.parentElement?.id
                        })).filter(e => e.text).slice(0,30),
                        allIds: Array.from(document.querySelectorAll('[id]')).map(e => ({
                            tag: e.tagName,
                            id: e.id,
                            class: (e.className?.baseVal || e.className || '').substr(0,40)
                        })).filter(e => e.id.length < 30).slice(0,30),
                        clickableGs: Array.from(document.querySelectorAll('svg g[class*="clickable"], svg g[style*="cursor"], svg g[tabindex]')).map(e => ({
                            id: e.id, class: (e.className?.baseVal || '').substr(0,50), tabindex: e.tabIndex
                        })).slice(0,20),
                        bodyHTML: document.body?.innerHTML?.substring(0, 2000)
                    };
                }''')
                
                print(f"SVGs in iframe: {result['svgCount']}")
                
                print(f"\n--- SVG GROUP IDs in iframe ({len(result['svgGroupIds'])}) ---")
                for g in result['svgGroupIds']:
                    print(f"  <g id='{g['id']}' class='{g['class']}'>")
                
                print(f"\n--- SVG TEXTS in iframe ({len(result['svgTexts'])}) ---")
                for t in result['svgTexts']:
                    print(f"  '{t['text']}' (id={t['id']}, parentId={t['parentId']})")
                
                print(f"\n--- ALL IDs in iframe ({len(result['allIds'])}) ---")
                for el in result['allIds']:
                    print(f"  {el['tag']}#{el['id']}  class='{el['class']}'")
                
                print(f"\n--- Clickable SVG Gs ({len(result['clickableGs'])}) ---")
                for g in result['clickableGs']:
                    print(f"  id='{g['id']}' class='{g['class']}' tabindex={g['tabindex']}")
                
                print(f"\n--- IFRAME BODY (first 2000 chars) ---")
                print(result.get('bodyHTML', 'N/A'))
                
                # Save iframe HTML
                full_html = await seats_frame.evaluate('() => document.documentElement.outerHTML')
                with open('debug_iframe_content.html', 'w', encoding='utf-8') as f:
                    f.write(full_html)
                print("\nFull iframe HTML saved to: debug_iframe_content.html")
                
            except Exception as e:
                print(f"Error inspecting iframe: {e}")
                print("This might be a cross-origin iframe (different domain)")
                
                # Try to get the src of the iframe
                iframe_el = await page.query_selector('#seats-iframe, iframe')
                if iframe_el:
                    src = await iframe_el.get_attribute('src')
                    print(f"Iframe src attribute: {src}")
        else:
            print("❌ Could not find seats iframe")
        
        print("\n\nDone! The browser will close in 30 seconds.")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
