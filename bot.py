import logging
import random
import string
import asyncio
import os
import io
import speech_recognition as sr
from pydub import AudioSegment
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
from google import genai

# ================= الإعدادات والمتغيرات =================
TOKEN = os.getenv("TOKEN")
TARGET_CHANNEL_ID_RAW = os.getenv("TARGET_CHANNEL_ID", "-1003642554894")
try:
    TARGET_CHANNEL_ID = int(TARGET_CHANNEL_ID_RAW)
except ValueError:
    TARGET_CHANNEL_ID = -1003642554894

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

SITE_URL = "https://www.bbvadescuentos.mx/develop/openai-3msc"
BASE_UP_URL = "http://www.chatgpt.com/up/"

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ================= قائمة البروكسيات (Webshare) =================
PROXIES_LIST = [
    "31.59.20.176:6754:nfpomqkz:j7a755wntvaj",
    "31.56.127.193:7684:nfpomqkz:j7a755wntvaj",
    "45.38.107.97:6014:nfpomqkz:j7a755wntvaj",
    "198.105.121.200:6462:nfpomqkz:j7a755wntvaj",
    "64.137.96.74:6641:nfpomqkz:j7a755wntvaj",
    "198.23.243.226:6361:nfpomqkz:j7a755wntvaj",
    "38.154.185.97:6370:nfpomqkz:j7a755wntvaj",
    "84.247.60.125:6095:nfpomqkz:j7a755wntvaj",
    "142.111.67.146:5611:nfpomqkz:j7a755wntvaj",
    "191.96.254.138:6185:nfpomqkz:j7a755wntvaj"
]

# ================= الدوال المساعدة =================

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

async def human_delay(min_sec=1.0, max_sec=2.5):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def solve_captcha_via_free_audio(page, bframe, chat_id, context) -> bool:
    try:
        await context.bot.send_message(chat_id=chat_id, text="🎧 جاري التحويل إلى التحدي الصوتي...")
        
        await human_delay(1.5, 2.5)
        audio_btn = await bframe.query_selector("#recaptcha-audio-button")
        if not audio_btn:
            return False
        await audio_btn.click()
        await page.wait_for_timeout(3000)

        doscaptcha = await bframe.query_selector(".rc-doscaptcha-header")
        if doscaptcha and await doscaptcha.is_visible():
            await context.bot.send_message(chat_id=chat_id, text="🚫 البروكسي الحالي محظور مؤقتاً (Try again later).")
            return False

        audio_url = await bframe.evaluate("""() => {
            const audioSource = document.querySelector('.rc-audiocore-download-link') || document.querySelector('audio');
            return audioSource ? (audioSource.href || audioSource.src) : null;
        }""")
        
        if not audio_url:
            audio_url = await bframe.evaluate("""() => {
                const source = document.querySelector('audio source');
                return source ? source.src : null;
            }""")

        if not audio_url:
            return False

        audio_response = await page.request.get(audio_url)
        mp3_bytes = await audio_response.body()
        if not mp3_bytes:
            return False

        sound = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
        wav_io = io.BytesIO()
        sound.export(wav_io, format="wav")
        wav_io.seek(0)

        r = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = r.record(source)
        
        captcha_text = r.recognize_google(audio_data)
        await context.bot.send_message(chat_id=chat_id, text=f"✍️ النص المستخرج: {captcha_text}")

        audio_input = await bframe.query_selector("#audio-response")
        if audio_input:
            await human_delay(1.0, 2.0)
            await audio_input.fill("")
            for char in captcha_text:
                await audio_input.type(char, delay=random.randint(150, 350))
            
            await human_delay(1.0, 2.0)

            verify_btn = await bframe.query_selector("#recaptcha-verify-button")
            if verify_btn:
                await verify_btn.click()
                await page.wait_for_timeout(4000)
                
                error_msg = await bframe.query_selector(".rc-audiochallenge-error-message")
                if error_msg and await error_msg.is_visible():
                    error_text = await error_msg.inner_text()
                    if "Multiple correct solutions required" in error_text:
                        await context.bot.send_message(chat_id=chat_id, text="🔄 جوجل تطلب حل صوت إضافي للتأكد...")
                        return "RETRY" 
                    return False
                    
                return True

    except sr.UnknownValueError:
        logging.error("الصوت مشوش وغير مفهوم.")
    except Exception as e:
        logging.error(f"خطأ في حل الكابتشا الصوتي: {e}")
    
    return False

