import os
import requests
import logging
import time
import asyncio
import uuid
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from pydub import AudioSegment
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

load_dotenv()

# ensure downloads dir exists
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# Load environment variables
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS", "").split(",") if os.getenv("ALLOWED_CHATS") else []
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
MAX_SECONDS = int(os.getenv("MAX_SECONDS", 18))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")

if not TELEGRAM_TOKEN or not AUDD_API_TOKEN:
    raise ValueError("TELEGRAM_TOKEN and AUDD_API_TOKEN must be set in the .env file.")

if ALLOWED_CHATS:
    try:
        ALLOWED_CHATS = [int(chat_id.strip()) for chat_id in ALLOWED_CHATS if chat_id.strip().isdigit()]
    except ValueError:
        raise ValueError("ALLOWED_CHATS must be a comma-separated list of valid chat IDs.")
    
try:
    AudioSegment.converter = FFMPEG_BINARY
    AudioSegment.ffmpeg = FFMPEG_BINARY
    AudioSegment.ffprobe = FFMPEG_BINARY.replace("ffmpeg", "ffprobe")
except OSError:
    raise ValueError(f"FFMPEG not found at {FFMPEG_BINARY}. Please install it or set the correct path in .env.")

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

# ---------------- Media handler (FIXED) ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    logger.info("Got a message of type: %s", type(message))
    
    # Send initial status
    status_msg = await message.reply_text("🎵 Processing your audio...")

    try:
        # Get the file based on message type
        if message.voice:
            file = await message.voice.get_file()
            ext = ".ogg"
            file_name = "voice"
        elif message.audio:
            file = await message.audio.get_file()
            ext = ".mp3"
            file_name = "audio"
        elif message.video_note:
            file = await message.video_note.get_file()
            ext = ".mp4"
            file_name = "video_note"
        elif message.document and message.document.mime_type and message.document.mime_type.startswith("audio/"):
            file = await message.document.get_file()
            # Get extension from mime type or filename
            if message.document.file_name:
                ext = os.path.splitext(message.document.file_name)[1] or ".mp3"
            else:
                ext = ".mp3"
            file_name = "document"
        else:
            await status_msg.edit_text("⚠️ Please send me a voice note, audio file, or video note.")
            return

        # Create unique filename to avoid conflicts
        unique_id = uuid.uuid4().hex[:8]
        original_path = f"downloads/{file_name}_{unique_id}{ext}"
        mp3_path = f"downloads/{file_name}_{unique_id}.mp3"

        # Download the file
        await status_msg.edit_text("📥 Downloading audio file...")
        await file.download_to_drive(original_path)
        logger.info("Downloaded to %s", original_path)

        # Convert to mp3 if needed
        await status_msg.edit_text("🔄 Converting audio format...")
        try:
            if ext.lower() != ".mp3":
                sound = AudioSegment.from_file(original_path)
                # Limit duration to save processing time and API costs
                if len(sound) > MAX_SECONDS * 1000:
                    sound = sound[:MAX_SECONDS * 1000]
                sound.export(mp3_path, format="mp3", bitrate="128k")
                logger.info("Converted to mp3: %s", mp3_path)
                
                # Close the AudioSegment to release file handle
                del sound
                await asyncio.sleep(0.1)  # Small delay to ensure file is released
                
                # Clean up original file
                try:
                    if os.path.exists(original_path):
                        os.remove(original_path)
                except PermissionError:
                    logger.warning("Could not delete original file, will try later")
                    
                audio_file_path = mp3_path
            else:
                audio_file_path = original_path
        except Exception as e:
            logger.error("Audio conversion failed: %s", e)
            await status_msg.edit_text("⚠️ Failed to process audio file. Please try a different format.")
            # Clean up files with better error handling
            await asyncio.sleep(0.5)  # Wait a bit before cleanup
            for path in [original_path, mp3_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except (PermissionError, OSError) as cleanup_error:
                        logger.warning("Could not delete file %s: %s", path, cleanup_error)
            return

        # Send to AudD API
        await status_msg.edit_text("🔍 Recognizing song...")
        try:
            with open(audio_file_path, "rb") as f:
                response = requests.post(
                    "https://api.audd.io/",
                    data={
                        "api_token": AUDD_API_TOKEN, 
                        "return": "apple_music,spotify,deezer,napster"
                    },
                    files={"file": f},
                    timeout=30  # Add timeout
                )
            
            logger.info("AudD status: %s", response.status_code)
            
            if response.status_code != 200:
                raise Exception(f"AudD API returned status {response.status_code}")
                
            result = response.json()
            logger.info("AudD response: %s", result)

            # Parse the result
            if result.get("status") == "success" and result.get("result"):
                song = result["result"]
                title = song.get("title", "Unknown Title")
                artist = song.get("artist", "Unknown Artist")
                album = song.get("album", "")
                
                reply = f"🎵 **{title}** — **{artist}**"
                if album:
                    reply += f"\n💿 Album: {album}"
                
                # Add streaming links
                links_added = False
                if song.get("spotify") and song["spotify"].get("external_urls", {}).get("spotify"):
                    reply += f"\n🎧 [Spotify]({song['spotify']['external_urls']['spotify']})"
                    links_added = True
                    
                if song.get("apple_music") and song["apple_music"].get("url"):
                    reply += f"\n🍎 [Apple Music]({song['apple_music']['url']})"
                    links_added = True
                    
                if song.get("deezer") and song["deezer"].get("link"):
                    reply += f"\n🎼 [Deezer]({song['deezer']['link']})"
                    links_added = True
                
                if not links_added:
                    reply += f"\n\n🔍 Search: `{title} {artist}`"
                    
            else:
                # Check for specific error messages
                if result.get("error"):
                    error_msg = result["error"].get("error_message", "Unknown error")
                    reply = f"😅 Recognition failed: {error_msg}"
                else:
                    reply = "😅 Sorry, I couldn't recognize that song. Try with a clearer audio or a more popular track."

        except requests.RequestException as e:
            logger.error("AudD API request failed: %s", e)
            reply = "⚠️ Music recognition service is temporarily unavailable. Please try again later."
        except Exception as e:
            logger.error("Music recognition failed: %s", e)
            reply = "😅 Sorry, I couldn't recognize that song. Please try again with a different audio file."

        # Send the result
        await status_msg.edit_text(reply, parse_mode='Markdown')
        logger.info("Replied to user with result")

    except Exception as e:
        logger.error("Media handling failed: %s", e)
        await status_msg.edit_text("⚠️ Failed to process your audio. Please try again.")
    
    finally:
        # Clean up downloaded files with better error handling
        await asyncio.sleep(0.5)  # Give time for file handles to be released
        for path in [original_path if 'original_path' in locals() else None, 
                    mp3_path if 'mp3_path' in locals() else None]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info("Cleaned up file: %s", path)
                except (PermissionError, OSError) as e:
                    logger.warning("Could not delete file %s: %s. Will try again later.", path, e)
                    # Try again after a longer delay
                    try:
                        await asyncio.sleep(1.0)
                        os.remove(path)
                        logger.info("Successfully cleaned up file on second attempt: %s", path)
                    except:
                        logger.error("Could not delete file %s even on second attempt", path)

# ---------------- Enhanced Link handler with better progress ----------------
async def handle_link_simple_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not any(domain in url for domain in ["instagram.com", "youtu.be", "youtube.com", "tiktok.com"]):
        return

    status_msg = await message.reply_text("📥 Preparing download...")
    
    progress_data = {
        "percentage": 0, 
        "speed": 0, 
        "status": "starting", 
        "last_update": 0,
        "total_bytes": 0,
        "downloaded_bytes": 0
    }
    
    def progress_hook(d):
        current_time = time.time()
        
        # Log for debugging
        logger.debug(f"Progress hook called with status: {d.get('status')}, data: {d}")
        
        if d['status'] == 'downloading':
            # Update more frequently for better UX
            if current_time - progress_data["last_update"] < 1.0:  # Reduced frequency to avoid rate limits
                return
                
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)
            
            progress_data.update({
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "speed": speed,
                "status": "downloading", 
                "last_update": current_time
            })
            
            if total > 0:
                percentage = (downloaded / total) * 100
                progress_data["percentage"] = percentage
                
                # Create progress bar
                filled = int(20 * percentage / 100)
                bar = "█" * filled + "░" * (20 - filled)
                
                # Format file sizes
                downloaded_mb = downloaded / 1024 / 1024
                total_mb = total / 1024 / 1024
                speed_mb = (speed / 1024 / 1024) if speed else 0
                
                # Create progress text
                progress_text = (
                    f"📥 **Downloading...**\n"
                    f"`[{bar}] {percentage:.1f}%`\n"
                    f"📊 {downloaded_mb:.1f}/{total_mb:.1f} MB\n"
                    f"⚡ Speed: {speed_mb:.1f} MB/s"
                )
                
                # Update message asynchronously
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(safe_edit_message(status_msg, progress_text))
                    logger.info(f"Created progress update task: {percentage:.1f}%")
                except Exception as e:
                    logger.error("Progress update failed: %s", e)
            else:
                # No total size available, show spinner
                spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                spinner = spinner_chars[int(current_time) % len(spinner_chars)]
                
                downloaded_mb = downloaded / 1024 / 1024 if downloaded > 0 else 0
                speed_mb = (speed / 1024 / 1024) if speed else 0
                
                progress_text = (
                    f"📥 **Downloading...** {spinner}\n"
                    f"📊 {downloaded_mb:.1f} MB downloaded\n"
                    f"⚡ Speed: {speed_mb:.1f} MB/s"
                )
                
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(safe_edit_message(status_msg, progress_text))
                except Exception as e:
                    logger.error("Progress update failed: %s", e)
                    
        elif d['status'] == 'finished':
            progress_data["status"] = "finished"
            logger.info("Download finished, updating status message")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(safe_edit_message(status_msg, "✅ **Download completed!** Processing..."))
            except Exception as e:
                logger.error("Finish message update failed: %s", e)

    async def safe_edit_message(msg, text):
        try:
            await msg.edit_text(text, parse_mode='Markdown')
        except Exception as e:
            logger.debug("Message edit failed: %s", e)

    try:
        await status_msg.edit_text("🔍 **Extracting video information...**", parse_mode='Markdown')
        await asyncio.sleep(1)

        # Platform-specific options
        if "instagram.com" in url:
            ydl_opts = {
                "format": "best[ext=mp4]/best[height<=720]/best",
                "outtmpl": f"downloads/%(title).50s-{uuid.uuid4().hex[:8]}.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "noprogress": False,  # Enable progress for our hook
                "progress_hooks": [progress_hook],
                "http_headers": {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                "socket_timeout": 60,
            }
        elif "tiktok.com" in url:
            ydl_opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": f"downloads/%(title).50s-{uuid.uuid4().hex[:8]}.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "noprogress": False,  # Enable progress for our hook
                "progress_hooks": [progress_hook],
                "socket_timeout": 60,
            }
        else:  # YouTube
            ydl_opts = {
                "format": "bestvideo[ext=mp4][filesize<100M]+bestaudio[ext=m4a]/best[ext=mp4][filesize<100M]/best[filesize<100M]",
                "outtmpl": f"downloads/%(title).50s-{uuid.uuid4().hex[:8]}.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "noprogress": False,  # Enable progress for our hook
                "progress_hooks": [progress_hook],
                "socket_timeout": 60,
            }
        
        if os.path.exists("cookies.txt"):
            ydl_opts["cookiefile"] = "cookies.txt"

        await status_msg.edit_text("📥 **Initializing download...**", parse_mode='Markdown')

        def download_video():
            with YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)
                except Exception as e:
                    logger.error("yt-dlp download error: %s", e)
                    raise
        
        loop = asyncio.get_running_loop()
        video_path = await loop.run_in_executor(None, download_video)

        await status_msg.edit_text("📤 **Uploading to Telegram...**", parse_mode='Markdown')
        await asyncio.sleep(0.5)

        if os.path.exists(video_path):
            # Check file size
            file_size = os.path.getsize(video_path)
            file_size_mb = file_size / 1024 / 1024
            
            if file_size_mb > 50:  # Telegram limit
                await status_msg.edit_text(f"⚠️ File too large ({file_size_mb:.1f}MB). Trying to compress or download audio instead...")
                raise Exception("File too large")
            
            with open(video_path, "rb") as f:
                if video_path.endswith('.mp4'):
                    await message.reply_video(f, supports_streaming=True)
                else:
                    await message.reply_document(f)
            
            os.remove(video_path)  # cleanup
            await status_msg.delete()
            logger.info("Successfully sent video to user")
        else:
            raise Exception("Video file not found")

    except Exception as e:
        logger.error("Video download failed: %s", e)
        await status_msg.edit_text("⚠️ **Video failed. Trying audio...**", parse_mode='Markdown')
        await asyncio.sleep(1)

        try:
            # Reset progress for audio download
            progress_data.update({"percentage": 0, "speed": 0, "status": "starting", "last_update": 0})
            
            ydl_opts_audio = {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": f"downloads/%(title).50s-{uuid.uuid4().hex[:8]}.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "noprogress": False,  # Enable progress for our hook
                "progress_hooks": [progress_hook],
                "socket_timeout": 60,
            }
            if os.path.exists("cookies.txt"):
                ydl_opts_audio["cookiefile"] = "cookies.txt"

            def download_audio():
                with YoutubeDL(ydl_opts_audio) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)
            
            audio_path = await loop.run_in_executor(None, download_audio)

            await status_msg.edit_text("📤 **Uploading audio to Telegram...**", parse_mode='Markdown')
            await asyncio.sleep(0.5)

            if os.path.exists(audio_path):
                with open(audio_path, "rb") as f:
                    await message.reply_audio(f)
                os.remove(audio_path)  # cleanup
                await status_msg.delete()
                logger.info("Successfully sent audio to user")
            else:
                raise Exception("Audio file not found")

        except Exception as e2:
            logger.error("Audio download failed: %s", e2)
            error_msg = "⚠️ **Download failed.**\n\n"
            
            if "instagram.com" in url:
                error_msg += (
                    "**Possible reasons:**\n"
                    "• Private account or story\n"
                    "• Content requires login\n"
                    "• Instagram changed their API\n\n"
                    "**Try:** Update with `pip install -U yt-dlp`"
                )
            elif "tiktok.com" in url:
                error_msg += (
                    "**Possible reasons:**\n"
                    "• Video is private or deleted\n"
                    "• TikTok blocked the request\n"
                    "• Try copying the link again"
                )
            else:
                error_msg += (
                    "**Possible reasons:**\n"
                    "• Video is private or deleted\n"
                    "• Region restrictions\n"
                    "• Platform changed their API"
                )
            
            await status_msg.edit_text(error_msg, parse_mode='Markdown')

