import os
import asyncio
import re
from typing import Dict
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import Page

from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.browser_manager import BrowserManager
from services.webook_automation import WebookAutomation
from services.event_scraper import EventScraper
from utils.validators import validate_webook_url, validate_seat_numbers
from utils.formatters import format_event_summary, format_booking_receipt
from data.db import DatabaseManager, add_booking_record

router = Router()

class BookingState(StatesGroup):
    waiting_for_event_url = State()
    waiting_for_login = State()
    waiting_for_cookie = State()
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_tickets = State()
    waiting_for_team = State()
    waiting_for_section = State()    # <-- New: user picks section from map
    waiting_for_price = State()
    waiting_for_seats = State()
    processing_payment = State()

async def check_login_and_extract_data(page: Page, event_url: str) -> Dict:
    """Check login status AND extract event data"""
    scraper = EventScraper(page)
    automation = WebookAutomation(page)
    
    # Ensure we navigate to the EVENT page, not the BOOKING page
    # The booking page (/book) redirects to login if not authenticated
    base_url = event_url.split('?')[0] # remove query params
    if base_url.endswith('/book'):
        base_url = base_url[:-5]
        
    # Navigate to event
    await automation.navigate_to_event(base_url)
    
    # Check login
    is_logged_in = await automation.check_login_status()
    
    # Extract data
    event_data = await scraper.extract_event_data()
    event_data['is_logged_in'] = is_logged_in
    event_data['url'] = event_url
    
    return event_data

async def handle_login_required(message: types.Message, event_data: Dict):
    """Handle case when user is not logged in"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 تسجيل الدخول بالبريد (داخل البوت)", callback_data="login_via_bot")],
        [InlineKeyboardButton(text="🌐 تسجيل من المتصفح (يدوياً)", url=event_data['url'])],
        [InlineKeyboardButton(text="✅ لقد سجلت دخولي (متابعة)", callback_data="continue_login")]
    ])
    
    await message.answer(
        f"⚠️ <b>يجب تسجيل الدخول أولاً لفتح خريطة المقاعد وحجز الفعالية</b>\n\n"
        f"📋 <b>تفاصيل الفعالية التي تم العثور عليها:</b>\n"
        f"• {event_data['name']}\n"
        f"• {event_data['date']}\n"
        f"• {event_data['venue']}\n\n"
        f"لتتمكن من إكمال الحجز بشكل صحيح يرجى اختيار أحد الطرق التالية:\n"
        f"- إعطاء البوت البريد و الرقم السري ليسجل لك تلقائياً\n"
        f"- أتسجيل الدخول يدوياً والضغط على متابعة.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.message(F.text == "/book")
async def start_booking(message: types.Message, state: FSMContext):
    await message.answer(
        "🎫 <b>مرحباً بك في نظام الحجز الذكي!</b>\n\n"
        "أرسل رابط الفعالية من Webook.com",
        parse_mode="HTML"
    )
    await state.set_state(BookingState.waiting_for_event_url)

@router.message(F.text.startswith("https://webook.com"))
async def process_event_url(message: types.Message, state: FSMContext):
    """Process event URL and extract data automatically"""
    event_url = message.text
    
    # Send processing message
    processing_msg = await message.answer(
        "⏳ <b>جاري تحليل الفعالية...</b>\n\n"
        "• جاري فتح الصفحة\n"
        "• استخراج البيانات\n"
        "• التحقق من تسجيل الدخول\n\n"
        "قد يستغرق 10-15 ثانية...",
        parse_mode="HTML"
    )
    
    try:
        # Initialize browser
        browser_mgr = BrowserManager()
        await browser_mgr.initialize()
        context, page = await browser_mgr.create_session(message.from_user.id)
        
        # Extract data AND check login
        event_data = await check_login_and_extract_data(page, event_url)
        
        # Save to state
        await state.update_data(
            event_url=event_url,
            event_name=event_data['name'],
            event_type=event_data['type'],
            teams=event_data['teams'],
            date=event_data['date'],
            venue=event_data['venue'],
            price_range=event_data['price_range'],
            is_logged_in=event_data['is_logged_in']
        )
        
        await processing_msg.delete()
        
        # Check if logged in
        if not event_data['is_logged_in']:
            await handle_login_required(message, event_data)
            await state.set_state(BookingState.waiting_for_login)
            return
        
        # User is logged in, show event details
        event_summary = format_event_summary(event_data)
        event_summary += "\n🎫 <b>كم تذكرة تريد؟</b> (1-10)"
        
        # Send event image if available
        if event_data['image_url'] and event_data['image_url'].startswith('http'):
            try:
                await message.answer_photo(
                    photo=event_data['image_url'],
                    caption=event_summary,
                    parse_mode="HTML"
                )
            except:
                await message.answer(event_summary, parse_mode="HTML")
        else:
            await message.answer(event_summary, parse_mode="HTML")
        
        await state.set_state(BookingState.waiting_for_tickets)
        
    except Exception as e:
        await processing_msg.delete()
        await message.answer(f"❌ حدث خطأ: {str(e)}\n\nتأكد من الرابط وحاول مرة أخرى.")

@router.callback_query(F.data == "login_via_bot", BookingState.waiting_for_login)
async def process_login_via_bot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📧 <b>أرسل بريدك الإلكتروني المسجل في Webook:</b>", parse_mode="HTML")
    await state.set_state(BookingState.waiting_for_email)
    await callback.answer()

@router.message(BookingState.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("🔒 <b>أرسل كلمة المرور الخاصة بك:</b>\n(ملاحظة: لا نقوم بحفظ كلمة المرور وسيم مسحها فور الانتهاء)", parse_mode="HTML")
    await state.set_state(BookingState.waiting_for_password)

@router.message(BookingState.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text
    # We delete the message containing the password for security
    try:
        await message.delete()
    except:
        pass
        
    data = await state.get_data()
    email = data.get('email')
    
    processing_msg = await message.answer("⏳ <b>جاري محاولة تسجيل الدخول...</b>\nقد يستغرق بضع ثوانٍ.", parse_mode="HTML")
    
    try:
        browser_mgr = BrowserManager()
        session = await browser_mgr.get_session(message.chat.id)
        if not session:
            raise Exception("انتهت الجلسة. أعد المحاولة عبر إرسال الرابط من جديد.")
            
        context, page = session
        automation = WebookAutomation(page)
        
        success = await automation.login_with_credentials(email, password)
        await processing_msg.delete()
        
        if success:
            event_summary = f"""
