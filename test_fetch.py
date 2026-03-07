import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def fetch_webook():
    url = "https://webook.com/ar/events/rsl-al-ettifaq-vs-al-riyadh-123554"
    print(f"Fetching {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'lxml')
            
            print("Title:", soup.title.string if soup.title else "No title")
            
            h1s = soup.find_all('h1')
            print("H1 tags:")
            for h in h1s:
                print(" -", h.text.strip())
                
            print("H2 tags:")
            for h in soup.find_all('h2'):
                print(" -", h.text.strip())

if __name__ == "__main__":
    asyncio.run(fetch_webook())
