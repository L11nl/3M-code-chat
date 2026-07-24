import logging
import random
import string
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from playwright.async_api import async_playwright

TOKEN = os.getenv("TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "-1003642554894"))

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

SITE_URL = "https://www.bbvadescuentos.mx/develop/openai-3msc"

user_selected_boxes = set()
captcha_future = None
current_page = None

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

def get_captcha_keyboard():
    keyboard = []
    for r in range(3):
        row = []
        for c in range(3):
            box_num = r * 3 + c + 1
            status = "✅" if box_num in user_selected_boxes else "🟩"
            row.append(InlineKeyboardButton(f"{box_num} {status}", callback_data=f"box_{box_num}"))
        keyboard.append(row)
    
    keyboard.append([
        InlineKeyboardButton("🔄 إعادة ضبط", callback_data="reset_boxes"),
        InlineKeyboardButton("🚀 إرسال الحل والتنفيذ", callback_data="verify_solution")
    ])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 البوت جاهز. أرسل عدد الأكواد المطلوبة:")

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global captcha_future, current_page
    text = update.message.text.strip()
    if not text.isdigit():
        return

    count = int(text)
    status_msg = await update.message.reply_text(f"⚡ جاري بدء عملية استخراج {count} كود...")

    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
            except Exception as e:
                await status_msg.edit_text(f"❌ خطأ في تشغيل المتصفح: {e}")
                return

            context_browser = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context_browser.new_page()
            current_page = page

            try:
                await page.goto(SITE_URL, timeout=40000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                await status_msg.edit_text(f"❌ خطأ أثناء فتح الموقع: {e}")
                await browser.close()
                return

            all_codes = []
            for i in range(count):
                email = generate_random_email()
                
                email_input = await page.query_selector("input[name='email'], input[type='email']")
                if email_input:
                    await email_input.fill(email)

                submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
                if submit_btn:
                    await submit_btn.click()

                await page.wait_for_timeout(3000)

                # التحقق من وجود الكابتشا
                recaptcha_frame = None
                for frame in page.frames:
                    if "recaptcha" in frame.url:
                        recaptcha_frame = frame
                        break

                if recaptcha_frame or await page.query_selector("iframe[src*='recaptcha']"):
                    await status_msg.edit_text("⚠️ ظهرت الكابتشا! جاري التقاط الصورة...")
                    
                    screenshot_path = "captcha.png"
                    try:
                        captcha_element = await page.query_selector(".g-recaptcha, iframe[src*='recaptcha']")
                        if captcha_element:
                            await captcha_element.screenshot(path=screenshot_path)
                        else:
                            await page.screenshot(path=screenshot_path)
                    except Exception:
                        await page.screenshot(path=screenshot_path)

                    user_selected_boxes.clear()
                    captcha_future = asyncio.get_running_loop().create_future()

                    with open(screenshot_path, "rb") as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption="🔍 يرجى تحديد المربعات المطلوبة من الشبكة أدناه واضغط 'إرسال الحل':",
                            reply_markup=get_captcha_keyboard()
                        )

                    await captcha_future

                    try:
                        frames = page.frames
                        for f in frames:
                            if "bframe" in f.url:
                                for box_num in user_selected_boxes:
                                    tiles = await f.query_selector_all(".rc-imageselect-tile")
                                    if tiles and box_num <= len(tiles):
                                        await tiles[box_num - 1].click()
                                        await asyncio.sleep(0.5)
                                verify_btn = await f.query_selector("#recaptcha-verify-button")
                                if verify_btn:
                                    await verify_btn.click()
                                    await asyncio.sleep(3)
                    except Exception as e:
                        print(f"خطأ أثناء النقر على المربعات: {e}")

                await asyncio.sleep(2)
                
            await status_msg.edit_text(f"✅ تمت العملية بنجاح!")
            await browser.close()
            
    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ غير متوقع: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global captcha_future
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("box_"):
        box_num = int(data.split("_")[1])
        if box_num in user_selected_boxes:
            user_selected_boxes.remove(box_num)
        else:
            user_selected_boxes.add(box_num)
        await query.edit_message_reply_markup(reply_markup=get_captcha_keyboard())
        
    elif data == "reset_boxes":
        user_selected_boxes.clear()
        await query.edit_message_reply_markup(reply_markup=get_captcha_keyboard())
        
    elif data == "verify_solution":
        await query.edit_message_text(text="✅ تم استلام اختياراتك، جاري تطبيقها في المتصفح...")
        if captcha_future and not captcha_future.done():
            captcha_future.set_result(True)

def main():
    if not TOKEN:
        print("خطأ: يرجى تعيين متغير البيئة TOKEN.")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
