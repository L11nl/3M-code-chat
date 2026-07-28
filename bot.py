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

async def solve_captcha_via_free_audio(page, bframe, chat_id, context) -> bool:
    """حل الكابتشا عبر التحدي الصوتي محلياً وبشكل مجاني تماماً"""
    try:
        await context.bot.send_message(chat_id=chat_id, text="🎧 جاري التحويل إلى التحدي الصوتي...")
        
        # 1. النقر على أيقونة الصوت
        audio_btn = await bframe.query_selector("#recaptcha-audio-button")
        if not audio_btn:
            logging.error("لم يتم العثور على زر الصوت.")
            return False
        await audio_btn.click()
        await page.wait_for_timeout(2500)

        # 2. استخراج رابط ملف الصوت الصادر من reCAPTCHA
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

        # 3. تحميل ملف الصوت برمجياً عبر المتصفح
        audio_response = await page.request.get(audio_url)
        mp3_bytes = await audio_response.body()
        if not mp3_bytes:
            logging.error("فشل تحميل ملف الصوت.")
            return False

        # 4. تحويل ملف الـ MP3 إلى WAV لتوافقية مكتبة التعرف الصوتي (يعتمد على ffmpeg)
        sound = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
        wav_io = io.BytesIO()
        sound.export(wav_io, format="wav")
        wav_io.seek(0)

        # 5. تفريغ الصوت إلى نص محلياً
        r = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = r.record(source)
        
        captcha_text = r.recognize_google(audio_data)
        await context.bot.send_message(chat_id=chat_id, text=f"✍️ النص المستخرج من الصوت: {captcha_text}")

        # 6. كتابة النص والضغط على تحقق
        audio_input = await bframe.query_selector("#audio-response")
        if audio_input:
            await audio_input.fill(captcha_text)
            await asyncio.sleep(1.0)

            verify_btn = await bframe.query_selector("#recaptcha-verify-button")
            if verify_btn:
                await verify_btn.click()
                await page.wait_for_timeout(3500)
                
                # التحقق مما إذا ظهرت رسالة خطأ بعد إدخال الصوت
                error_msg = await bframe.query_selector(".rc-audiochallenge-error-message")
                if error_msg and await error_msg.is_visible():
                    logging.error("الرد الصوتي غير صحيح أو تم رفضه.")
                    return False
                    
                return True

    except sr.UnknownValueError:
        logging.error("لم يتمكن النظام من فهم الصوت (قد يكون مشوشاً جداً).")
    except Exception as e:
        logging.error(f"خطأ غير متوقع في حل الكابتشا الصوتي: {e}")
    
    return False

# ================= أوامر البوت =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("فحص مفتاح الAi")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "🚀 البوت الذكي جاهز (مدعوم بنظام التخطي الصوتي).\nأرسل عدد الأكواد المطلوبة لاستخراجها:",
        reply_markup=reply_markup
    )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    if text == "فحص مفتاح الAi":
        if not GEMINI_API_KEY:
            await update.message.reply_text("❌ متغير البيئة GEMINI_API_KEY غير موجود أو فارغ في منصة الاستضافة.")
            return
        if not ai_client:
            await update.message.reply_text("❌ فشل تهيئة عميل Gemini.")
            return
        
        checking_msg = await update.message.reply_text("🔍 جاري فحص الاتصال بمفتاح جمناي...")
        try:
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Say 'CONNECTED'",
            )
            if response and response.text:
                await checking_msg.edit_text(f"✅ مفتاح Gemini يعمل بكفاءة ومتصل بنجاح!\nرد النموذج التجريبي: {response.text.strip()}")
            else:
                await checking_msg.edit_text("⚠️ المفتاح متصل ولكن لم يتم استلام رد صحيح من النموذج.")
        except Exception as e:
            await checking_msg.edit_text(f"❌ فشل الاتصال بمفتاح جمناي:\n{e}")
        return

    if not text.isdigit():
        return

    count = int(text)
    status_msg = await update.message.reply_text(f"⚡ جاري بدء العمل واستخراج {count} كود...")

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

                shot2 = "step_2_submitted.png"
                await page.screenshot(path=shot2, full_page=True)
                with open(shot2, "rb") as photo:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"✉️ الخطوة 2 (طلب {i+1}): إدخال الإيميل وإرسال الطلب.")

                # النقر على مربع ريكابتشا الأساسي
                try:
                    recaptcha_frame = None
                    for frame in page.frames:
                        if "anchor" in frame.url:
                            recaptcha_frame = frame
                            break

                    if recaptcha_frame:
                        checkbox = await recaptcha_frame.wait_for_selector("#recaptcha-anchor", timeout=4000)
                        if checkbox:
                            await checkbox.click()
                            await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"مربع التحقق غير موجود (قد يكون تم التخطي تلقائياً): {e}")

                # معالجة الكابتشا وتحدي الصوت
                max_captcha_rounds = 3
                for round_num in range(max_captcha_rounds):
                    bframe = None
                    for frame in page.frames:
                        if "bframe" in frame.url:
                            bframe = frame
                            break

                    is_captcha_active = False
                    if bframe:
                        try:
                            payload = await bframe.query_selector(".rc-imageselect-payload, .rc-audiochallenge-payload")
                            if payload and await payload.is_visible():
                                is_captcha_active = True
                        except:
                            pass

                    if not is_captcha_active:
                        break

                    await context.bot.send_message(chat_id=chat_id, text=f"🤖 ظهرت الكابتشا (الجولة {round_num + 1})، جاري التخطي الصوتي...")

                    audio_solved = await solve_captcha_via_free_audio(page, bframe, chat_id, context)
                    
                    if audio_solved:
                        # التأكد من اختفاء إطار الكابتشا
                        await page.wait_for_timeout(2000)
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
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم يتم قبول الحل في الجولة {round_num + 1}، جاري إعادة المحاولة...")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم حل الكابتشا بنجاح في الجولة {round_num + 1}!")
                            break
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ فشل الحل الصوتي في الجولة {round_num + 1}، جاري إعادة المحاولة...")

                # التقاط صورة للنتيجة النهائية
                shot3 = f"step_3_result_{i+1}.png"
                await page.screenshot(path=shot3, full_page=True)
                with open(shot3, "rb") as photo:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🎯 نتيجة الطلب رقم {i+1}:")

                # استخراج الأكواد
                try:
                    extracted_values = await page.evaluate("""() => {
                        const inputs = document.querySelectorAll('input[type="text"], input:not([type]), textarea');
                        let values = [];
                        inputs.forEach(el => {
                            if (el.value && el.value.trim().length > 3 && !el.value.includes('@')) {
                                values.push(el.value.trim());
                            }
                        });
                        return values;
                    }""")
                    
                    for val in extracted_values:
                        if val not in all_extracted_codes and SITE_URL not in val:
                            all_extracted_codes.append(val)
                except Exception as e:
                    print(f"خطأ في استخراج الكود من الحقول: {e}")

                await asyncio.sleep(2)

            if all_extracted_codes:
                final_text = "\n".join(all_extracted_codes)
                await context.bot.send_message(chat_id=TARGET_CHANNEL_ID, text=f"🚀 الأكواد المستخرجة:\n{final_text}")
                await status_msg.edit_text(f"✅ تمت العملية بنجاح وتم إرسال {len(all_extracted_codes)} كود إلى قناتك!")
            else:
                await status_msg.edit_text(f"✅ انتهت العملية، يرجى مراجعة الصور المرسلة للتأكد من النتيجة.")
                
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
