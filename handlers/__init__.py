"""
Handlers: unified router that includes all sub-routers.
"""
from aiogram import Router

from handlers.booking import router as booking_router
from handlers.admin import router as admin_router
from handlers.support import router as support_router

# Start command (kept here for simplicity)
from aiogram import types
from aiogram.filters import Command

router = Router()


@router.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 <b>مرحباً بك في بوت حجز التذاكر الذكي!</b>\n\n"
        "🎫 أسرع وأذكى طريقة لحجز تذاكر Webook.com\n\n"
        "<b>المميزات:</b>\n"
        "⚡ حجز فوري في أقل من 15 ثانية\n"
        "🔄 إعادة المحاولة التلقائية\n"
        "🗺️ خريطة تفاعلية للمقاعد\n"
        "🔒 تسجيل دخول آمن\n\n"
        "<b>للبدء:</b> أرسل رابط الفعالية أو /book\n"
        "<b>المساعدة:</b> /help",
        parse_mode="HTML",
    )


# Include sub-routers
router.include_router(booking_router)
router.include_router(admin_router)
router.include_router(support_router)
