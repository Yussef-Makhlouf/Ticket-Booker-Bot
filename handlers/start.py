from aiogram import Router, types
from aiogram.filters import CommandStart

router = Router()

@router.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 <b>أهلاً بك في بوت حجز التذاكر!</b>\n\n"
        "أنا هنا لمساعدتك في حجز التذاكر من منصة Webook بطريقة سريعة وشبه آلية.\n"
        "استخدم الأمر /book لبدء عملية الحجز.",
        parse_mode="HTML"
    )
