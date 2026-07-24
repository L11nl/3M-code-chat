import logging
import random
import string
import asyncio
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
from google import genai
from google.genai import types

TOKEN = os.getenv("TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "-1003642554894"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

SITE_URL = "https://www.bbvadescuentos.mx/develop/openai-3msc"

# تهيئة عميل جمناي
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

async def solve_captcha_with_gemini(image_path: str) -> list:
    """إرسال صورة الكابتشا إلى جمناي لتحليلها وإرجاع أقم المربعات الصحيحة"""
    if not ai_client:
        logging.error("مفتاح جمناي غير متوفر!")
        return []
    
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        prompt = (
            "This is a 4x4 grid reCAPTCHA challenge image (16 squares total, numbered 1 to 16 row by row from top-left to bottom-right). "
            "Analyze the instruction text at the top, and identify which tile numbers contain the requested objects. "
            "Return ONLY a Python list of integers representing the correct tile numbers, for example: [5, 6, 9]. "
            "If none contain the object, return []."
        )

        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/png",
                ),
                prompt
            ],
        )
        
        # استخراج الأرقام من إجابة الذكاء الاصطناعي بأمان
        import json
        text_res = response.text.strip()
        # محاولة استخراج الأستركشر كقائمة بايثون
        if "[" in text_res and "]" in text_res:
            start = text_res.find("[")
            end = text_res.rfind("]") + 1
            tiles = json.loads(text_res[start:end])
            return [int(t) for t in tiles if 1 <= t <= 16]
    except Exception as e:
        logging.error(f"خطأ أثناء حل الكابتشا بواسطة جمناي: {e}")
    
    return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 البوت الذكي يعمل الآن (مدعوم بالذكاء الاصطناعي لحل الكابتشا تلقائياً).\nأرسل عدد الأكواد المطلوبة:")

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        return

    count = int(text)
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text(f"⚡ جاري بدء العمل واستخراج الأكواد بالذكاء الاصطناعي...")

    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--headless=new"
                    ]
                )
            except Exception as e:
                await status_msg.edit_text(f"❌ خطأ في تشغيل المتصفح: {e}")
                return

            context_browser = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context_browser.new_page()

            try:
                await page.goto(SITE_URL, timeout=45000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                await status_msg.edit_text(f"❌ خطأ أثناء فتح الموقع: {e}")
                await browser.close()
                return

            for i in range(count):
                email = generate_random_email()
                
                email_input = await page.query_selector("input[name='email'], input[type='email']")
                if email_input:
                    await email_input.fill(email)
                    await page.evaluate("""el => {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""", email_input)

                await page.wait_for_timeout(1000)

                submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
                if submit_btn:
                    await submit_btn.click(force=True)

                await page.wait_for_timeout(3000)

                # النقر على مربع "أنا لست روبوت"
                recaptcha_frame = None
                for frame in page.frames:
                    if "anchor" in frame.url:
                        recaptcha_frame = frame
                        break

                if recaptcha_frame:
                    try:
                        checkbox = await recaptcha_frame.wait_for_selector("#recaptcha-anchor", timeout=5000)
                        if checkbox:
                            await checkbox.click()
                            await page.wait_for_timeout(3000)
                    except Exception as e:
                        print(f"فشل النقر على مربع التحقق: {e}")

                # فحص ظهور شبكة الصور (التحدي 4x4)
                bframe = None
                for frame in page.frames:
                    if "bframe" in frame.url:
                        bframe = frame
                        break

                if bframe and await bframe.query_selector(".rc-imageselect-payload"):
                    await status_msg.edit_text("🤖 ظهرت الكابتشا، جاري إرسالها لـ Gemini للحل التلقائي...")
                    
                    screenshot_path = "captcha.png"
                    try:
                        captcha_element = await page.query_selector("iframe[src*='bframe']")
                        if captcha_element:
                            await captcha_element.screenshot(path=screenshot_path)
                        else:
                            await page.screenshot(path=screenshot_path)
                    except Exception:
                        await page.screenshot(path=screenshot_path)

                    # استدعاء جمناي لتحليل الصورة والحصول على أرقام المربعات
                    correct_boxes = await solve_captcha_with_gemini(screenshot_path)
                    await context.bot.send_message(chat_id=chat_id, text=f"🧠 تم تحليل الكابتشا بواسطة Gemini. المربعات المختارة: {correct_boxes}")

                    try:
                        for f in page.frames:
                            if "bframe" in f.url:
                                tiles = await f.query_selector_all(".rc-imageselect-tile")
                                for box_num in correct_boxes:
                                    if tiles and box_num <= len(tiles):
                                        await tiles[box_num - 1].click(force=True)
                                        await asyncio.sleep(0.4)
                                
                                verify_btn = await f.query_selector("#recaptcha-verify-button")
                                if verify_btn:
                                    await verify_btn.click(force=True)
                                    await asyncio.sleep(3)
                    except Exception as e:
                        print(f"خطأ أثناء النقر الآلي على المربعات: {e}")

                await asyncio.sleep(2)
                
            await status_msg.edit_text(f"✅ تمت عملية استخراج الأكواد بالذكاء الاصطناعي بنجاح!")
            await browser.close()
            
    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ غير متوقع: {e}")

def main():
    if not TOKEN:
        print("خطأ: يرجى تعيين متغير البيئة TOKEN.")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request))
    app.run_polling()

if __name__ == "__main__":
    main()
