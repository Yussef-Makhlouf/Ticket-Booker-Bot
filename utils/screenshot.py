import os
import time
import asyncio

async def cleanup_screenshots(directory: str = "screenshots", max_age_hours: int = 1):
    """Deletes screenshots older than max_age_hours"""
    if not os.path.exists(directory):
        return
        
    current_time = time.time()
    for filename in os.listdir(directory):
        if not filename.endswith(".png"):
            continue
            
        file_path = os.path.join(directory, filename)
        file_age_hours = (current_time - os.path.getmtime(file_path)) / 3600
        
        if file_age_hours > max_age_hours:
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting old screenshot {file_path}: {e}")

async def start_screenshot_cleanup_task(interval_minutes: int = 60):
    """Background task to periodically clean up screenshots"""
    while True:
        await cleanup_screenshots()
        await asyncio.sleep(interval_minutes * 60)