# ---------------- Start command ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Welcome to Media Bot!**\n\n"
        "**🎵 Music Recognition:**\n"
        "Send me voice notes, audio files, or video notes and I'll identify the song!\n\n"
        "**📥 Media Downloader:**\n"
        "Send me links from:\n"
        "• YouTube\n"
        "• Instagram\n"
        "• TikTok\n\n"
        "Just paste the link and I'll download it for you! 🚀"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

# ---------------- Help command ----------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 **Help & Commands**\n\n"
        "**📱 Supported Media:**\n"
        "• Voice messages\n"
        "• Audio files (MP3, M4A, etc.)\n"
        "• Video notes\n"
        "• Audio documents\n\n"
        "**🔗 Supported Platforms:**\n"
        "• YouTube (videos & shorts)\n"
        "• Instagram (posts, reels, stories)\n"
        "• TikTok\n\n"
        "**💡 Tips:**\n"
        "• For better recognition, use clear audio\n"
        "• Private content might not be downloadable\n"
        "• Large files are automatically compressed"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ---------------- Main ----------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(instagram.com|youtu.be|youtube.com|tiktok.com)"), handle_link_simple_progress))
    app.add_handler(MessageHandler(filters.ALL, debug_all))
    app.add_error_handler(error_handler)
    
    print("🤖 Bot is running...")
    print("📱 Music recognition enabled")
    print("📥 Media downloader enabled")
    app.run_polling()

if __name__ == "__main__":
    main()