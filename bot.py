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

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ================= الدوال المساعدة =================

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

async def human_delay(min_sec=1.0, max_sec=2.5):
    """تأخير زمني عشوائي لمحاكاة السلوك البشري"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def solve_captcha_via_free_audio(page, bframe, chat_id, context) -> bool:
    """حل الكابتشا عبر التحدي الصوتي مع محاكاة البشر"""
    try:
        await context.bot.send_message(chat_id=chat_id, text="🎧 جاري التحويل إلى التحدي الصوتي...")
        
        await human_delay(1.5, 2.5)
        audio_btn = await bframe.query_selector("#recaptcha-audio-button")
        if not audio_btn:
            logging.error("لم يتم العثور على زر الصوت.")
            return False
        await audio_btn.click()
        await page.wait_for_timeout(3000)

        doscaptcha = await bframe.query_selector(".rc-doscaptcha-header")
        if doscaptcha and await doscaptcha.is_visible():
            await context.bot.send_message(chat_id=chat_id, text="🚫 جوجل قامت بحظر الـ IP مؤقتاً (Try again later). يرجى المحاولة بعد فترة أو استخدام بروكسي.")
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
            logging.error("لم يتم العثور على رابط ملف الصوت.")
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
                        await context.bot.send_message(chat_id=chat_id, text="🔄 جوجل تطلب حل صوت إضافي للتأكد (Multiple solutions)، جاري الحل مرة ثانية...")
                        return "RETRY" 
                    else:
                        logging.error("الرد الصوتي غير صحيح.")
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
        "🚀 البوت الذكي جاهز.\nأرسل عدد الأكواد المطلوبة لاستخراجها:",
        reply_markup=reply_markup
    )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    if text == "فحص مفتاح الAi":
        if not GEMINI_API_KEY:
            await update.message.reply_text("❌ متغير البيئة GEMINI_API_KEY غير موجود.")
            return
        if not ai_client:
            await update.message.reply_text("❌ فشل تهيئة عميل Gemini.")
            return
        
        checking_msg = await update.message.reply_text("🔍 جاري فحص الاتصال...")
        try:
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Say 'CONNECTED'",
            )
            if response and response.text:
                await checking_msg.edit_text(f"✅ متصل بنجاح: {response.text.strip()}")
            else:
                await checking_msg.edit_text("⚠️ متصل بدون رد صحيح.")
        except Exception as e:
            await checking_msg.edit_text(f"❌ فشل الاتصال:\n{e}")
        return

    if not text.isdigit():
        return

    count = int(text)
    status_msg = await update.message.reply_text(f"⚡ جاري بدء العمل واستخراج {count} رابط ببطء بشري...")

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
                        "--disable-blink-features=AutomationControlled",
                        "--window-size=1920,1080",
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
            
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
            """)

            try:
                await page.goto(SITE_URL, timeout=45000, wait_until="domcontentloaded")
                await human_delay(2.0, 4.0)
                
                shot1 = "step_1_open.png"
                await page.screenshot(path=shot1, full_page=True)
                with open(shot1, "rb") as photo:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo, caption="🌐 الخطوة 1: تم فتح الموقع بنجاح.")
            except Exception as e:
                await status_msg.edit_text(f"❌ خطأ أثناء فتح الموقع: {e}")
                await browser.close()
                return

            all_extracted_codes = []

            for i in range(count):
                email = generate_random_email()
                
                email_input = await page.query_selector("input[name='email'], input[type='email']")
                if email_input:
                    await email_input.fill("") 
                    for char in email:
                        await email_input.type(char, delay=random.randint(50, 150))
                    
                    await page.evaluate("""el => {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""", email_input)

                await human_delay(1.5, 2.5)

                submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
                if submit_btn:
                    await submit_btn.click(force=True)

                await page.wait_for_timeout(4000)

                shot2 = "step_2_submitted.png"
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
                            await page.wait_for_timeout(3500)
                except Exception as e:
                    print(f"مربع التحقق غير موجود: {e}")

                max_captcha_rounds = 5
                for round_num in range(max_captcha_rounds):
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

                    try:
                        doscaptcha_main = await bframe.query_selector(".rc-doscaptcha-header")
                        if doscaptcha_main and await doscaptcha_main.is_visible():
                            await context.bot.send_message(chat_id=chat_id, text="🚫 الموقع حظر الـ IP مؤقتاً (Try again later). سيتم تخطي هذا الطلب.")
                            break
                    except:
                        pass

                    await context.bot.send_message(chat_id=chat_id, text=f"🤖 ظهرت الكابتشا (الجولة {round_num + 1})، جاري الحل...")

                    audio_solved = await solve_captcha_via_free_audio(page, bframe, chat_id, context)
                    
                    if audio_solved == "RETRY":
                        continue
                    elif audio_solved == True:
                        await page.wait_for_timeout(3000)
                        still_active = False
                        for frame in page.frames:
                            if "bframe" in frame.url:
                                try:
                                    p_load = await frame.query_selector(".rc-imageselect-payload, .rc-audiochallenge-payload")
                                    if p_load and await p_load.is_visible():
                                        still_active = True
                                except:
                                    pass

                        if still_active:
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم يتم قبول الحل، جاري المحاولة...")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم حل الكابتشا بنجاح!")
                            break
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ فشل الحل، جاري المحاولة...")

                # ==========================================
                # الخطوة 3: الضغط على زر "Obtener código"
                # ==========================================
                await context.bot.send_message(chat_id=chat_id, text="🖱️ جاري الضغط على زر 'Obtener código' الأولي...")
                try:
                    obtener_btn = await page.query_selector("button:has-text('Obtener'), button[type='submit']")
                    if obtener_btn:
                        await human_delay(1.0, 2.0)
                        await obtener_btn.click(force=True)
                    elif email_input:
                        await email_input.press("Enter")
                except Exception as e:
                    print(f"خطأ في الضغط على Obtener: {e}")
                
                # انتظار 5 ثواني لظهور صفحة الكود والزر السمائي
                await page.wait_for_timeout(5000)

                shot3 = f"step_3_code_generated_{i+1}.png"
                await page.screenshot(path=shot3, full_page=True)
                with open(shot3, "rb") as photo:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🎯 تم توليد الكود (طلب {i+1})، جاري التفعيل وسحب الرابط...")

                # ==========================================
                # الخطوة 4: سحب الكود والضغط على 'Actívalo ya'
                # ==========================================
                try:
                    # استخراج الكود النصي كاحتياط
                    promo_code = await page.evaluate("""() => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (let el of inputs) {
                            if (el.value && el.value.length > 8 && !el.value.includes('@')) {
                                return el.value.trim();
                            }
                        }
                        return "";
                    }""")

                    # البحث عن الزر السمائي
                    activalo_btn = await page.query_selector("text='Actívalo ya', a:has-text('Actívalo ya'), button:has-text('Actívalo ya')")
                    extracted_link = ""
                    
                    if activalo_btn:
                        # جلب الرابط المباشر من الزر (إذا كان الزر عبارة عن رابط)
                        extracted_link = await activalo_btn.get_attribute("href")
                        
                        # الضغط على الزر لتفعيل الكود
                        await human_delay(1.0, 2.0)
                        await activalo_btn.click(force=True)
                        await page.wait_for_timeout(4000)
                    
                    # إذا لم نجد الرابط في الزر، نسحبه من متصفح الصفحة بعد الضغط
                    if not extracted_link or extracted_link == "#" or not extracted_link.startswith("http"):
                        extracted_link = page.url

                    # ترتيب وتنسيق النتيجة النهائية للإرسال
                    final_result = ""
                    if extracted_link and SITE_URL not in extracted_link and extracted_link.startswith("http"):
                        if promo_code:
                            final_result = f"🎁 الكود: `{promo_code}`\n🔗 الرابط: {extracted_link}"
                        else:
                            final_result = f"🔗 الرابط: {extracted_link}"
                    elif promo_code:
                        final_result = f"🎁 الكود: `{promo_code}`"
                        
                    if final_result and final_result not in all_extracted_codes:
                        all_extracted_codes.append(final_result)

                except Exception as e:
                    print(f"خطأ في خطوة Actívalo ya: {e}")

                await human_delay(3.0, 5.0) # انتظار لتخفيف الضغط بين الطلبات

            if all_extracted_codes:
                final_text = "\n\n".join(all_extracted_codes)
                await context.bot.send_message(chat_id=TARGET_CHANNEL_ID, text=f"🚀 الأكواد والروابط المستخرجة:\n\n{final_text}")
                await status_msg.edit_text(f"✅ تمت العملية بنجاح وتم إرسال {len(all_extracted_codes)} تفعيل إلى قناتك!")
            else:
                await status_msg.edit_text(f"✅ انتهت العملية، يرجى مراجعة الصور للتأكد من النتيجة.")
                
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
