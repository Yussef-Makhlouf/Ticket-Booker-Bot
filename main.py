"""
Webook Pro Bot — Enterprise Ticket Booking System
Main entry point with graceful startup and shutdown.
"""
import asyncio
import os
import sys
import logging

# Ensure project root is on import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from config.logging_config import setup_logging
from data.db import init_db, cleanup_expired_cache
from services.browser_pool import browser_pool
from core.bot import create_bot, create_dispatcher

logger = logging.getLogger("bot")


async def on_startup():
    """Startup tasks."""
    logger.info("═" * 50)
    logger.info("  🎫 Webook Pro Bot Starting...")
    logger.info("═" * 50)

    # Create required directories
    for d in ["screenshots", "logs", "data"]:
        os.makedirs(d, exist_ok=True)

    # Initialize database
    init_db()

    # Initialize browser pool
    await browser_pool.initialize()

    logger.info("Bot startup complete!")


async def on_shutdown():
    """Graceful shutdown."""
    logger.info("Shutting down...")
    await browser_pool.close_all()
    cleanup_expired_cache()
    logger.info("Shutdown complete.")


async def background_cleanup():
    """Periodic cleanup task."""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        try:
            cleanup_expired_cache()
            # Clean old screenshots
            screenshots_dir = "screenshots"
            if os.path.exists(screenshots_dir):
                now = asyncio.get_event_loop().time()
                for f in os.listdir(screenshots_dir):
                    path = os.path.join(screenshots_dir, f)
                    if os.path.isfile(path):
                        age = now - os.path.getmtime(path)
                        if age > 3600:  # 1 hour
                            os.remove(path)
        except Exception as e:
            logger.warning("Background cleanup error: %s", e)


async def main():
    """Main entry point."""
    # Setup logging first
    setup_logging()

    # Create bot and dispatcher
    bot = create_bot()
    dp = create_dispatcher()

    # Register lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start background tasks
    asyncio.create_task(background_cleanup())

    # Start polling
    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
