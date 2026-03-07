"""
User guidance, FAQ, and help commands.
"""
from aiogram import Router, types
from aiogram.filters import Command

router = Router()


@router.message(Command("help"))
async def help_cmd(message: types.Message):
    """Show help and FAQ."""
    await message.answer(
        "📖 <b>دليل استخدام بوت الحجز</b>\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "<b>الأوامر المتاحة:</b>\n"
        "  /start — بدء المحادثة\n"
        "  /book — بدء حجز جديد\n"
        "  /help — عرض المساعدة\n"
        "  /cancel — إلغاء العملية الحالية\n\n"
        "<b>كيفية الحجز:</b>\n"
        "1️⃣ أرسل رابط الفعالية من Webook.com\n"
        "2️⃣ سيستخرج البوت بيانات الفعالية تلقائياً\n"
        "3️⃣ سجّل دخولك (بالبريد أو الكوكيز)\n"
        "4️⃣ اختر عدد التذاكر والقسم\n"
        "5️⃣ سيقوم البوت بالحجز وإرسال رابط الدفع\n\n"
        "<b>❓ الأسئلة الشائعة:</b>\n\n"
        "<b>س: هل حفظ كلمة المرور آمن؟</b>\n"
        "ج: لا نحفظ كلمة المرور. تُستخدم مرة واحدة ثم تُمسح فوراً.\n\n"
        "<b>س: ماذا لو فشل الحجز؟</b>\n"
        "ج: البوت يحاول تلقائياً حتى 3 مرات. إذا استمر الفشل، حاول لاحقاً.\n\n"
        "<b>س: هل البوت شريك رسمي لـ Webook؟</b>\n"
        "ج: لا، البوت أداة مساعدة غير رسمية تساعدك في تسريع عملية الحجز.\n\n"
        "<b>س: كم يستغرق الحجز؟</b>\n"
        "ج: عادةً أقل من 15 ثانية من إرسال الرابط حتى إتمام الحجز.\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "📩 للدعم الفني، تواصل مع المشرف.",
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
async def cancel_cmd(message: types.Message, state=None):
    """Cancel the current operation."""
    from aiogram.fsm.context import FSMContext

    if state and isinstance(state, FSMContext):
        current = await state.get_state()
        if current:
            await state.clear()
            # Release browser if active
            from services.browser_pool import browser_pool
            await browser_pool.release(message.from_user.id)

            await message.answer(
                "✅ تم إلغاء العملية الحالية.\n"
                "أرسل /book لبدء حجز جديد.",
            )
            return

    await message.answer("ℹ️ لا توجد عملية جارية حالياً.")
