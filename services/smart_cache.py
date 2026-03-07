"""
Multi-level caching: in-memory LRU + SQLite persistent storage.
No external dependencies (no Redis).
"""
import json
import time
import logging
import asyncio
from typing import Optional, Any, Dict
from collections import OrderedDict
from config.settings import settings

logger = logging.getLogger("cache")


class LRUCache:
    """Simple in-memory LRU cache with TTL support."""

    def __init__(self, max_size: int = 100):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            entry = self._cache[key]
            if entry["expires_at"] > time.time():
                self._cache.move_to_end(key)
                self._hits += 1
                return entry["value"]
            else:
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl: int):
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
        }

    def delete(self, key: str):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return (self._hits / total * 100) if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._cache)


class SmartCache:
    """
    Multi-level cache: memory (LRU) → SQLite.
    Stores event data, selectors, prices with configurable TTLs.
    """

    def __init__(self):
        self._memory = LRUCache(max_size=200)
        self._ttl_config = {
            "event": settings.CACHE_EVENT_TTL,
            "selector": settings.CACHE_SELECTOR_TTL,
            "price": settings.CACHE_PRICE_TTL,
            "section_coords": 1800,  # 30 minutes
        }
        self._lock = asyncio.Lock()

    def _key(self, prefix: str, identifier: str) -> str:
        return f"{prefix}:{identifier}"

    async def get_event_data(self, event_id: str) -> Optional[dict]:
        """Get cached event data."""
        key = self._key("event", event_id)
        # Level 1: Memory
        result = self._memory.get(key)
        if result is not None:
            logger.debug("Cache HIT (memory): %s", key)
            return result

        # Level 2: SQLite
        result = await self._get_from_db(key)
        if result is not None:
            # Promote to memory
            self._memory.set(key, result, self._ttl_config["event"])
            logger.debug("Cache HIT (sqlite): %s", key)
            return result

        logger.debug("Cache MISS: %s", key)
        return None

    async def set_event_data(self, event_id: str, data: dict):
        """Cache event data in both memory and SQLite."""
        key = self._key("event", event_id)
        ttl = self._ttl_config["event"]
        self._memory.set(key, data, ttl)
        await self._set_in_db(key, data, ttl)

    async def get_section_coordinates(self, event_id: str) -> Optional[dict]:
        """Get cached section click coordinates."""
        key = self._key("section_coords", event_id)
        return self._memory.get(key)

    async def set_section_coordinates(self, event_id: str, coords: dict):
        """Cache section click coordinates (memory only for speed)."""
        key = self._key("section_coords", event_id)
        self._memory.set(key, coords, self._ttl_config["section_coords"])

    async def get_selectors(self, target: str) -> Optional[list]:
        """Get cached working selectors for a target."""
        key = self._key("selector", target)
        return self._memory.get(key)

    async def set_selectors(self, target: str, selectors: list):
        """Cache working selectors."""
        key = self._key("selector", target)
        self._memory.set(key, selectors, self._ttl_config["selector"])

    async def invalidate(self, event_id: str):
        """Invalidate all caches for an event."""
        for prefix in ["event", "section_coords", "price"]:
            key = self._key(prefix, event_id)
            self._memory.delete(key)
        await self._delete_from_db(self._key("event", event_id))
        logger.info("Cache invalidated for event: %s", event_id)

    @property
    def stats(self) -> dict:
        return {
            "memory_size": self._memory.size,
            "memory_hit_rate": f"{self._memory.hit_rate:.1f}%",
            "memory_hits": self._memory._hits,
            "memory_misses": self._memory._misses,
        }

    # ── SQLite persistence ──

    async def _get_from_db(self, key: str) -> Optional[dict]:
        """Read from SQLite cache table."""
        try:
            from data.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM cache_store WHERE key = ? AND expires_at > ?",
                (key, time.time()),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.debug("SQLite cache read error: %s", e)
        return None

    async def _set_in_db(self, key: str, value: dict, ttl: int):
        """Write to SQLite cache table."""
        try:
            from data.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO cache_store (key, value, expires_at)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(value, ensure_ascii=False), time.time() + ttl),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("SQLite cache write error: %s", e)

    async def _delete_from_db(self, key: str):
        """Delete from SQLite cache table."""
        try:
            from data.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cache_store WHERE key = ?", (key,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("SQLite cache delete error: %s", e)


# Global instance
smart_cache = SmartCache()
