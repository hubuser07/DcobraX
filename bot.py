import logging
import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from yt_dlp import YoutubeDL
from shazamio import Shazam

# 1. SETUP LOGGING
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# 2. BACKGROUND WORKER POOL
executor = ThreadPoolExecutor(max_workers=4)

# 3. DATABASE SETUP (Persistent file tracking)
DB_FILE = "bot_subscription.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_scans INTEGER DEFAULT 3,
            is_premium INTEGER DEFAULT 0,
            premium_expiry TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ⚠️ ADMIN SETTING: Change 123456789 to your actual personal Telegram User ID!
# (No need to make this an env variable unless you want to, as it's safe to keep here)
ADMIN_ID = 123456789

# 4. TINY FLASK WEB SERVER (Tricks Render to keep the instance alive)
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "DcobraX Bot is running smoothly 24/7!"

def run_flask():
    # Render automatically sets this environment variable port to 8080
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# 5. COMMAND HANDLERS
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"🚀 **Welcome to DcobraX Media Suite, {user_name}!**\n\n"
        "This custom utility was engineered by **@YourTelegramUsername** to give creators "
        "a clean, unified space to manage short-form media and tracking tools.\n\n"
        "📥 **Media Downloader:** Send me any link (YouTube, Insta, TikTok) to download high-quality assets.\n"
        "🎵 **Song Identifier:** Send or forward an audio file/voice note to scan the background track.\n\n"
        "🔹 *Type /status at any time to manage your subscription tier profile.*"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT free_scans, is_premium, premium_expiry FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("⭐ **Account Status:**\n• Free Scans Remaining: 3\n• Tier: Free User")
        return

    free_scans, is_premium, premium_expiry = row
    
    if is_premium and premium_expiry:
        expiry_date = datetime.strptime(premium_expiry, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_date:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_premium = 0, premium_expiry = NULL WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            is_premium = 0

    if is_premium:
        await update.message.reply_text(f"⭐ **Account Status: PREMIUM ACTIVE**\n• Unlimited Audio Scans enabled!\n• Expires on: `{premium_expiry}`")
    else:
        await update.message.reply_text(
            f"📊 **Account Status: FREE TIER**\n• Free Trial Scans Remaining: {free_scans}\n\n"
            "💸 **How to Unlock Premium (2 Months / 150 INR):**\n"
            "1. Message the Admin on Telegram (@YourTelegramUsername) or WhatsApp (+91 XXXXX XXXXX) "
            "with the message: *'Want to unlock Premium Song Finder'*\n\n"
            "2. The Admin will send you a secure Payment QR Code directly.\n\n"
            "3. Once paid, send a screenshot along with your unique User ID:\n"
            f"👉 `{user_id}` 👈 *(Click to copy your ID)*"
        )

async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to execute this command.")
        return

    try:
        target_user_id = int(context.args[0])
        expiry_time = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, free_scans, is_premium, premium_expiry) 
            VALUES (?, 0, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET is_premium=1, premium_expiry=?
        ''', (target_user_id, expiry_time, expiry_time))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Subscription successfully granted to User `{target_user_id}` until {expiry_time}!")
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id, 
                text="🎉 **Payment Received!** Your Premium membership has been activated for 2 months! Enjoy unlimited song identification! 🔥"
            )
        except Exception:
            pass
            
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Incorrect format. Use: `/grant USER_ID`")

# 6. LINK HANDLER FOR MEDIA DOWNLOADS
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if "http://" in user_text or "https://" in user_text:
        keyboard = [
            [InlineKeyboardButton("🎬 Quick Video (No FFmpeg)", callback_data=f"vid_quick|{user_text}")],
            [
                InlineKeyboardButton("🎬 Video 720p", callback_data=f"vid_720|{user_text}"),
                InlineKeyboardButton("🎬 Video 360p", callback_data=f"vid_360|{user_text}")
            ],
            [
                InlineKeyboardButton("🎵 Audio High (320k)", callback_data=f"aud_320|{user_text}"),
                InlineKeyboardButton("🎵 Audio Normal (128k)", callback_data=f"aud_128|{user_text}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select your desired quality format below:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please send me a valid link starting with http:// or https://")

# 7. DOWNLOAD UTILITY
def blocking_download(url, ydl_opts):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# 8. BUTTON CLICK DOWNLOAD RUNNER
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  
    
    quality_choice, url = query.data.split("|", 1)
    status_message = await query.message.reply_text(f"⏳ Starting background process for `{quality_choice}`...")

    if quality_choice == "vid_quick":
        ydl_opts = {'format': 'b[ext=mp4]', 'outtmpl': '%(title)s_%(id)s.%(ext)s', 'max_filesize': 45000000}
        is_video = True
    elif quality_choice == "vid_720":
        ydl_opts = {'format': 'bestvideo[height<=720]+bestaudio/best', 'outtmpl': '%(title)s_%(id)s.%(ext)s', 'max_filesize': 45000000}
        is_video = True
    elif quality_choice == "vid_360":
        ydl_opts = {'format': 'bestvideo[height<=360]+bestaudio/best', 'outtmpl': '%(title)s_%(id)s.%(ext)s', 'max_filesize': 45000000}
        is_video = True
    elif quality_choice == "aud_320":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s_%(id)s.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
        }
        is_video = False
    else:  
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s_%(id)s.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
        }
        is_video = False

    try:
        loop = asyncio.get_event_loop()
        await status_message.edit_text("📥 Extracting and downloading file layers...")
        raw_filename = await loop.run_in_executor(executor, blocking_download, url, ydl_opts)
        
        if is_video:
            final_filename = f"stream_{query.from_user.id}.mp4"
        else:
            final_filename = f"stream_{query.from_user.id}.mp3"

        if not os.path.exists(raw_filename):
            base_path = os.path.splitext(raw_filename)[0]
            for ext in ['.mp4', '.mkv', '.webm', '.mp3', '.opus', '.m4a']:
                if os.path.exists(base_path + ext):
                    raw_filename = base_path + ext
                    break

        if os.path.exists(final_filename):
            os.remove(final_filename)

        if os.path.exists(raw_filename):
            os.rename(raw_filename, final_filename)
        else:
            raise FileNotFoundError("System could not verify downloaded local components.")

        await status_message.edit_text("🚀 Injecting stream to Telegram chat...")
        
        with open(final_filename, 'rb') as f:
            if is_video:
                await query.message.reply_video(video=f, caption="🎬 Your stream download is ready!")
            else:
                await query.message.reply_audio(audio=f, caption="🎵 Your audio track download is ready!")

        await status_message.delete()
        if os.path.exists(final_filename):
            os.remove(final_filename)

    except Exception as e:
        await status_message.edit_text(f"❌ Download failed for this format.\nError: {str(e)}")

# 9. AUDIO PROCESSING (Shazam Implementation)
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    audio_obj = update.message.audio or update.message.voice or update.message.video
    
    if not audio_obj:
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT free_scans, is_premium, premium_expiry FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute("INSERT INTO users (user_id, free_scans, is_premium, premium_expiry) VALUES (?, 3, 0, NULL)", (user_id,))
        conn.commit()
        free_scans, is_premium, premium_expiry = 3, 0, None
    else:
        free_scans, is_premium, premium_expiry = row

    if is_premium and premium_expiry:
        expiry_date = datetime.strptime(premium_expiry, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_date:
            cursor.execute("UPDATE users SET is_premium = 0, premium_expiry = NULL WHERE user_id = ?", (user_id,))
            conn.commit()
            is_premium = 0
            free_scans = 0

    if not is_premium and free_scans <= 0:
        conn.close()
        await update.message.reply_text(
            "❌ **Free Trial Finished!**\n\n"
            "You have used all 3 free song identification scans. "
            "To unlock unlimited scans for **2 full months**, transfer **150 INR** to the Admin "
            f"and send them your User ID: `{user_id}`\n\nType /status for payment info."
        )
        return

    if not is_premium:
        free_scans -= 1
        cursor.execute("UPDATE users SET free_scans = ? WHERE user_id = ?", (free_scans, user_id))
        conn.commit()

    conn.close()

    status_message = await update.message.reply_text("🔍 Analyzing audio acoustic blueprint via Shazam...")
    
    try:
        tg_file = await context.bot.get_file(audio_obj.file_id)
        local_filename = f"scan_{user_id}.ogg"
        await tg_file.download_to_drive(local_filename)
        
        shazam = Shazam()
        result = await shazam.recognize_song(local_filename)
        
        if result.get('track'):
            title = result['track']['title']
            artist = result['track']['subtitle']
            credit_notice = f"\n\n📊 *(Premium Active - Unlimited Scans)*" if is_premium else f"\n\n📊 *(Remaining Free Scans: {free_scans})*"
            await status_message.edit_text(f"🎵 **Song Identified!**\n\n• **Title:** {title}\n• **Artist:** {artist}{credit_notice}")
        else:
            credit_notice = f"\n\n📊 *(Remaining Free Scans: {free_scans})*" if not is_premium else ""
            await status_message.edit_text(f"❌ Analysis complete. Unable to extract match details from this sample audio clip.{credit_notice}")
            
        if os.path.exists(local_filename):
            os.remove(local_filename)
            
    except Exception as e:
        await status_message.edit_text(f"❌ Audio parsing component error: {str(e)}")

# 10. ENGINE BOOT SETUP WITH KEEP ALIVE ACTIVE
if __name__ == '__main__':
    # 🌟 FETCHES TOKEN DYNAMICALLY FROM RENDER ENVIRONMENT BLOCKS
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    
    if not BOT_TOKEN:
        print("🚨 CRITICAL ERROR: BOT_TOKEN environment variable not found on host platform.")
        exit(1)
        
    # Start the tiny heartbeat web server right before launching the bot
    keep_alive()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("grant", grant_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO, handle_audio))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("🚀 Public Core Bot with 24/7 Keep-Alive is operational!")
    app.run_polling()
