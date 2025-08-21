import os
import requests
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from pydub import AudioSegment
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS", "").split(",") if os.getenv("ALLOWED_CHATS") else []
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
MAX_SECONDS = int(os.getenv("MAX_SECONDS", 18))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")

# Validate required environment variables
if not TELEGRAM_TOKEN or not AUDD_API_TOKEN:
    raise ValueError("TELEGRAM_TOKEN and AUDD_API_TOKEN must be set in the .env file.")

# Validate allowed chats
if ALLOWED_CHATS:
    try:
        ALLOWED_CHATS = [int(chat_id.strip()) for chat_id in ALLOWED_CHATS if chat_id.strip().isdigit()]
    except ValueError:
        raise ValueError("ALLOWED_CHATS must be a comma-separated list of valid chat IDs.")
    
# Ensure FFMPEG is available
try:
    AudioSegment.converter = FFMPEG_BINARY
except OSError:
    raise ValueError(f"FFMPEG not found at {FFMPEG_BINARY}. Please install it or set the correct path in .env.")
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------- Error handler ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    if update and isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred, please try again later.")

# ---------------- Debug catch-all ----------------
async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("📩 Raw update: %s", update.to_dict())

# ---------------- Media handler ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    logger.info("Got a message of type: %s", message)

    if message.voice:
        file = await message.voice.get_file()
        ext = ".ogg"
    elif message.audio:
        file = await message.audio.get_file()
        ext = ".mp3"
    elif message.video_note:
        file = await message.video_note.get_file()
        ext = ".mp4"
    elif message.document and message.document.mime_type.startswith("audio/"):
        file = await message.document.get_file()
        ext = ".mp3"
    else:
        await message.reply_text("⚠️ Please send me a voice note, audio, or video note.")
        return

    ogg_path = "voice" + ext
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    logger.info("Downloaded to %s", ogg_path)

    # convert to mp3
    sound = AudioSegment.from_file(ogg_path)
    sound.export(mp3_path, format="mp3")
    logger.info("Converted to mp3: %s", mp3_path)

    # send to AudD
    with open(mp3_path, "rb") as f:
        response = requests.post(
            "https://api.audd.io/",
            data={"api_token": AUDD_API_TOKEN, "return": "apple_music,spotify"},
            files={"file": f},
        )
    logger.info("AudD status: %s", response.status_code)
    result = response.json()
    logger.info("AudD response: %s", result)

    if result.get("result"):
        song = result["result"]
        reply = f"🎵 {song['title']} — {song['artist']}"
        if "spotify" in song and song["spotify"].get("external_urls"):
            reply += f"\n🔗 {song['spotify']['external_urls']['spotify']}"
    else:
        reply = "😅 Sorry, I couldn’t recognize that song."

    await message.reply_text(reply)
    logger.info("Replied to user.")

# ---------------- Instagram handler ----------------

async def handle_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if "instagram.com" not in url:
        return  # ignore non-IG links

    await message.reply_text("📥 Downloading Instagram video...")

    try:
        ydl_opts = {
            "format": "mp4",
            "outtmpl": "insta.%(ext)s",
            "quiet": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = ydl.prepare_filename(info)

        # Send back video
        with open(video_path, "rb") as f:
            await message.reply_video(f)

        # Cleanup
        os.remove(video_path)

    except Exception as e:
        logger.error("Instagram download failed: %s", e)
        await message.reply_text("⚠️ Failed to download the Instagram video.")


# ---------------- Start command ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a voice note or song file and I’ll try to recognize it!")

# ---------------- Main ----------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # /start command
    app.add_handler(CommandHandler("start", start))

    # Media handler
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO,
        handle_media
    ))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("instagram.com"), handle_instagram))

    # Debug catch-all (remove later)
    app.add_handler(MessageHandler(filters.ALL, debug_all))

    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling()




if __name__ == "__main__":
    main()
