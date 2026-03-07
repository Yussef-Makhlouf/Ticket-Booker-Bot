"""
Anti-detection and stealth module for browser automation.
Applies various techniques to avoid bot detection.
"""
import random
import asyncio
import logging
from playwright.async_api import Page, BrowserContext

logger = logging.getLogger("browser")


async def apply_full_stealth(page: Page):
    """
    Apply comprehensive stealth patches to a page.
    Call this after page creation or navigation.
    """
    await page.add_init_script("""
    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });

    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ar-SA', 'ar', 'en-US', 'en']
    });

    // Fake plugins (Chrome-like)
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                {name: 'Native Client', filename: 'internal-nacl-plugin'}
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    // Fake chrome runtime
    window.chrome = {
        runtime: {},
        loadTimes: function() { return {}; },
        csi: function() { return {}; },
        app: {isInstalled: false}
    };

    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
    );

    // Prevent canvas fingerprinting detection
    const toBlob = HTMLCanvasElement.prototype.toBlob;
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    const getImageData = CanvasRenderingContext2D.prototype.getImageData;

    // Add subtle noise to canvas reads
    const addNoise = (data) => {
        for (let i = 0; i < data.length; i += 4) {
            data[i] = data[i] + (Math.random() * 2 - 1);  // R
        }
        return data;
    };

    // Hide automation indicators
    delete navigator.__proto__.webdriver;

    // Override connection rtt to seem more natural
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', {
            get: () => Math.floor(Math.random() * 100) + 50
        });
    }
    """)


async def human_delay(min_ms: int = 200, max_ms: int = 800):
    """Add a random human-like delay."""
    delay = random.randint(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


async def human_type(page: Page, selector: str, text: str, delay_range: tuple = (50, 150)):
    """Type text with human-like delays between keystrokes."""
    element = await page.wait_for_selector(selector, timeout=10000)
    if element:
        await element.click()
        for char in text:
            await page.keyboard.type(char, delay=random.randint(*delay_range))
        await human_delay(100, 300)


async def human_click(page: Page, selector: str):
    """Click with a small random offset and human-like timing."""
    element = await page.wait_for_selector(selector, timeout=10000)
    if element:
        box = await element.bounding_box()
        if box:
            # Click slightly off-center (more human-like)
            x_offset = random.uniform(-3, 3)
            y_offset = random.uniform(-3, 3)
            await page.mouse.click(
                box["x"] + box["width"] / 2 + x_offset,
                box["y"] + box["height"] / 2 + y_offset
            )
        else:
            await element.click()
        await human_delay(200, 500)


async def random_mouse_movement(page: Page, count: int = 3):
    """Simulate random mouse movements to appear more human."""
    for _ in range(count):
        x = random.randint(100, 1800)
        y = random.randint(100, 900)
        await page.mouse.move(x, y)
        await human_delay(50, 200)


def get_random_viewport() -> dict:
    """Get a randomized but realistic viewport size."""
    viewports = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1680, "height": 1050},
    ]
    return random.choice(viewports)