✅ <b>تم تسجيل الدخول بنجاح!</b>

🏆 <b>{data.get('event_name', 'الفعالية')}</b>
📅 {data.get('date', 'غير محدد')}
🏟️ {data.get('venue', 'غير محدد')}

🎫 <b>كم تذكرة تريد؟</b> (1-10)
"""
            await message.answer(event_summary, parse_mode="HTML")
            await state.set_state(BookingState.waiting_for_tickets)
        else:
            await message.answer("❌ <b>فشل تسجيل الدخول.</b> يرجى التأكد من البريد وكلمة المرور.", parse_mode="HTML")
            
            # Check for failure screenshot
            screenshot_path = 'screenshots/login_failure.png'
            if os.path.exists(screenshot_path):
                try:
                    photo = FSInputFile(screenshot_path)
                    await message.answer_photo(
                        photo=photo,
                        caption="📸 <b>لقطة شاشة لسبب الفشل:</b>\nقد تظهر لك رسالة خطأ أو طلب التحقق (Captcha).",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            await message.answer("أعد المحاولة بإرسال رابط الفعالية للبدء من جديد.")
            await state.clear()
            
    except Exception as e:
        await processing_msg.delete()
        await message.answer(f"❌ حدث خطأ: {e}")
        await state.clear()

@router.callback_query(F.data == "continue_login", BookingState.waiting_for_login)
async def continue_after_manual_login(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "لتتمكن من المتابعة بعد تسجيل الدخول يدوياً المتصفح، يحتاج البوت إلى ملفات تعريف الارتباط (Cookies) الخاصة بجلستك.\n\n"
        "<b>كيفية الحصول عليها (للمحترفين):</b>\n"
        "1. افتح Webook على الكمبيوتر وسجل دخولك.\n"
        "2. اضغط F12 لفتح أدوات المطور (Developer Tools).\n"
        "3. اذهب إلى Network ثم أعد تحميل الصفحة.\n"
        "4. اضغط على أول طلب (غالباً اسم الفعالية)، وابحث في اليمين عن Request Headers.\n"
        "5. انسخ القيمة الموجودة بجانب كلمة <code>cookie:</code> وأرسلها هنا.\n\n"
        "<i>إذا كان هذا معقداً، يمكنك استخدام خيار تسجيل الدخول بالبريد داخل البوت.</i>",
        parse_mode="HTML"
    )
    await state.set_state(BookingState.waiting_for_cookie)
    await callback.answer()

@router.message(BookingState.waiting_for_cookie)
async def process_cookie(message: types.Message, state: FSMContext):
    cookie_string = message.text.strip()
    
    # Remove "cookie: " prefix if the user copied the whole line
    if cookie_string.lower().startswith("cookie:"):
        cookie_string = cookie_string[7:].strip()
        
    try:
        await message.delete() # Security: Delete cookie message from chat
    except:
        pass
        
    processing_msg = await message.answer("⏳ <b>جاري حقن الجلسة والتحقق...</b>", parse_mode="HTML")
    
    try:
        browser_mgr = BrowserManager()
        session = await browser_mgr.get_session(message.chat.id)
        if not session:
            raise Exception("انتهت الجلسة. يرجى إرسال الرابط من جديد.")
            
        context, page = session
        
        # Parse cookie string
        cookies = []
        # Support both ';' and newline separation
        pairs = cookie_string.replace('\n', ';').split(';')
        
        for pair in pairs:
            if '=' in pair:
                try:
                    name, value = pair.strip().split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.webook.com', # Use wild card for webook
                        'path': '/'
                    })
                except:
                    continue
        
        if not cookies:
             raise Exception("لم يتم العثور على ملفات تعريف ارتباط صالحة في النص المرسل.")
             
        # Inject cookies
        await context.add_cookies(cookies)
        
        # CRITICAL: Robust navigation to Webook
        try:
            # Using wait_until="domcontentloaded" is safer against redirect chains
            await page.goto("https://webook.com/ar/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5) # Give it time to resolve background redirects
        except Exception as e:
            print(f"Navigation warning: {e}")
            # If we were interrupted by another navigation, that's often OK for cookie verification
        
        # Verify
        automation = WebookAutomation(page)
        is_logged_in = await automation.check_login_status()
        
        await processing_msg.delete()
        if is_logged_in:
            data = await state.get_data()
            event_summary = f"""
