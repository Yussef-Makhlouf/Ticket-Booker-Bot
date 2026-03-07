"""
Pydantic-based settings management for the Webook Pro Bot.
All configuration is loaded from environment variables with sensible defaults.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Telegram ──
    BOT_TOKEN: str = Field(..., description="Telegram Bot API token")
    ADMIN_ID: Optional[int] = Field(None, description="Admin Telegram user ID")

    # ── Browser Pool ──
    MAX_BROWSER_INSTANCES: int = Field(5, description="Max browsers in pool")
    BROWSER_WARMUP_COUNT: int = Field(2, description="Pre-warmed browser count")
    BROWSER_HEADLESS: bool = Field(True, description="Run browsers headless")
    BROWSER_ACQUIRE_TIMEOUT: float = Field(10.0, description="Seconds to wait for browser")
    PAGE_LOAD_TIMEOUT: int = Field(60000, description="Page load timeout in ms")

    # ── Booking Engine ──
    MAX_RETRIES: int = Field(3, description="Max retry attempts per booking")
    BOOKING_TIMEOUT: int = Field(60, description="Total booking timeout in seconds")
    RETRY_BASE_DELAY: float = Field(1.0, description="Base delay for exponential backoff")
    MAX_TICKETS_PER_BOOKING: int = Field(10, description="Max tickets per booking")

    # ── Cache ──
    CACHE_EVENT_TTL: int = Field(3600, description="Event data cache TTL in seconds")
    CACHE_SELECTOR_TTL: int = Field(7200, description="Selector cache TTL in seconds")
    CACHE_PRICE_TTL: int = Field(300, description="Price data cache TTL in seconds")

    # ── Seat Mapping ──
    SEAT_SCAN_GRID_X: int = Field(22, description="Horizontal grid steps for canvas scan")
    SEAT_SCAN_GRID_Y: int = Field(18, description="Vertical grid steps for canvas scan")
    SEAT_MAP_WAIT_TIMEOUT: int = Field(45000, description="Seat map load timeout ms")

    # ── Rate Limiting ──
    MIN_REQUEST_INTERVAL: float = Field(0.5, description="Min seconds between requests")
    MAX_CONCURRENT_BOOKINGS: int = Field(10, description="Max simultaneous bookings")

    # ── Paths ──
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent)
    SCREENSHOTS_DIR: str = Field("screenshots", description="Screenshots directory")
    DATA_DIR: str = Field("data", description="Data directory")
    DB_PATH: str = Field("data/webook_pro.db", description="SQLite database path")

    # ── Logging ──
    LOG_LEVEL: str = Field("INFO", description="Logging level")
    LOG_FILE: str = Field("logs/bot.log", description="Log file path")
    LOG_FORMAT: str = Field(
        "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        description="Log format string"
    )

    # ── Security ──
    ENCRYPTION_KEY: Optional[str] = Field(None, description="Fernet encryption key for cookies")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


# Singleton settings instance
settings = Settings()
