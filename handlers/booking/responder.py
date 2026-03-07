"""
User-facing message formatting for Telegram.
Rich HTML messages with Arabic support.
"""
from typing import Optional, List, Dict, Any
from data.models import EventData


class Responder:
    """Format rich Arabic messages for the booking flow."""

    @staticmethod
    def format_event_summary(event: EventData) -> str:
        """Format event data as Telegram message."""
        name = event.name or "الفعالية غير معروفة"
        date = event.date or "غير محدد"
        venue = event.venue or "غير محدد"
        price_min = event.price_range.get("min", 0)
        price_max = event.price_range.get("max", 0)

        if price_min > 0 and price_max > 0 and price_min != price_max:
            price_text = f"الأسعار: {price_min} – {price_max} ريال"
        elif price_min > 0:
            price_text = f"السعر يبدأ من {price_min} ريال"
        else:
            price_text = "الأسعار غير متوفرة"

        return (
            f"🎟️ <b>تفاصيل الفعالية</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{name}</b>\n"
            f"📅 {date}\n"
            f"🏟️ {venue}\n"
            f"💰 {price_text}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )

    @staticmethod
    def format_booking_receipt(
        event_name: str,
        tickets: int,
        section: str,
        team: Optional[str] = None,
        duration: float = 0,
    ) -> str:
        """Format the final booking receipt."""
        receipt = (
            "🎉 <b>تم الحجز بنجاح!</b>\n\n"
            "📋 <b>ملخص الطلب:</b>\n"
            f"• <b>الفعالية:</b> {event_name}\n"
        )
        if team:
            receipt += f"• <b>الفريق:</b> {team}\n"
        receipt += (
            f"• <b>القسم:</b> {section}\n"
            f"• <b>عدد التذاكر:</b> {tickets}\n"
        )
        if duration > 0:
            receipt += f"• <b>الوقت:</b> {duration:.1f} ثانية\n"
        receipt += "\n⚠️ <b>يجب إكمال الدفع الآن لتأكيد الحجز</b>"
        return receipt

    @staticmethod
    def format_booking_progress(
        steps: List[dict],
        total_time: float = 0,
    ) -> str:
        """Format step-by-step progress message."""
        lines = ["⚡ <b>مراحل الحجز:</b>\n"]
        for step in steps:
            icon = "✅" if step.get("success", True) else "❌"
            lines.append(f"  {icon} {step['name']}: {step['duration']:.1f}s")
        if total_time > 0:
            lines.append(f"\n⏱️ <b>الوقت الإجمالي: {total_time:.1f}s</b>")
        return "\n".join(lines)

    @staticmethod
    def format_error(message: str, suggestion: str = "") -> str:
        """Format error message."""
        text = f"❌ <b>{message}</b>"
        if suggestion:
            text += f"\n\n💡 {suggestion}"
        return text
