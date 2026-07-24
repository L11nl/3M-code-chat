import httpx
import logging
import random
import string
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# ---------- إعدادات البوت والقناة ----------
TOKEN = "2051861765:AAEktLeDoXO57rudwHnxQ5RimkB7Et0XYS8"
TARGET_CHANNEL_ID = -1003642554894  

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

URL = "https://www.bbvadescuentos.mx/admin-site/php/_httprequest.php"
SITE_URL = "https://www.bbvadescuentos.mx/develop/openai-3msc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Origin": "https://www.bbvadescuentos.mx",
    "Referer": SITE_URL,
    "X-Requested-With": "XMLHttpRequest"
}

async def get_fresh_cookies_with_stealth():
    """دالة خلفية لفتح متصفح خفي مخفي البصمة وتجاوز الحماية لجلب كوكيز نظيفة"""
    logging.info("جاري تحديث الجلسة واكتساب كوكيز جديدة عبر المتصفح الخفي...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu"
            ]
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        # تطبيق أدوات التخفي لمنع كشف البوت
        await stealth_async(page)
        
        try:
            await page.goto(SITE_URL, timeout=45000, wait_until="networkidle")
            await page.wait_for_timeout(5000) # انتظار توليد الحماية للكوكيز
            cookies_list = await context.cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies_list}
            await browser.close()
            return cookies_dict
        except Exception as e:
            logging.error(f"فشل جلب الكوكيز عبر المتصفح: {e}")
            await browser.close()
            return None

def generate_random_email():
    chars = string.ascii_lowercase + string.digits
    return f"{''.join(random.choices(chars, k=10))}@gmail.com"

async def fetch_code(client, cookies):
    email = generate_random_email()
    files = {"assignOpenAICode": (None, "true"), "email": (None, email)}
    try:
        response = await client.post(URL, files=files, cookies=cookies, timeout=12.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") == 1:
                return f"https://{data.get('code')}"
    except:
        pass
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚀 **البوت يعمل الآن بسيرفر سحابي آمن**\n\n"
        f"أرسل عدد الأكواد التي تريد استخراجها وسيقوم البوت بالعمل تلقائياً.", 
        parse_mode="Markdown"
    )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        return

    count = int(text)
    status_msg = await update.message.reply_text(f"⚡ جاري إعداد الجلسة الذكية واستخراج {count} كود...")

    # جلب كوكيز طازجة تلقائياً عبر المتصفح الخفي في الخلفية
    cookies = await get_fresh_cookies_with_stealth()
    if not cookies:
        await status_msg.edit_text("❌ فشل الاتصال الأمني بالموقع حالياً، يرجى المحاولة لاحقاً.")
        return

    all_codes = []
    batch_size = 5 
    
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for i in range(0, count, batch_size):
            current_batch = min(batch_size, count - i)
            tasks = [fetch_code(client, cookies) for _ in range(current_batch)]
            
            results = await asyncio.gather(*tasks)
            valid_results = [res for res in results if res]
            
            # إذا انتهت صلاحية الجلسة، يتم تحديثها تلقائياً في الخلفية
            if not valid_results and i == 0:
                cookies = await get_fresh_cookies_with_stealth()
                if cookies:
                    tasks = [fetch_code(client, cookies) for _ in range(current_batch)]
                    results = await asyncio.gather(*tasks)
                    valid_results = [res for res in results if res]

            all_codes.extend(valid_results)
            await asyncio.sleep(1.0)

    if all_codes:
        final_message = "\n".join(all_codes)
        for chunk in [final_message[i:i + 4000] for i in range(0, len(final_message), 4000)]:
            try:
                await context.bot.send_message(chat_id=TARGET_CHANNEL_ID, text=chunk)
            except Exception as e:
                await status_msg.edit_text(f"❌ فشل الإرسال للقناة:\nالخطأ: {e}")
                return

        await status_msg.edit_text(f"✅ تم بنجاح استخراج وإرسال {len(all_codes)} كود إلى قناتك الخاصة.")
    else:
        await status_msg.edit_text("❌ لم يتم استخراج أي كود، يبدو أن الموقع فرض قيوداً مؤقتة.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request))
    
    print("البوت يعمل على السيرفر ومستعد لتلقي الطلبات...")
    app.run_polling()

if __name__ == "__main__":
    main()
