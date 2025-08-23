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
import tempfile
import shutil

load_dotenv()

# ensure downloads dir exists
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# Load environment variables
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS", "").split(",") if os.getenv("ALLOWED_CHATS") else []
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
MAX_SECONDS = int(os.getenv("MAX_SECONDS", 30))  # Increased for better recognition
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")

if not TELEGRAM_TOKEN or not AUDD_API_TOKEN:
    raise ValueError("TELEGRAM_TOKEN and AUDD_API_TOKEN must be set in the .env file.")

if ALLOWED_CHATS:
    try:
        ALLOWED_CHATS = [int(chat_id.strip()) for chat_id in ALLOWED_CHATS if chat_id.strip().lstrip('-').isdigit()]
    except ValueError:
        raise ValueError("ALLOWED_CHATS must be a comma-separated list of valid chat IDs.")

# Test FFmpeg availability
try:
    AudioSegment.converter = FFMPEG_BINARY
    AudioSegment.ffmpeg = FFMPEG_BINARY
    AudioSegment.ffprobe = FFMPEG_BINARY.replace("ffmpeg", "ffprobe")
    # Test with a dummy conversion
    test_audio = AudioSegment.silent(duration=100)  # 100ms of silence
    test_audio.export("test.mp3", format="mp3")
    if os.path.exists("test.mp3"):
        os.remove("test.mp3")
    print("✅ FFmpeg is working correctly")
except Exception as e:
    print(f"❌ FFmpeg test failed: {e}")
    raise ValueError(f"FFMPEG not working properly. Error: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------- Error handler ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ An error occurred, please try again later.")
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

# ---------------- Debug catch-all ----------------
async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("📩 Raw update: %s", update.to_dict())

# ---------------- Improved Audio Processing ----------------
def process_audio_for_recognition(input_path: str, output_path: str) -> bool:
    """
    Process audio file for better music recognition.
    Returns True if successful, False otherwise.
    """
    try:
        # Load audio
        audio = AudioSegment.from_file(input_path)
        
        # Limit duration but take from the middle for better recognition
        duration_ms = len(audio)
        max_duration_ms = MAX_SECONDS * 1000
        
        if duration_ms > max_duration_ms:
            # Take from the middle of the track (often has the chorus)
            start_time = (duration_ms - max_duration_ms) // 2
            audio = audio[start_time:start_time + max_duration_ms]
            logger.info(f"Trimmed audio from {duration_ms}ms to {len(audio)}ms (middle section)")
        
        # Optimize for recognition
        # Normalize volume
        audio = audio.normalize()
        
        # Convert to mono (music recognition works better with mono)
        if audio.channels > 1:
            audio = audio.set_channels(1)
            logger.info("Converted to mono")
        
        # Set optimal sample rate for music recognition (44.1kHz or 22kHz)
        if audio.frame_rate != 44100:
            audio = audio.set_frame_rate(44100)
            logger.info(f"Resampled to 44.1kHz")
        
        # Export with optimal settings for recognition
        audio.export(
            output_path,
            format="mp3",
            bitrate="192k",  # Higher bitrate for better quality
            parameters=["-ac", "1", "-ar", "44100"]  # Force mono, 44.1kHz
        )
        
        logger.info(f"Audio processed successfully: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Audio processing failed: {e}")
        return False

