"""
Health monitoring and metrics tracking.
Stores metrics in memory with periodic summary logging.
"""
import time
import logging
from typing import Dict, List, Optional
from collections import deque
from data.models import HealthStatus

logger = logging.getLogger("monitor")


class BotMonitor:
    """Track bot performance, booking metrics, and health."""

    def __init__(self):
        self._start_time = time.time()
        self._booking_attempts = 0
        self._booking_successes = 0
        self._booking_failures = 0
        self._booking_durations: deque = deque(maxlen=100)
        self._errors: deque = deque(maxlen=50)
        self._last_error = ""
        self._last_error_time = 0.0

    def record_booking_attempt(self):
        self._booking_attempts += 1

    def record_booking_success(self, duration: float):
        self._booking_successes += 1
        self._booking_durations.append(duration)
        logger.info("Booking SUCCESS in %.2fs (total: %d)", duration, self._booking_successes)

    def record_booking_failure(self, error: str, duration: float = 0):
        self._booking_failures += 1
        self._last_error = error
        self._last_error_time = time.time()
        self._errors.append({
            "error": error,
            "time": time.time(),
            "duration": duration,
        })
        logger.warning("Booking FAILURE: %s (total failures: %d)", error, self._booking_failures)

    def get_health(self) -> HealthStatus:
        """Get current health snapshot."""
        total = self._booking_successes + self._booking_failures
        durations = list(self._booking_durations)

        from services.browser_pool import browser_pool
        pool_stats = browser_pool.stats

        return HealthStatus(
            uptime_seconds=time.time() - self._start_time,
            total_bookings=self._booking_attempts,
            successful_bookings=self._booking_successes,
            failed_bookings=self._booking_failures,
            success_rate=(self._booking_successes / total * 100) if total > 0 else 0.0,
            avg_booking_time=sum(durations) / len(durations) if durations else 0.0,
            active_browsers=pool_stats.get("active_sessions", 0),
            pool_size=pool_stats.get("max_instances", 0),
            last_error=self._last_error,
            last_error_time=self._last_error_time,
        )

    def format_health_message(self) -> str:
        """Format health status as Arabic Telegram message."""
        h = self.get_health()
        uptime_hours = h.uptime_seconds / 3600

        from services.smart_cache import smart_cache
        cache_stats = smart_cache.stats

        msg = (
            "📊 <b>حالة النظام</b>\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"⏱️ وقت التشغيل: {uptime_hours:.1f} ساعة\n"
            f"📈 إجمالي الحجوزات: {h.total_bookings}\n"
            f"✅ ناجحة: {h.successful_bookings}\n"
            f"❌ فاشلة: {h.failed_bookings}\n"
            f"📊 نسبة النجاح: {h.success_rate:.1f}%\n"
            f"⏱️ متوسط الوقت: {h.avg_booking_time:.1f}s\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"🌐 متصفحات نشطة: {h.active_browsers}/{h.pool_size}\n"
            f"💾 ذاكرة التخزين: {cache_stats.get('memory_size', 0)} عنصر "
            f"({cache_stats.get('memory_hit_rate', '0%')})\n"
        )

        if h.last_error:
            msg += f"\n⚠️ آخر خطأ: {h.last_error[:80]}\n"

        return msg

    def format_stats_summary(self) -> str:
        """Format compact stats for admin dashboard."""
        h = self.get_health()
        return (
            f"📊 حجوزات: {h.successful_bookings}/{h.total_bookings} "
            f"({h.success_rate:.0f}%) | "
            f"⏱️ {h.avg_booking_time:.1f}s | "
            f"🌐 {h.active_browsers} متصفح"
        )


# Global instance
bot_monitor = BotMonitor()
