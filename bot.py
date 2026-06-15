```python
import logging
import os
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from threading import Thread

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from yt_dlp import YoutubeDL
from shazamio import Shazam

# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# =========================
# FLASK KEEP ALIVE
# =========================

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# =========================
# DATABASE
# =========================

DB_FILE = "users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        scans INTEGER DEFAULT 3
    )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================
# THREAD POOL
# =========================

executor = ThreadPoolExecutor(max_workers=2)

# =========================
# START COMMAND
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "🚀 Welcome!\n\n"
        "Send me:\n"
        "1. A video link → I will download MP4\n"
        "2. Audio/voice/video → I will identify song"
    )

    await update.message.reply_text(text)

# =========================
# STATUS COMMAND
# =========================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT scans FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cursor.fetchone()

    conn.close()

    if row:
        scans = row[0]
    else:
        scans = 3

    await update.message.reply_text(
        f"🎵 Remaining free scans: {scans}"
    )

# =========================
# DOWNLOAD FUNCTION
# =========================

def download_video(url):

    ydl_opts = {
        "format": "mp4",
        "outtmpl": "%(title)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
    }

    with YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(url, download=True)

        filename = ydl.prepare_filename(info)

        return filename

# =========================
# HANDLE LINKS
# =========================

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if "http://" not in text and "https://" not in text:
        await update.message.reply_text(
            "❌ Send valid link."
        )
        return

    status_msg = await update.message.reply_text(
        "📥 Downloading video..."
    )

    try:

        loop = asyncio.get_event_loop()

        filename = await loop.run_in_executor(
            executor,
            download_video,
            text
        )

        if not os.path.exists(filename):
            raise Exception("Downloaded file not found.")

        await status_msg.edit_text(
            "🚀 Uploading to Telegram..."
        )

        with open(filename, "rb") as f:

            await update.message.reply_video(
                video=f,
                caption="✅ Download completed!"
            )

        os.remove(filename)

        await status_msg.delete()

    except Exception as e:

        logging.error(str(e))

        await status_msg.edit_text(
            f"❌ Error:\n{str(e)}"
        )

# =========================
# SONG IDENTIFIER
# =========================

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT scans FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cursor.fetchone()

    if row:
        scans = row[0]
    else:
        scans = 3

        cursor.execute(
            "INSERT INTO users (user_id, scans) VALUES (?, ?)",
            (user_id, scans)
        )

        conn.commit()

    if scans <= 0:

        conn.close()

        await update.message.reply_text(
            "❌ Free scans finished."
        )

        return

    scans -= 1

    cursor.execute(
        "UPDATE users SET scans=? WHERE user_id=?",
        (scans, user_id)
    )

    conn.commit()

    conn.close()

    status_msg = await update.message.reply_text(
        "🔍 Identifying song..."
    )

    try:

        audio_obj = (
            update.message.audio
            or update.message.voice
            or update.message.video
        )

        tg_file = await context.bot.get_file(
            audio_obj.file_id
        )

        local_file = f"{user_id}.ogg"

        await tg_file.download_to_drive(local_file)

        shazam = Shazam()

        result = await shazam.recognize(local_file)

        if result.get("track"):

            title = result["track"]["title"]
            artist = result["track"]["subtitle"]

            await status_msg.edit_text(
                f"🎵 Song Found!\n\n"
                f"Title: {title}\n"
                f"Artist: {artist}\n\n"
                f"Remaining scans: {scans}"
            )

        else:

            await status_msg.edit_text(
                "❌ Song not found."
            )

        if os.path.exists(local_file):
            os.remove(local_file)

    except Exception as e:

        logging.error(str(e))

        await status_msg.edit_text(
            f"❌ Error:\n{str(e)}"
        )

# =========================
# MAIN
# =========================

if __name__ == "__main__":

    BOT_TOKEN = os.environ.get("BOT_TOKEN")

    if not BOT_TOKEN:

        print("BOT_TOKEN missing!")
        exit()

    keep_alive()

    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CommandHandler("status", status)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.AUDIO
            | filters.VOICE
            | filters.VIDEO,
            handle_audio
        )
    )

    print("🚀 Bot started!")

    telegram_app.run_polling()
```