# ---------------- Enhanced Media handler ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    # Check if it's an allowed chat
    if ALLOWED_CHATS and message.chat_id not in ALLOWED_CHATS:
        logger.info(f"Blocked request from unauthorized chat: {message.chat_id}")
        await message.reply_text("⚠️ This bot is restricted to authorized chats only.")
        return

    logger.info(f"Processing media from chat {message.chat_id}, message type: {type(message)}")
    
    # Send initial status
    status_msg = await message.reply_text("🎵 Processing your audio...")

    # Use temporary directory for better file management
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Get the file based on message type
            file = None
            ext = None
            file_name = "audio"
            
            if message.voice:
                file = await message.voice.get_file()
                ext = ".ogg"
                file_name = "voice"
                logger.info("Processing voice message")
            elif message.audio:
                file = await message.audio.get_file()
                ext = ".mp3"
                file_name = "audio"
                logger.info(f"Processing audio file: {message.audio.title or 'unknown'}")
            elif message.video_note:
                file = await message.video_note.get_file()
                ext = ".mp4"
                file_name = "video_note"
                logger.info("Processing video note")
            elif message.document and message.document.mime_type:
                if message.document.mime_type.startswith("audio/"):
                    file = await message.document.get_file()
                    if message.document.file_name:
                        ext = os.path.splitext(message.document.file_name)[1] or ".mp3"
                    else:
                        ext = ".mp3"
                    file_name = "document"
                    logger.info(f"Processing audio document: {message.document.file_name or 'unknown'}")
                else:
                    await status_msg.edit_text("⚠️ Please send an audio file, not a document.")
                    return
            else:
                await status_msg.edit_text("⚠️ Please send me a voice note, audio file, video note, or audio document.")
                return

            if not file:
                await status_msg.edit_text("⚠️ Could not access the file. Please try again.")
                return

            # Create unique filename
            unique_id = uuid.uuid4().hex[:8]
            original_path = os.path.join(temp_dir, f"{file_name}_{unique_id}{ext}")
            processed_path = os.path.join(temp_dir, f"{file_name}_{unique_id}_processed.mp3")

            # Download the file
            await status_msg.edit_text("📥 Downloading audio file...")
            await file.download_to_drive(original_path)
            logger.info(f"Downloaded {file.file_size} bytes to {original_path}")

            # Process audio for recognition
            await status_msg.edit_text("🔄 Processing audio for recognition...")
            if not process_audio_for_recognition(original_path, processed_path):
                await status_msg.edit_text("⚠️ Failed to process audio file. Please try a different format.")
                return

            # Check if processed file exists and has reasonable size
            if not os.path.exists(processed_path):
                await status_msg.edit_text("⚠️ Audio processing failed. Please try again.")
                return

            file_size = os.path.getsize(processed_path)
            if file_size < 1024:  # Less than 1KB is probably an error
                await status_msg.edit_text("⚠️ Processed audio file is too small. Please try a longer audio clip.")
                return

            logger.info(f"Processed audio size: {file_size} bytes")

            # Send to AudD API
            await status_msg.edit_text("🔍 Recognizing song... (this may take a moment)")
            
            try:
                with open(processed_path, "rb") as f:
                    # Prepare the request
                    files = {"file": f}
                    data = {
                        "api_token": AUDD_API_TOKEN, 
                        "return": "apple_music,spotify,deezer,napster,lyrics"  # Added lyrics
                    }
                    
                    logger.info("Sending request to AudD API...")
                    response = requests.post(
                        "https://api.audd.io/",
                        data=data,
                        files=files,
                        timeout=45  # Increased timeout
                    )
                
                logger.info(f"AudD API response - Status: {response.status_code}")
                
                if response.status_code == 429:
                    await status_msg.edit_text("⚠️ Too many requests. Please wait a moment and try again.")
                    return
                elif response.status_code != 200:
                    logger.error(f"AudD API error: {response.status_code} - {response.text}")
                    await status_msg.edit_text(f"⚠️ Music recognition service error (HTTP {response.status_code}). Please try again later.")
                    return
                    
                result = response.json()
                logger.info(f"AudD response: {result}")

                # Parse the result
                if result.get("status") == "success":
                    if result.get("result"):
                        song = result["result"]
                        title = song.get("title", "Unknown Title")
                        artist = song.get("artist", "Unknown Artist")
                        album = song.get("album", "")
                        release_date = song.get("release_date", "")
                        
                        # Format the response
                        reply = f"🎵 **{title}**\n👨‍🎤 **{artist}**"
                        
                        if album:
                            reply += f"\n💿 Album: *{album}*"
                        if release_date:
                            reply += f"\n📅 Released: {release_date}"
                        
                        # Add streaming links if available
                        links = []
                        
                        if song.get("spotify") and song["spotify"].get("external_urls", {}).get("spotify"):
                            links.append(f"🎧 [Spotify]({song['spotify']['external_urls']['spotify']})")
                            
                        if song.get("apple_music") and song["apple_music"].get("url"):
                            links.append(f"🍎 [Apple Music]({song['apple_music']['url']})")
                            
                        if song.get("deezer") and song["deezer"].get("link"):
                            links.append(f"🎼 [Deezer]({song['deezer']['link']})")
                        
                        if links:
                            reply += "\n\n" + "\n".join(links)
                        else:
                            reply += f"\n\n🔍 Search: `{title} {artist}`"
                            
                    else:
                        reply = ("😅 **Song not recognized**\n\n"
                                "💡 **Tips for better recognition:**\n"
                                "• Use a clearer/longer audio clip\n"
                                "• Try popular songs\n"
                                "• Avoid background noise\n"
                                "• Send the chorus part if possible")
                else:
                    # Handle API errors
                    error_info = result.get("error", {})
                    if isinstance(error_info, dict):
                        error_msg = error_info.get("error_message", "Unknown error")
                        error_code = error_info.get("error_code", "N/A")
                        
                        if "insufficient" in error_msg.lower() or "limit" in error_msg.lower():
                            reply = "⚠️ **API limit reached**\n\nThe music recognition service has reached its daily limit. Please try again tomorrow."
                        elif "invalid" in error_msg.lower():
                            reply = "⚠️ **Invalid audio format**\n\nPlease try with a different audio file."
                        else:
                            reply = f"❌ **Recognition failed**\n\nError: {error_msg} (Code: {error_code})"
                    else:
                        reply = f"❌ **Recognition failed**\n\nAPI returned an error. Please try again later."

            except requests.exceptions.Timeout:
                logger.error("AudD API request timed out")
                reply = "⏰ **Request timed out**\n\nThe recognition service is taking too long. Please try again with a shorter audio clip."
            except requests.exceptions.ConnectionError:
                logger.error("AudD API connection failed")
                reply = "🌐 **Connection failed**\n\nCannot connect to the music recognition service. Please check your internet connection and try again."
            except requests.exceptions.RequestException as e:
                logger.error(f"AudD API request failed: {e}")
                reply = "⚠️ **Service unavailable**\n\nThe music recognition service is temporarily unavailable. Please try again later."
            except ValueError as e:  # JSON decode error
                logger.error(f"AudD API returned invalid JSON: {e}")
                reply = "⚠️ **Invalid response**\n\nThe music recognition service returned an invalid response. Please try again."
            except Exception as e:
                logger.error(f"Unexpected error during music recognition: {e}")
                reply = "😅 **Recognition failed**\n\nSomething went wrong. Please try again with a different audio file."

            # Send the result
            try:
                await status_msg.edit_text(reply, parse_mode='Markdown', disable_web_page_preview=True)
                logger.info("Successfully sent recognition result to user")
            except Exception as e:
                logger.error(f"Failed to send result: {e}")
                # Fallback without markdown
                await status_msg.edit_text(reply.replace("*", "").replace("**", ""), disable_web_page_preview=True)

        except Exception as e:
            logger.error(f"Media handling failed: {e}", exc_info=True)
            try:
                await status_msg.edit_text("⚠️ **Processing failed**\n\nSomething went wrong while processing your audio. Please try again.")
            except:
                pass

