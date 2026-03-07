from typing import Dict, Any

def format_event_summary(event_data: Dict[str, Any]) -> str:
    """Formats event data into a beautiful Arabic Telegram message."""
    
    name = event_data.get('name', 'الفعالية غير معروفة')
    date = event_data.get('date', 'غير محدد')
    venue = event_data.get('venue', 'غير محدد')
    price_range = event_data.get('price_range', {'min': 0, 'max': 0})
    
    # Format prices
    min_price = price_range.get('min', 0)
    max_price = price_range.get('max', 0)
    
    if min_price > 0 and max_price > 0 and min_price != max_price:
        price_text = f"الأسعار تبدأ من {min_price} إلى {max_price} ريال"
    elif min_price > 0:
        price_text = f"الأسعار تبدأ من {min_price} ريال"
    else:
        price_text = "الأسعار غير متوفرة أو مجانية"
        
    summary = f"🎟️ <b>تفاصيل الفعالية:</b>\n"
    summary += f"━━━━━━━━━━━━━━━━━\n"
    summary += f"🏆 <b>الاسم:</b> {name}\n"
    summary += f"📅 <b>التاريخ:</b> {date}\n"
    summary += f"🏟️ <b>المكان:</b> {venue}\n"
    summary += f"💰 <b>{price_text}</b>\n"
    summary += f"━━━━━━━━━━━━━━━━━\n"
    
    return summary

def format_booking_receipt(event_name: str, tickets: int, seats: list[int], team: str = None) -> str:
    """Formats the final booking summary/receipt."""
    
    receipt = f"✅ <b>تم الحجز المبدئي بنجاح!</b>\n\n"
    receipt += f"📋 <b>ملخص الطلب:</b>\n"
    receipt += f"• <b>الفعالية:</b> {event_name}\n"
    if team:
        receipt += f"• <b>الفريق المختار:</b> {team}\n"
    receipt += f"• <b>عدد التذاكر:</b> {tickets}\n"
    receipt += f"• <b>أرقام المقاعد:</b> {', '.join(map(str, seats))}\n\n"
    receipt += f"⚠️ <b>يجب عليك الدفع الآن لتأكيد الحجز.</b>"
    
    return receipt
