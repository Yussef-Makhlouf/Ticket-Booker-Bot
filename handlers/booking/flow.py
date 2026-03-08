"""
Main booking state machine / FSM flow.
Rebuilt to use BookingEngine, BrowserPool, and all new services.
"""
import os
import asyncio
import logging
from typing import Dict
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from core.engine import booking_engine
from core.monitor import bot_monitor
from services.browser_pool import browser_pool
from services.webook_automation import WebookAutomation
from services.login_manager import login_manager
from analyzers.page_analyzer import PageAnalyzer
from data.models import BookingRequest
from data.db import add_booking_record
from handlers.booking.responder import Responder
from handlers.booking.validator import Validator
from utils.link_parser import extract_event_id
from utils.speed import Timer

logger = logging.getLogger("bot")

router = Router()


class BookingState(StatesGroup):
    waiting_for_event_url = State()
    waiting_for_login = State()
    waiting_for_cookie = State()
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_tickets = State()
    waiting_for_team = State()
    waiting_for_section = State()
    waiting_for_price = State()
    processing = State()


# ═══════════════════════════════════════════════
# BOOKING ENTRY POINT
# ═══════════════════════════════════════════════

@router.message(F.text == "/book")
async def start_booking(message: types.Message, state: FSMContext):
    await message.answer(
        "🎫 <b>مرحباً بك في نظام الحجز الذكي!</b>\n\n"
        "أرسل رابط الفعالية من Webook.com\n"
        "مثال:\n<code>https://webook.com/ar/events/...</code>",
        parse_mode="HTML",
    )
    await state.set_state(BookingState.waiting_for_event_url)


@router.message(F.text.startswith("https://webook.com"))
async def process_event_url(message: types.Message, state: FSMContext):
    """Process event URL with parallel data extraction."""
    event_url = message.text.strip()

    if not Validator.validate_url(event_url):
        await message.answer("❌ الرابط غير صحيح. يرجى إرسال رابط صالح من Webook.com")
        return

    processing_msg = await message.answer(
        "⚡ <b>جاري التحليل الذكي...</b>\n\n"
        "• استخراج بيانات الفعالية\n"
        "• التحقق من تسجيل الدخول\n"
        "• تحليل المقاعد\n\n"
        "⏳ الرجاء الانتظار...",
        parse_mode="HTML",
    )

    try:
        # Use BookingEngine for parallel preparation
        with Timer("booking_prep") as t:
            prep = await booking_engine.prepare_booking(event_url, message.from_user.id)

        event_data = prep.event_data
        event_id = extract_event_id(event_url) or ""

        # Save to FSM state
        await state.update_data(
            event_url=event_url,
            event_id=event_id,
            event_name=event_data.name,
            event_type=event_data.event_type,
            teams=event_data.teams,
            date=event_data.date,
            venue=event_data.venue,
            price_range=event_data.price_range,
            image_url=event_data.image_url,
            is_logged_in=prep.is_logged_in,
        )

        try:
            await processing_msg.delete()
        except Exception:
            pass

        # Not logged in → prompt login
        if not prep.is_logged_in:
            await _handle_login_required(message, event_data, state)
            return

        # Logged in → show event summary and ask for ticket count
        summary = Responder.format_event_summary(event_data)
        summary += "\n🎫 <b>كم تذكرة تريد؟</b> (1-10)"

        if event_data.image_url and event_data.image_url.startswith("http"):
            try:
                await message.answer_photo(
                    photo=event_data.image_url,
                    caption=summary,
                    parse_mode="HTML",
                )
            except Exception:
                await message.answer(summary, parse_mode="HTML")
        else:
            await message.answer(summary, parse_mode="HTML")

        # Show prep timing
        await message.answer(
            f"⚡ <b>تم التحليل في {t.elapsed:.1f} ثانية</b>",
            parse_mode="HTML",
        )

        await state.set_state(BookingState.waiting_for_tickets)

    except Exception as e:
        logger.error("Event URL processing error: %s", e)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ حدث خطأ: {str(e)}\n\nتأكد من الرابط وحاول مرة أخرى."
        )


# ═══════════════════════════════════════════════
# LOGIN HANDLING
# ═══════════════════════════════════════════════

