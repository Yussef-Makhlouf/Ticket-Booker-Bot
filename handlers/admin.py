from aiogram import Router, types
from aiogram.filters import Command
from config import ADMIN_ID

router = Router()

@router.message(Command("setup"))
async def setup_cmd(message: types.Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return await message.answer("❌ عذراً، هذا الأمر للمشرفين فقط.")
        
    await message.answer(
        "⚙️ <b>إعدادات البوت</b>\n\n"
        "يمكنك من هنا إرسال رابط الفعالية لتجهيزها مسبقاً (هذه الميزة قيد التطوير).",
        parse_mode="HTML"
    )
