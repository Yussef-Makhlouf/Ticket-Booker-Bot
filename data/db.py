"""
SQLite database layer with connection management, table initialization,
and CRUD operations for bookings, sessions, and cache.
"""
import os
import json
import sqlite3
import time
import logging
from typing import Optional
from config.settings import settings

logger = logging.getLogger("bot")

_DB_PATH = os.path.join(settings.BASE_DIR, settings.DB_PATH)


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_connection()
    cursor = conn.cursor()

    # Bookings history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_name TEXT,
            event_id TEXT,
            team TEXT,
            tickets INTEGER DEFAULT 1,
            seats TEXT,
            status TEXT DEFAULT 'pending',
            checkout_url TEXT,
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # User sessions (cookies)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            cookies TEXT NOT NULL,
            is_valid BOOLEAN DEFAULT 1,
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # Cache store
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_store (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    """)

    # Events cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events_cache (
            event_url TEXT PRIMARY KEY,
            event_name TEXT,
            event_data TEXT,
            scraped_at REAL DEFAULT (strftime('%s','now'))
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", _DB_PATH)


# ── Booking Records ──

def add_booking_record(
    user_id: int,
    event_name: str,
    event_id: str = "",
    team: str = None,
    tickets: int = 1,
    seats: str = "",
    status: str = "pending",
    checkout_url: str = "",
):
    """Record a booking attempt."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO bookings (user_id, event_name, event_id, team, tickets, seats, status, checkout_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, event_name, event_id, team, tickets, seats, status, checkout_url),
    )
    conn.commit()
    conn.close()


def get_user_bookings(user_id: int, limit: int = 10) -> list:
    """Get recent bookings for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM bookings WHERE user_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── User Sessions ──

def save_user_session(user_id: int, cookies: str):
    """Save or update user session cookies."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT OR REPLACE INTO user_sessions (user_id, cookies, is_valid, updated_at)
           VALUES (?, ?, 1, strftime('%s','now'))""",
        (user_id, cookies),
    )
    conn.commit()
    conn.close()


def get_user_session(user_id: int) -> Optional[str]:
    """Get valid session cookies for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT cookies FROM user_sessions
           WHERE user_id = ? AND is_valid = 1""",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return row["cookies"] if row else None


def invalidate_session(user_id: int):
    """Mark a user session as invalid."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE user_sessions SET is_valid = 0, updated_at = strftime('%s','now') WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ── Cache Operations ──

def cleanup_expired_cache():
    """Remove expired cache entries."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_store WHERE expires_at < ?", (time.time(),))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.debug("Cleaned %d expired cache entries", deleted)
    except Exception as e:
        logger.warning("Cache cleanup error: %s", e)