# ================= أوامر البوت =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("فحص مفتاح الAi")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "🚀 البوت الذكي جاهز ومحمي بالبروكسيات مع ميزة التصوير.\nأرسل عدد الروابط المطلوبة لاستخراجها:",
        reply_markup=reply_markup
    )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    if text == "فحص مفتاح الAi":
        await update.message.reply_text("✅ مفتاح الـ AI غير مطلوب حالياً، البوت يعمل محلياً بكفاءة.")
        return

    if not text.isdigit():
        return

    count = int(text)
    status_msg = await update.message.reply_text(f"⚡ جاري استخراج {count} رابط...\n(سيتم استخدام IP مختلف وتصوير الخطوات لكل طلب)")

    all_extracted_codes = []

    try:
        async with async_playwright() as p:
            for i in range(count):
                await context.bot.send_message(chat_id=chat_id, text=f"🔄 بدء العمل على الطلب ({i+1}/{count})...")
                
                raw_proxy = random.choice(PROXIES_LIST)
                proxy_parts = raw_proxy.split(":")
                playwright_proxy = None
                
                if len(proxy_parts) == 4:
                    playwright_proxy = {
                        "server": f"http://{proxy_parts[0]}:{proxy_parts[1]}",
                        "username": proxy_parts[2],
                        "password": proxy_parts[3]
                    }
                
                try:
                    browser = await p.chromium.launch(
                        headless=True,
                        proxy=playwright_proxy,
                        args=[
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-blink-features=AutomationControlled",
                            "--window-size=1920,1080",
                            "--headless=new"
                        ]
                    )
                    
                    context_browser = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 800}
                    )
                    
                    page = await context_browser.new_page()
                    
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.chrome = { runtime: {} };
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    """)

                    # انتظار تحميل الموقع (زدنا الوقت لأن البروكسيات قد تكون بطيئة)
                    await page.goto(SITE_URL, timeout=60000, wait_until="domcontentloaded")
                    await human_delay(3.0, 5.0)
                    
                    # ======= لقطة الشاشة 1: فتح الموقع =======
                    shot1 = f"step_1_open_{i+1}.png"
                    await page.screenshot(path=shot1, full_page=True)
                    with open(shot1, "rb") as photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🌐 الخطوة 1 (طلب {i+1}): تم فتح الموقع بنجاح بالبروكسي.")

                    email = generate_random_email()
                    email_input = await page.query_selector("input[name='email'], input[type='email']")
                    if email_input:
                        await email_input.fill("") 
                        for char in email:
                            await email_input.type(char, delay=random.randint(50, 150))
                        await page.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); }", email_input)

                    await human_delay(1.0, 2.0)
                    submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
                    if submit_btn:
                        await submit_btn.click(force=True)

                    await page.wait_for_timeout(5000)

                    # ======= لقطة الشاشة 2: بعد إرسال الإيميل =======
                    shot2 = f"step_2_submitted_{i+1}.png"
                    await page.screenshot(path=shot2, full_page=True)
                    with open(shot2, "rb") as photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"✉️ الخطوة 2 (طلب {i+1}): إدخال الإيميل وإرسال الطلب.")

                    try:
                        recaptcha_frame = None
                        for frame in page.frames:
                            if "anchor" in frame.url:
                                recaptcha_frame = frame
                                break
                        if recaptcha_frame:
                            checkbox = await recaptcha_frame.wait_for_selector("#recaptcha-anchor", timeout=4000)
                            if checkbox:
                                await human_delay(1.0, 2.0)
                                await checkbox.click()
                                await page.wait_for_timeout(4000)
                    except Exception:
                        pass

                    for round_num in range(5):
                        bframe = None
                        for frame in page.frames:
                            if "bframe" in frame.url:
                                bframe = frame
                                break
                        is_captcha_active = False
                        if bframe:
                            try:
                                payload = await bframe.query_selector(".rc-imageselect-payload, .rc-audiochallenge-payload, .rc-doscaptcha-header")
                                if payload and await payload.is_visible():
                                    is_captcha_active = True
                            except:
                                pass
                        
                        if not is_captcha_active:
                            break

                        audio_solved = await solve_captcha_via_free_audio(page, bframe, chat_id, context)
                        if audio_solved == "RETRY":
                            continue
                        elif audio_solved == True:
                            await page.wait_for_timeout(4000)
                            break

                    await context.bot.send_message(chat_id=chat_id, text="🖱️ جاري توليد الكود...")
                    try:
                        obtener_btn = await page.query_selector("button:has-text('Obtener'), button[type='submit']")
                        if obtener_btn:
                            await obtener_btn.click(force=True)
                        elif email_input:
                            await email_input.press("Enter")
                    except:
                        pass
                    
                    await page.wait_for_timeout(6000)

                    # ======= لقطة الشاشة 3: النتيجة النهائية =======
                    shot3 = f"step_3_result_{i+1}.png"
                    await page.screenshot(path=shot3, full_page=True)
                    with open(shot3, "rb") as photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🎯 النتيجة النهائية (طلب {i+1}): صفحة استخراج الكود.")

                    # استخراج الكود
                    promo_code = await page.evaluate("""() => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (let el of inputs) {
                            if (el.value && el.value.length > 8 && !el.value.includes('@')) {
                                return el.value.trim();
                            }
                        }
                        return "";
                    }""")

                    if promo_code:
                        final_link = f"{BASE_UP_URL}{promo_code}"
                        if final_link not in all_extracted_codes:
                            all_extracted_codes.append(final_link)
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم سحب الطلب ({i+1}): {promo_code}")
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ فشل الطلب ({i+1}): راجع الصورة الأخيرة لمعرفة السبب.")
                        
                except Exception as e:
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ خطأ أثناء معالجة الطلب {i+1} (قد يكون بسبب بطء البروكسي): {e}")
                finally:
                    if 'browser' in locals():
                        await browser.close()
                    await human_delay(2.0, 4.0)

            if all_extracted_codes:
                final_text = "\n".join(all_extracted_codes)
                await context.bot.send_message(chat_id=TARGET_CHANNEL_ID, text=f"🚀 تم سحب الروابط بنجاح:\n\n{final_text}")
                await status_msg.edit_text(f"✅ تمت العملية. إرسال {len(all_extracted_codes)} رابط جاهز إلى قناتك!")
            else:
                await status_msg.edit_text(f"❌ انتهت العملية ولم يتم سحب أي رابط بنجاح. يرجى مراجعة الصور.")
                
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