✅ <b>تم ربط الجلسة بنجاح!</b>

🏆 <b>{data.get('event_name', 'الفعالية')}</b>
📅 {data.get('date', 'غير محدد')}
🏟️ {data.get('venue', 'غير محدد')}

🎫 <b>كم تذكرة تريد؟</b> (أرسل رقم من 1 إلى 10)
"""
            await message.answer(event_summary, parse_mode="HTML")
            await state.set_state(BookingState.waiting_for_tickets)
        else:
            await message.answer(
                "❌ <b>فشل ربط الجلسة.</b>\n"
                "يبدو أن ملفات تعريف الارتباط غير صحيحة أو انتهت صلاحيتها.\n\n"
                "تأكد من نسخ القيمة الموجودة <b>بعد</b> كلمة <code>cookie:</code> بالكامل."
            )
            # Don't clear state, let them try cookies again
            
    except Exception as e:
        if processing_msg:
            try: await processing_msg.delete()
            except: pass
        await message.answer(f"❌ حدث خطأ: {str(e)}")
        # Don't clear state, let them try cookies again


@router.message(BookingState.waiting_for_tickets)
async def process_tickets(message: types.Message, state: FSMContext):
    try:
        tickets = int(message.text)
        if not (1 <= tickets <= 10):
            raise ValueError
        
        await state.update_data(tickets=tickets)
        data = await state.get_data()
        
        if data.get('event_type') == 'match' and len(data.get('teams', [])) >= 2:
            teams = data['teams']
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🟡 {teams[0]}", callback_data="team_0")],
                [InlineKeyboardButton(text=f"🟢 {teams[1]}", callback_data="team_1")]
            ])
            await message.answer("⚽ <b>اختر الفريق:</b>", reply_markup=keyboard, parse_mode="HTML")
            await state.set_state(BookingState.waiting_for_team)
        else:
            # If not a match or teams not found, skip team selection
            await proceed_to_map(message, state)
            
    except ValueError:
        await message.answer("❌ أرسل رقماً صحيحاً بين 1 و 10")

@router.callback_query(F.data.startswith("team_"), BookingState.waiting_for_team)
async def process_team(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    teams = data.get('teams', [])
    
    if callback.data == "team_0":
        team = teams[0]
    else:
        team = teams[1]
        
    await state.update_data(team=team)
    await callback.message.answer(f"✅ تم اختيار: {team}")
    
    # Proceed to select category or direct to map
    await proceed_to_map(callback.message, state)

async def proceed_to_map(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    processing_msg = await message.answer(
        "⏳ <b>جاري فتح خريطة الملعب...</b>\n\n"
        "قد يستغرق بضع ثوانٍ...",
        parse_mode="HTML"
    )
    
    try:
        browser_mgr = BrowserManager()
        session = await browser_mgr.get_session(message.chat.id)
        if not session:
            raise Exception("انتهت الجلسة. يرجى البدء من جديد عبر /book.")
            
        context, page = session
        automation = WebookAutomation(page)
        
        # Navigate to the /book URL
        event_url = data.get('event_url', '')
        booking_url = event_url.split('?')[0]
        if not booking_url.endswith('/book'):
            booking_url = booking_url.rstrip('/') + '/book'
        
        print(f"Navigating to booking URL: {booking_url}")    
        await automation.navigate_to_event(booking_url)
        
        # Wait for map to load
        await automation.wait_for_seat_map()
        
        # Take screenshot
        screenshot_path = await automation.take_seat_map_screenshot(message.chat.id)
        
        # Try to get section names
        sections = await automation.get_available_sections()
        
        await processing_msg.delete()
        
        # Send the map screenshot
        photo_file = FSInputFile(screenshot_path)
        await message.answer_photo(
            photo=photo_file,
            caption=(
                "📸 <b>خريطة الملعب</b>\n\n"
                "اختر القسم الذي تريد الجلوس فيه.\n"
                "أرسل <b>اسم القسم</b> كما يظهر في الخريطة\n\n"
                "<b>أمثلة على الأقسام:</b> D9 أو D10 أو A1 أو VIP"
            ),
            parse_mode="HTML"
        )
        
        # If we found sections, show them as buttons
        if sections and len(sections) > 0 and len(sections) <= 20:
            # Filter to likely section names
            valid_sections = [s for s in sections if len(s) <= 8 and s.replace('-','').replace('_','').isalnum()][:12]
            if valid_sections:
                buttons = []
                for i in range(0, len(valid_sections), 3):
                    row = [
                        types.InlineKeyboardButton(text=s, callback_data=f"section_{s}")
                        for s in valid_sections[i:i+3]
                    ]
                    buttons.append(row)
                
                keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
                await message.answer(
                    "أو اختر من القائمة:",
                    reply_markup=keyboard
                )
        
        await state.set_state(BookingState.waiting_for_section)
        
    except Exception as e:
        await processing_msg.delete()
        await message.answer(
            f"❌ <b>حدث خطأ أثناء فتح خريطة الملعب</b>\n\n"
            f"تفاصيل الخطأ: {str(e)}\n\n"
            "تأكد من أنك سجلت الدخول وأن الفعالية متاحة، ثم أرسل الرابط من جديد لإعادة المحاولة.",
            parse_mode="HTML"
        )
        await state.clear()


@router.message(BookingState.waiting_for_section)
async def process_section_text(message: types.Message, state: FSMContext):
    section = message.text.strip().upper()
    await _select_section(message, state, section)


@router.callback_query(F.data.startswith("section_"), BookingState.waiting_for_section)
async def process_section_button(callback: types.CallbackQuery, state: FSMContext):
    section = callback.data.replace("section_", "")
    await callback.answer()
    await _select_section(callback.message, state, section)


async def _select_section(message: types.Message, state: FSMContext, section: str):
    data = await state.get_data()
    tickets = data.get('tickets', 1)
    
    processing_msg = await message.answer(
        f"⏳ <b>جاري اختيار القسم {section} وحجز {tickets} تذكرة...</b>",
        parse_mode="HTML"
    )
    
    try:
        browser_mgr = BrowserManager()
        session = await browser_mgr.get_session(message.chat.id)
        if not session:
            raise Exception("انتهت الجلسة. يرجى البدء من جديد.")
            
        context, page = session
        automation = WebookAutomation(page)
        
        # Click the section
        clicked = await automation.click_section(section)
        
        if not clicked:
            await processing_msg.delete()
            await message.answer(
                f"❌ لم أتمكن من النقر على القسم <b>{section}</b>.\n"
                "تأكد من الاسم الصحيح كما يظهر في الخريطة وأرسله مرة أخرى.",
                parse_mode="HTML"
            )
            return  # Keep state waiting_for_section
        
        # Set ticket quantity and add to cart
        added = await automation.get_ticket_count(section, tickets)
        
        # Take screenshot of updated map / cart
        screenshot_path = await automation.take_seat_map_screenshot(message.chat.id)
        
        await processing_msg.delete()
        
        if added:
            # Proceed to checkout
            checkout_url = await automation.proceed_to_checkout()
            
            event_name = data.get('event_name', 'الفعالية')
            receipt = format_booking_receipt(
                event_name=event_name,
                tickets=tickets,
                seats=[section],
                team=data.get('team')
            )
            
            # Record to DB
            try:
                add_booking_record(
                    user_id=message.chat.id,
                    event_name=event_name,
                    team=data.get('team'),
                    tickets=tickets,
                    seats=section,
                    status="pending_payment"
                )
            except Exception as e:
                print(f"DB record error: {e}")
            
            # Build pay button
            buttons = []
            if checkout_url and 'webook.com' in checkout_url:
                buttons.append([types.InlineKeyboardButton(text="💳 ادفع الآن", url=checkout_url)])
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
            
            await message.answer(
                receipt,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Send map screenshot so user can see the state
            photo_file = FSInputFile(screenshot_path)
            await message.answer_photo(
                photo=photo_file,
                caption=(
                    f"✅ تم النقر على القسم <b>{section}</b>!\n\n"
                    "لم أتمكن من العثور على زر 'أضف للسلة' تلقائياً.\n"
                    "هل تريد المتابعة يدوياً أو تجربة قسم آخر؟",
                ),
                parse_mode="HTML"
            )
        
        await browser_mgr.close_session(message.chat.id)
        await state.clear()
        
    except Exception as e:
        await processing_msg.delete()
        await message.answer(f"❌ حدث خطأ: {str(e)}\n\nحاول مرة أخرى.")
        await state.clear()




@router.message(BookingState.waiting_for_seats)
async def process_seat_selection(message: types.Message, state: FSMContext):
    try:
        seat_text = message.text
        seat_numbers = [int(x.strip()) for x in seat_text.split(',')]
        
        if not seat_numbers:
            raise ValueError("لا يوجد مقاعد")
            
        data = await state.get_data()
        tickets = data['tickets']
        
        if len(seat_numbers) != tickets:
            return await message.answer(
                f"❌ عدد المقاعد ({len(seat_numbers)}) لا يطابق عدد التذاكر ({tickets})\n\n"
                "أرسل المقاعد مرة أخرى."
            )
            
    except ValueError:
        return await message.answer(
            "❌ صيغة غير صحيحة\n\n"
            "أرسل أرقام المقاعد فقط، مثال:\n"
            "7,8,9,10"
        )
        
    processing_msg = await message.answer(
        "⏳ <b>جاري إكمال الحجز...</b>",
        parse_mode="HTML"
    )
    
    try:
        browser_mgr = BrowserManager()
        session = await browser_mgr.get_session(message.chat.id)
        
        if not session:
            raise Exception("انتهت الجلسة. ابدأ من جديد.")
            
        context, page = session
        automation = WebookAutomation(page)
        
        await automation.select_seats(seat_numbers)
        # 5. Proceed to checkout
        checkout_url = await automation.proceed_to_checkout()
        
        # 6. Format final receipt
        event_name = data.get('event_data', {}).get('name', 'الفعالية')
        receipt = format_booking_receipt(
            event_name=event_name,
            tickets=data['tickets'],
            seats=seat_numbers,
            team=data.get('team')
        )
        
        # 7. Add checkout button
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(
            text="💳 ادفع الآن",
            url=checkout_url
        ))
        
        # 8. Record to DB if available
        try:
            add_booking_record(
                user_id=message.chat.id,
                event_name=event_name,
                team=data.get('team'),
                tickets=data['tickets'],
                seats=','.join(map(str, seat_numbers)),
                status="pending_payment"
            )
        except Exception as e:
            print(f"Could not record booking: {e}")
        
        await message.answer(
            receipt,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
        await browser_mgr.close_session(message.chat.id)
        await state.clear()
        
    except Exception as e:
        await processing_msg.delete()
        await message.answer(f"❌ حدث خطأ: {str(e)}\n\nحاول من جديد.")
        await state.clear()