async def _handle_login_required(message: types.Message, event_data, state: FSMContext):
    """Present login options."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 تسجيل الدخول بالبريد", callback_data="login_via_bot")],
        [InlineKeyboardButton(text="🌐 تسجيل من المتصفح",
                              url=event_data.url or "https://webook.com/ar/login")],
        [InlineKeyboardButton(text="✅ لقد سجلت دخولي (متابعة)", callback_data="continue_login")],
    ])

    await message.answer(
        f"⚠️ <b>يجب تسجيل الدخول أولاً</b>\n\n"
        f"📋 <b>الفعالية:</b> {event_data.name or 'غير معروفة'}\n"
        f"📅 {event_data.date or 'غير محدد'}\n"
        f"🏟️ {event_data.venue or 'غير محدد'}\n\n"
        f"اختر طريقة تسجيل الدخول:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await state.set_state(BookingState.waiting_for_login)


@router.callback_query(F.data == "login_via_bot", BookingState.waiting_for_login)
async def login_via_bot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📧 <b>أرسل بريدك الإلكتروني المسجل في Webook:</b>",
        parse_mode="HTML",
    )
    await state.set_state(BookingState.waiting_for_email)
    await callback.answer()


@router.message(BookingState.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if not Validator.validate_email(email):
        await message.answer("❌ البريد الإلكتروني غير صحيح. حاول مرة أخرى.")
        return

    await state.update_data(email=email)
    await message.answer(
        "🔒 <b>أرسل كلمة المرور:</b>\n"
        "(سيتم حذف الرسالة فوراً ولن نحفظ كلمة المرور)",
        parse_mode="HTML",
    )
    await state.set_state(BookingState.waiting_for_password)


@router.message(BookingState.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    email = data.get("email", "")

    processing_msg = await message.answer(
        "⏳ <b>جاري تسجيل الدخول...</b>", parse_mode="HTML"
    )

    try:
        ctx, page = await browser_pool.acquire(message.from_user.id)
        success = await login_manager.login_with_credentials(page, email, password)

        try:
            await processing_msg.delete()
        except Exception:
            pass

        if success:
            # Save session cookies
            await login_manager.save_session(ctx, message.from_user.id)

            await message.answer(
                f"✅ <b>تم تسجيل الدخول بنجاح!</b>\n\n"
                f"🏆 <b>{data.get('event_name', 'الفعالية')}</b>\n"
                f"📅 {data.get('date', 'غير محدد')}\n\n"
                f"🎫 <b>كم تذكرة تريد؟</b> (1-10)",
                parse_mode="HTML",
            )
            await state.set_state(BookingState.waiting_for_tickets)
        else:
            screenshot_path = "screenshots/login_failure.png"
            if os.path.exists(screenshot_path):
                try:
                    photo = FSInputFile(screenshot_path)
                    await message.answer_photo(
                        photo=photo,
                        caption="📸 لقطة شاشة لسبب فشل تسجيل الدخول",
                    )
                except Exception:
                    pass

            await message.answer(
                "❌ <b>فشل تسجيل الدخول</b>\n"
                "تأكد من البريد وكلمة المرور وأعد المحاولة عبر إرسال الرابط من جديد.",
                parse_mode="HTML",
            )
            await state.clear()

    except Exception as e:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(f"❌ خطأ: {e}")
        await state.clear()


@router.callback_query(F.data == "continue_login", BookingState.waiting_for_login)
async def continue_after_login(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "<b>أرسل ملفات تعريف الارتباط (Cookies):</b>\n\n"
        "1. افتح Webook وسجل دخولك\n"
        "2. اضغط F12 ← Network ← أعد التحميل\n"
        "3. انسخ قيمة <code>cookie:</code> وأرسلها هنا\n\n"
        "<i>أو استخدم تسجيل الدخول بالبريد</i>",
        parse_mode="HTML",
    )
    await state.set_state(BookingState.waiting_for_cookie)
    await callback.answer()


@router.message(BookingState.waiting_for_cookie)
async def process_cookie(message: types.Message, state: FSMContext):
    cookie_string = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass

    processing_msg = await message.answer(
        "⏳ <b>جاري التحقق من الجلسة...</b>", parse_mode="HTML"
    )

    try:
        ctx, page = await browser_pool.acquire(message.from_user.id)
        success = await login_manager.inject_cookies(ctx, page, cookie_string)

        try:
            await processing_msg.delete()
        except Exception:
            pass

        if success:
            data = await state.get_data()
            await message.answer(
                f"✅ <b>تم ربط الجلسة بنجاح!</b>\n\n"
                f"🏆 <b>{data.get('event_name', 'الفعالية')}</b>\n\n"
                f"🎫 <b>كم تذكرة تريد؟</b> (1-10)",
                parse_mode="HTML",
            )
            await state.set_state(BookingState.waiting_for_tickets)
        else:
            await message.answer(
                "❌ <b>فشل ربط الجلسة</b>\n"
                "ملفات تعريف الارتباط غير صحيحة أو منتهية.",
                parse_mode="HTML",
            )

    except Exception as e:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(f"❌ خطأ: {e}")


# ═══════════════════════════════════════════════
# TICKET COUNT & TEAM SELECTION
# ═══════════════════════════════════════════════

@router.message(BookingState.waiting_for_tickets)
async def process_tickets(message: types.Message, state: FSMContext):
    tickets = Validator.validate_ticket_count(message.text)
    if tickets is None:
        await message.answer("❌ أرسل رقماً بين 1 و 10")
        return

    await state.update_data(tickets=tickets)
    data = await state.get_data()

    # If match with teams → ask for team selection
    if data.get("event_type") == "match" and len(data.get("teams", [])) >= 2:
        teams = data["teams"]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🟡 {teams[0]}", callback_data="team_0")],
            [InlineKeyboardButton(text=f"🟢 {teams[1]}", callback_data="team_1")],
        ])
        await message.answer(
            "⚽ <b>اختر الفريق:</b>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await state.set_state(BookingState.waiting_for_team)
    else:
        await _proceed_to_map(message, state)


@router.callback_query(F.data.startswith("team_"), BookingState.waiting_for_team)
async def process_team(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    teams = data.get("teams", [])
    team = teams[0] if callback.data == "team_0" else teams[1] if len(teams) > 1 else ""

    await state.update_data(team=team)
    await callback.message.answer(f"✅ تم اختيار: {team}")
    await callback.answer()
    await _proceed_to_map(callback.message, state)


# ═══════════════════════════════════════════════
# SEAT MAP & SECTION SELECTION
# ═══════════════════════════════════════════════

async def _proceed_to_map(message: types.Message, state: FSMContext):
    """Navigate to booking page, load seat map, and present to user."""
    data = await state.get_data()

    processing_msg = await message.answer(
        "⏳ <b>جاري فتح خريطة الملعب...</b>\n"
        "قد يستغرق بضع ثوانٍ...",
        parse_mode="HTML",
    )

    try:
        ctx, page = await browser_pool.acquire(message.chat.id)
        automation = WebookAutomation(page)

        # Navigate to /book URL
        event_url = data.get("event_url", "")
        booking_url = event_url.split("?")[0]
        if not booking_url.endswith("/book"):
            booking_url = booking_url.rstrip("/") + "/book"

        await automation.navigate_to_event(booking_url)
        await automation.wait_for_seat_map()

        # Take screenshot
        screenshot_path = await automation.take_seat_map_screenshot(message.chat.id)

        # Get all sections with availability status
        sections_info = await automation.get_all_sections_with_availability()
        
        # Also get simple list for backward compatibility
        sections = await automation.get_available_sections()

        try:
            await processing_msg.delete()
        except Exception:
            pass

        # Send map screenshot
        photo = FSInputFile(screenshot_path)
        await message.answer_photo(
            photo=photo,
            caption=(
                "📸 <b>خريطة الملعب</b>\n\n"
                "اختر القسم الذي تريد.\n"
                "أرسل <b>اسم القسم</b> كما يظهر في الخريطة\n\n"
                "<b>أمثلة:</b> D9, D10, A1, VIP"
            ),
            parse_mode="HTML",
        )

        # Show discovered sections as buttons
        if sections and 0 < len(sections) <= 20:
            valid = [s for s in sections if len(s) <= 8 and s.replace("-", "").replace("_", "").isalnum()][:12]
            if valid:
                buttons = []
                for i in range(0, len(valid), 3):
                    row = [
                        InlineKeyboardButton(text=s, callback_data=f"section_{s}")
                        for s in valid[i:i + 3]
                    ]
                    buttons.append(row)

                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                await message.answer("أو اختر من القائمة:", reply_markup=keyboard)

        # Store sections info for later use
        if sections_info:
            await state.update_data(sections_info=sections_info)
            # Show available sections
            avail = [s for s,i in sections_info.items() if i.get("status")=="available"]
            if avail:
                await message.answer(f"✅ <b>الأقسام المتاحة:</b> {', '.join(avail[:8])}", parse_mode="HTML")

        await state.set_state(BookingState.waiting_for_section)

    except Exception as e:
        logger.error("Seat map error: %s", e)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ <b>خطأ في فتح خريطة الملعب</b>\n\n{str(e)}\n\n"
            "تأكد من تسجيل الدخول وأن الفعالية متاحة.",
            parse_mode="HTML",
        )
        await state.clear()


@router.message(BookingState.waiting_for_section)
async def process_section_text(message: types.Message, state: FSMContext):
    section = message.text.strip().upper()
    if not Validator.validate_section(section):
        await message.answer("❌ اسم القسم غير صحيح. أرسل مثل: D9 أو A1 أو VIP")
        return
    await _do_booking(message, state, section)


@router.callback_query(F.data.startswith("section_"), BookingState.waiting_for_section)
async def process_section_button(callback: types.CallbackQuery, state: FSMContext):
    section = callback.data.replace("section_", "")
    await callback.answer()
    await _do_booking(callback.message, state, section)


# ═══════════════════════════════════════════════
# BOOKING EXECUTION
# ═══════════════════════════════════════════════

async def _do_booking(message: types.Message, state: FSMContext, section: str):
    """Execute the actual booking via BookingEngine."""
    data = await state.get_data()
    tickets = data.get("tickets", 1)
    event_url = data.get("event_url", "")
    event_id = data.get("event_id", "")

    bot_monitor.record_booking_attempt()

    processing_msg = await message.answer(
        f"⚡ <b>جاري حجز {tickets} تذكرة في القسم {section}...</b>\n\n"
        "• فتح صفحة الحجز\n"
        "• اختيار القسم\n"
        "• إضافة التذاكر\n"
        "• الانتقال للدفع\n\n"
        "⏳ الرجاء الانتظار...",
        parse_mode="HTML",
    )

    try:
        request = BookingRequest(
            user_id=message.chat.id,
            event_url=event_url,
            tickets=tickets,
            team=data.get("team", ""),
            section=section,
        )

        result = await booking_engine.execute_booking(request)

        try:
            await processing_msg.delete()
        except Exception:
            pass

        if result.success:
            bot_monitor.record_booking_success(result.duration)

            # Record in DB
            try:
                add_booking_record(
                    user_id=message.chat.id,
                    event_name=data.get("event_name", ""),
                    event_id=event_id,
                    team=data.get("team"),
                    tickets=tickets,
                    seats=section,
                    status="pending_payment",
                )
            except Exception as e:
                logger.warning("DB record error: %s", e)

            # Build receipt
            receipt = Responder.format_booking_receipt(
                event_name=data.get("event_name", "الفعالية"),
                tickets=tickets,
                section=section,
                team=data.get("team"),
                duration=result.duration,
            )

            # Add payment button
            buttons = []
            if result.checkout_url and "webook.com" in result.checkout_url:
                buttons.append([InlineKeyboardButton(text="💳 ادفع الآن", url=result.checkout_url)])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

            # Send screenshot if available
            if result.screenshot_path and os.path.exists(result.screenshot_path):
                try:
                    photo = FSInputFile(result.screenshot_path)
                    await message.answer_photo(photo=photo, caption="📸 حالة الحجز")
                except Exception:
                    pass

            await message.answer(receipt, reply_markup=keyboard, parse_mode="HTML")

            # Show progress breakdown
            if result.message:
                await message.answer(
                    f"📊 <b>تفاصيل الأداء:</b>\n{result.message}",
                    parse_mode="HTML",
                )
        else:
            bot_monitor.record_booking_failure(result.error_code, result.duration)

            # Send screenshot
            if result.screenshot_path and os.path.exists(result.screenshot_path):
                try:
                    photo = FSInputFile(result.screenshot_path)
                    await message.answer_photo(
                        photo=photo,
                        caption=f"❌ {result.error_code}: فشل الحجز",
                    )
                except Exception:
                    pass

            await message.answer(
                f"❌ <b>فشل الحجز</b>\n\n"
                f"السبب: {result.message or result.error_code}\n\n"
                "حاول مرة أخرى بإرسال الرابط.",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error("Booking execution error: %s", e)
        bot_monitor.record_booking_failure(str(e))
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(f"❌ خطأ غير متوقع: {str(e)}")

    finally:
        # Cleanup
        await booking_engine.cleanup_user(message.chat.id)
        await state.clear()
