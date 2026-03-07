"""
Admin dashboard: metrics, health checks, runtime config.
Only accessible by the configured ADMIN_ID.
"""
import logging
from aiogram import Router, types
from aiogram.filters import Command
from config.settings import settings
from core.monitor import bot_monitor
from services.browser_pool import browser_pool
from services.smart_cache import smart_cache

logger = logging.getLogger("bot")

router = Router()


def _is_admin(user_id: int) -> bool:
    return settings.ADMIN_ID is not None and user_id == settings.ADMIN_ID


@router.message(Command("stats"))
async def stats_cmd(message: types.Message):
    """Show booking statistics."""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ عذراً، هذا الأمر للمشرفين فقط.")
        return

    await message.answer(
        bot_monitor.format_health_message(),
        parse_mode="HTML",
    )


@router.message(Command("health"))
async def health_cmd(message: types.Message):
    """Show detailed system health."""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ هذا الأمر للمشرفين فقط.")
        return

    health = bot_monitor.get_health()
    pool_stats = browser_pool.stats
    cache_stats = smart_cache.stats

    msg = (
        "🏥 <b>تقرير صحة النظام</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"⏱️ وقت التشغيل: {health.uptime_seconds / 3600:.1f}h\n"
        f"📊 نسبة النجاح: {health.success_rate:.1f}%\n"
        f"⏱️ متوسط الحجز: {health.avg_booking_time:.1f}s\n"
        "━━━━━━━━━━━━━━━━━\n"
        "<b>🌐 المتصفحات:</b>\n"
        f"  • نشطة: {pool_stats.get('active_sessions', 0)}\n"
        f"  • متاحة: {pool_stats.get('pool_available', 0)}\n"
        f"  • الحد الأقصى: {pool_stats.get('max_instances', 0)}\n"
        f"  • إجمالي تم إنشاؤها: {pool_stats.get('total_created', 0)}\n"
        "━━━━━━━━━━━━━━━━━\n"
        "<b>💾 ذاكرة التخزين:</b>\n"
        f"  • العناصر: {cache_stats.get('memory_size', 0)}\n"
        f"  • نسبة الإصابة: {cache_stats.get('memory_hit_rate', '0%')}\n"
        f"  • إصابات: {cache_stats.get('memory_hits', 0)}\n"
        f"  • إخفاقات: {cache_stats.get('memory_misses', 0)}\n"
    )

    if health.last_error:
        msg += f"\n⚠️ <b>آخر خطأ:</b> {health.last_error[:100]}\n"

    await message.answer(msg, parse_mode="HTML")


@router.message(Command("config"))
async def config_cmd(message: types.Message):
    """Show runtime configuration."""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ هذا الأمر للمشرفين فقط.")
        return

    msg = (
        "⚙️ <b>إعدادات التشغيل</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🌐 متصفحات: max={settings.MAX_BROWSER_INSTANCES}, warmup={settings.BROWSER_WARMUP_COUNT}\n"
        f"🔄 محاولات: max={settings.MAX_RETRIES}, timeout={settings.BOOKING_TIMEOUT}s\n"
        f"💾 ذاكرة: event_ttl={settings.CACHE_EVENT_TTL}s, price_ttl={settings.CACHE_PRICE_TTL}s\n"
        f"📐 مسح المقاعد: {settings.SEAT_SCAN_GRID_X}×{settings.SEAT_SCAN_GRID_Y}\n"
        f"⏱️ حد الطلبات: {settings.MIN_REQUEST_INTERVAL}s\n"
        f"🎫 أقصى تذاكر: {settings.MAX_TICKETS_PER_BOOKING}\n"
        f"📝 مستوى السجل: {settings.LOG_LEVEL}\n"
    )

    await message.answer(msg, parse_mode="HTML")