# ---------------- Enhanced Link handler with better progress ----------------
async def handle_link_simple_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    # Check if it's an allowed chat
    if ALLOWED_CHATS and message.chat_id not in ALLOWED_CHATS:
        logger.info(f"Blocked link request from unauthorized chat: {message.chat_id}")
        await message.reply_text("⚠️ This bot is restricted to authorized chats only.")
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
        "Just paste the link and I'll download it for you! 🚀\n\n"
        "💡 **Tips for better music recognition:**\n"
        "• Use clear audio without background noise\n"
        "• Send the chorus part if possible\n"
        "• Longer clips work better (up to 30 seconds)"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

# ---------------- Help command ----------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 **Help & Commands**\n\n"
        "**📱 Supported Media:**\n"
        "• Voice messages\n"
        "• Audio files (MP3, M4A, OGG, etc.)\n"
        "• Video notes\n"
        "• Audio documents\n\n"
        "**🔗 Supported Platforms:**\n"
        "• YouTube (videos & shorts)\n"
        "• Instagram (posts, reels, stories)\n"
        "• TikTok\n\n"
        "**💡 Tips for Music Recognition:**\n"
        "• Use clear, high-quality audio\n"
        "• Avoid background noise\n"
        "• Send popular/well-known songs\n"
        "• Include the chorus if possible\n"
        "• Try different parts of the song\n\n"
        "**🛠 Troubleshooting:**\n"
        "• If recognition fails, try a longer clip\n"
        "• Ensure the audio is clear and loud\n"
        "• Try popular songs for better results"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ---------------- Status command (for debugging) ----------------
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = (
        "🤖 **Bot Status**\n\n"
        f"✅ Bot is running\n"
        f"🎵 Music Recognition: {'✅ Enabled' if AUDD_API_TOKEN else '❌ No API token'}\n"
        f"📥 Media Downloader: ✅ Enabled\n"
        f"🔧 FFmpeg: ✅ Working\n"
        f"⏱ Max audio duration: {MAX_SECONDS} seconds\n"
        f"🔐 Chat restrictions: {'✅ Enabled' if ALLOWED_CHATS else '❌ Disabled (public)'}"
    )
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ---------------- Main ----------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(instagram.com|youtu.be|youtube.com|tiktok.com)"), handle_link_simple_progress))
    app.add_handler(MessageHandler(filters.ALL, debug_all))
    app.add_error_handler(error_handler)
    
    print("🤖 Bot is running...")
    print("📱 Music recognition enabled")
    print("📥 Media downloader enabled")
    print(f"🔐 Chat restrictions: {'Enabled' if ALLOWED_CHATS else 'Disabled (public)'}")
    print(f"⏱ Max audio duration: {MAX_SECONDS} seconds")
    app.run_polling()

if __name__ == "__main__":
    main()