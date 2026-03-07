"""
Bot initialization and dispatcher setup.
"""
from aiogram import Bot, Dispatcher
from config.settings import settings


def create_bot() -> Bot:
    """Create and return the Telegram bot instance."""
    return Bot(token=settings.BOT_TOKEN)


def create_dispatcher() -> Dispatcher:
    """Create and return the dispatcher with all routers."""
    dp = Dispatcher()

    # Import and include all routers
    from handlers import router as main_router
    dp.include_router(main_router)

    return dp
