import logging
import random
import string
import asyncio
import os
import json
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
from google import genai
from google.genai import types

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

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

async def solve_captcha_with_gemini(image_path: str, total_tiles: int) -> list:
    """تحليل بصري ذكي وعالي الدقة لتحديد مربعات الكابتشا المطلوبة بدقة مذهلة"""
    if not ai_client:
        logging.error("مفتاح جمناي غير متوفر!")
        return []
    
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        grid_desc = "3x3 grid (9 tiles total: 1,2,3 top row; 4,5,6 middle row; 7,8,9 bottom row)" if total_tiles == 9 else f"{total_tiles} tiles grid row by row from top-left to bottom-right."

        prompt = (
            f"You are an elite, world-class AI computer vision model specialized in solving Google reCAPTCHA v2 challenges with 100% precision. "
            f"This image is a {grid_desc}. "
            "CRITICAL INSTRUCTIONS: Read the target object specified at the top very carefully (e.g., 'bicycles', 'a bus', 'a fire hydrant', 'crosswalks', 'traffic lights', 'motorcycles'). "
            "Examine every single tile with extreme scrutiny. Look at edges, corners, reflections, and small parts of the object. "
            "Rule 1: If ANY part of the requested object appears in a tile, you MUST include that tile number. "
            "Rule 2: Do not miss any matching tile, as missing even one tile causes failure. "
            "Rule 3: Do not include tiles that do not contain the object. "
            f"Return ONLY a valid JSON list of integers representing the correct tile numbers between 1 and {total_tiles}, for example: [2, 5, 8]. "
            "Do not include any extra text, explanations, or markdown formatting, just the raw JSON list."
        )

        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                prompt
            ],
        )
        
        text_res = response.text.strip()
        if "```" in text_res:
            text_res = text_res.replace("```json", "").replace("```", "").strip()
            
        start = text_res.find("[")
        end = text_res.rfind("]") + 1
        if start != -1 and end != -1:
            tiles = json.loads(text_res[start:end])
            return [int(t) for t in tiles if 1 <= t <= total_tiles]
    except Exception as e:
        logging.error(f"خطأ أثناء حل الكابتشا بواسطة جمناي: {e}")
    
    return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("فحص مفتاح الAi")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "🚀 البوت الذكي المتطور (مدعوم بـ Google Gemini) جاهز.\nاختر 'فحص مفتاح الAi' للتأكد من عمله، أو أرسل عدد الأكواد المطلوبة:",
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
    
    # فحص ذكي مسبق للاتصال قبل بدء العملية
    if not ai_client:
        await update.message.reply_text("❌ عذراً، لا يمكن بدء العمل لأن مفتاح الـ AI غير متصل أو غير مُعرّف بشكل صحيح!")
        return

    status_msg = await update.message.reply_text(f"⚡ جاري بدء العمل واستخراج {count} كود عبر جمناي...")

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
                    print(f"مربع التحقق غير موجود: {e}")

                max_captcha_rounds = 10
                for round_num in range(max_captcha_rounds):
                    bframe = None
                    for frame in page.frames:
                        if "bframe" in frame.url:
                            bframe = frame
                            break

                    is_captcha_active = False
                    if bframe:
                        try:
                            payload = await bframe.query_selector(".rc-imageselect-payload")
                            if payload and await payload.is_visible():
                                is_captcha_active = True
                        except:
                            pass

                    if not is_captcha_active:
                        break

                    await context.bot.send_message(chat_id=chat_id, text=f"🤖 ظهرت صور الكابتشا (الجولة {round_num + 1})، جاري التحليل الفائق...")
                    
                    captcha_element = await page.query_selector("iframe[src*='bframe']")
                    gemini_img_path = f"captcha_crop_{round_num}.png"
                    
                    box = None
                    if captcha_element:
                        box = await captcha_element.bounding_box()
                        if box:
                            await page.screenshot(path=gemini_img_path, clip={
                                'x': box['x'],
                                'y': box['y'],
                                'width': box['width'],
                                'height': box['height']
                            })
                        else:
                            await captcha_element.screenshot(path=gemini_img_path)
                    else:
                        await page.screenshot(path=gemini_img_path)

                    with open(gemini_img_path, "rb") as photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🔍 الكابتشا المطلوب تحليلها (الجولة {round_num + 1}):")

                    tiles = await bframe.query_selector_all(".rc-imageselect-tile")
                    total_tiles = len(tiles) if tiles else 9

                    correct_boxes = await solve_captcha_with_gemini(gemini_img_path, total_tiles)
                    await context.bot.send_message(chat_id=chat_id, text=f"🧠 تحليل Gemini للمربعات الصحيحة: {correct_boxes}")

                    try:
                        for box_num in correct_boxes:
                            if tiles and box_num <= len(tiles):
                                await tiles[box_num - 1].click()
                                await asyncio.sleep(random.uniform(0.6, 1.2))
                        
                        await asyncio.sleep(1.0)

                        selection_shot_path = f"captcha_selected_{round_num}.png"
                        if captcha_element and box:
                            await page.screenshot(path=selection_shot_path, clip={
                                'x': box['x'],
                                'y': box['y'],
                                'width': box['width'],
                                'height': box['height']
                            })
                        else:
                            await page.screenshot(path=selection_shot_path)
                        
                        with open(selection_shot_path, "rb") as photo:
                            await context.bot.send_photo(
                                chat_id=chat_id, 
                                photo=photo, 
                                caption=f"☑️ المربعات التي تم النقر عليها (الجولة {round_num + 1}): {correct_boxes}"
                            )

                        await asyncio.sleep(random.uniform(1.0, 1.5))

                        action_btn = await bframe.query_selector("#recaptcha-verify-button, button:has-text('VERIFY'), button:has-text('NEXT')")
                        if action_btn:
                            await action_btn.click()
                            await page.wait_for_timeout(4000)
                        
                        # فحص ما إذا تم تجاوز الكابتشا أم تكررت الصورة
                        await page.wait_for_timeout(2000)
                        still_active = False
                        for frame in page.frames:
                            if "bframe" in frame.url:
                                try:
                                    p_load = await frame.query_selector(".rc-imageselect-payload")
                                    if p_load and await p_load.is_visible():
                                        still_active = True
                                except:
                                    pass

                        if still_active:
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ لم يتم قبول الحل في الجولة {round_num + 1} وتكررت الصور، جاري إعادة المحاولة بمجموع جديدة...")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم حل الكابتشا بنجاح في الجولة {round_num + 1}!")
                            break

                    except Exception as e:
                        print(f"خطأ أثناء النقر على المربعات أو زر التأكيد: {e}")

                shot3 = f"step_3_result_{i+1}.png"
                await page.screenshot(path=shot3, full_page=True)
                with open(shot3, "rb") as photo:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"🎯 نتيجة الطلب رقم {i+1}:")

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
