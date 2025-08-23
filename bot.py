import os
import requests
import logging
import asyncio
import uuid
import tempfile
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from pydub import AudioSegment
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

class MediaBot:
    def __init__(self):
        load_dotenv()
        self.setup_config()
        self.setup_logging()
        self.setup_ffmpeg()
        
    def setup_config(self):
        """Load and validate environment variables"""
        self.telegram_token = os.getenv("TELEGRAM_TOKEN")
        self.audd_token = os.getenv("AUDD_API_TOKEN")
        self.allowed_chats = self._parse_allowed_chats()
        self.max_seconds = int(os.getenv("MAX_SECONDS", 30))
        self.ffmpeg_path = os.getenv("FFMPEG_BINARY", "ffmpeg")
        
        if not self.telegram_token or not self.audd_token:
            raise ValueError("TELEGRAM_TOKEN and AUDD_API_TOKEN must be set in .env")
            
    def _parse_allowed_chats(self):
        """Parse allowed chat IDs"""
        chats = os.getenv("ALLOWED_CHATS", "")
        if not chats:
            return []
        return [int(chat.strip()) for chat in chats.split(",") if chat.strip().lstrip('-').isdigit()]
    
    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
    def setup_ffmpeg(self):
        """Configure FFmpeg"""
        try:
            AudioSegment.converter = self.ffmpeg_path
            AudioSegment.ffmpeg = self.ffmpeg_path
            AudioSegment.ffprobe = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
            
            # Test FFmpeg
            test_audio = AudioSegment.silent(duration=100)
            test_file = "test.mp3"
            test_audio.export(test_file, format="mp3")
            if os.path.exists(test_file):
                os.remove(test_file)
            print("✅ FFmpeg working")
        except Exception as e:
            print(f"⚠️ FFmpeg issue: {e} - Music recognition may be limited")
    
    def is_authorized(self, chat_id):
        """Check if chat is authorized"""
        return not self.allowed_chats or chat_id in self.allowed_chats
    
    async def process_audio_for_recognition(self, input_path, output_path):
        """Optimize audio for music recognition"""
        try:
            audio = AudioSegment.from_file(input_path)
            
            # Take middle section (usually has chorus)
            if len(audio) > self.max_seconds * 1000:
                start = (len(audio) - self.max_seconds * 1000) // 2
                audio = audio[start:start + self.max_seconds * 1000]
            
            # Optimize: mono, normalize, 44.1kHz
            audio = audio.set_channels(1).normalize().set_frame_rate(44100)
            audio.export(output_path, format="mp3", bitrate="192k")
            return True
        except Exception as e:
            self.logger.error(f"Audio processing failed: {e}")
            return False

    async def recognize_music(self, audio_path):
        """Send audio to AudD API for recognition"""
        try:
            with open(audio_path, "rb") as f:
                response = requests.post(
                    "https://api.audd.io/",
                    data={"api_token": self.audd_token, "return": "spotify,apple_music,deezer"},
                    files={"file": f},
                    timeout=45
                )
            
            if response.status_code != 200:
                return f"⚠️ Recognition service error (HTTP {response.status_code})"
            
            result = response.json()
            
            if result.get("status") == "success" and result.get("result"):
                return self._format_music_result(result["result"])
            else:
                return ("😅 **Song not recognized**\n\n"
                       "💡 Try: clearer audio, popular songs, chorus section")
                       
        except Exception as e:
            self.logger.error(f"Music recognition failed: {e}")
            return "⚠️ Recognition failed. Please try again."
    
    def _format_music_result(self, song):
        """Format music recognition result"""
        title = song.get("title", "Unknown")
        artist = song.get("artist", "Unknown")
        album = song.get("album", "")
        
        reply = f"🎵 **{title}**\n👨‍🎤 **{artist}**"
        if album:
            reply += f"\n💿 *{album}*"
        
        # Add streaming links
        links = []
        if song.get("spotify", {}).get("external_urls", {}).get("spotify"):
            links.append(f"🎧 [Spotify]({song['spotify']['external_urls']['spotify']})")
        if song.get("apple_music", {}).get("url"):
            links.append(f"🍎 [Apple Music]({song['apple_music']['url']})")
        if song.get("deezer", {}).get("link"):
            links.append(f"🎼 [Deezer]({song['deezer']['link']})")
            
        if links:
            reply += "\n\n" + "\n".join(links)
        else:
            reply += f"\n\n🔍 Search: `{title} {artist}`"
            
        return reply

    async def download_media(self, url, progress_callback=None):
        """Download media from supported platforms"""
        # Platform-specific configs
        configs = {
            "instagram.com": {
                "format": "best[ext=mp4]/best[height<=720]/best",
                "http_headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            },
            "tiktok.com": {
                "format": "best[ext=mp4]/best"
            },
            "youtube": {  # default for youtube
                "format": "best[ext=mp4][filesize<100M]/best[filesize<100M]",
                "http_headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}}
            }
        }
        
        # Select config
        config = configs["youtube"]  # default
        for platform in configs:
            if platform in url:
                config = configs[platform]
                break
        
        ydl_opts = {
            **config,
            "outtmpl": f"downloads/%(title).50s-{uuid.uuid4().hex[:8]}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 60,
        }
        
        if progress_callback:
            ydl_opts["progress_hooks"] = [progress_callback]
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)
        except Exception as e:
            # Try audio-only fallback
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

    # Event Handlers
    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle audio/voice messages for music recognition"""
        if not self.is_authorized(update.message.chat_id):
            await update.message.reply_text("⚠️ Unauthorized chat")
            return
            
        status_msg = await update.message.reply_text("🎵 Processing audio...")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Get file
                if update.message.voice:
                    file = await update.message.voice.get_file()
                    ext = ".ogg"
                elif update.message.audio:
                    file = await update.message.audio.get_file()
                    ext = ".mp3"
                elif update.message.video_note:
                    file = await update.message.video_note.get_file()
                    ext = ".mp4"
                elif update.message.document and update.message.document.mime_type.startswith("audio/"):
                    file = await update.message.document.get_file()
                    ext = ".mp3"
                else:
                    await status_msg.edit_text("⚠️ Please send audio/voice message")
                    return
                
                # Process files
                original_path = os.path.join(temp_dir, f"audio{ext}")
                processed_path = os.path.join(temp_dir, "processed.mp3")
                
                await file.download_to_drive(original_path)
                await status_msg.edit_text("🔄 Processing audio...")
                
                if not await self.process_audio_for_recognition(original_path, processed_path):
                    await status_msg.edit_text("⚠️ Audio processing failed")
                    return
                
                await status_msg.edit_text("🔍 Recognizing music...")
                result = await self.recognize_music(processed_path)
                await status_msg.edit_text(result, parse_mode='Markdown', disable_web_page_preview=True)
                
            except Exception as e:
                self.logger.error(f"Media handling failed: {e}")
                await status_msg.edit_text("⚠️ Processing failed")

    async def handle_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle media download links"""
        if not self.is_authorized(update.message.chat_id):
            return
            
        url = update.message.text.strip()
        if not any(domain in url for domain in ["instagram.com", "youtu.be", "youtube.com", "tiktok.com"]):
            return
        
        status_msg = await update.message.reply_text("📥 Downloading...")
        
        def progress_hook(d):
            if d['status'] == 'finished':
                asyncio.create_task(status_msg.edit_text("✅ Upload to Telegram..."))
        
        try:
            file_path = await self.download_media(url, progress_hook)
            
            if os.path.exists(file_path):
                file_size_mb = os.path.getsize(file_path) / 1024 / 1024
                
                if file_size_mb > 50:
                    await status_msg.edit_text(f"⚠️ File too large ({file_size_mb:.1f}MB)")
                    return
                
                with open(file_path, "rb") as f:
                    if file_path.endswith('.mp4'):
                        await update.message.reply_video(f, supports_streaming=True)
                    else:
                        await update.message.reply_audio(f)
                
                os.remove(file_path)
                await status_msg.delete()
            else:
                raise Exception("File not found")
                
        except Exception as e:
            error_msg = "⚠️ **Download failed**"
            if "youtube" in url.lower() and ("bot" in str(e).lower() or "sign in" in str(e).lower()):
                error_msg += "\n\n🤖 **YouTube Anti-Bot Detection**\nTry: different video, update yt-dlp, or use cookies"
            await status_msg.edit_text(error_msg, parse_mode='Markdown')

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        welcome = (
            "👋 **Media Bot**\n\n"
            "🎵 **Music Recognition**: Send voice/audio\n"
            "📥 **Downloader**: Send YouTube/Instagram/TikTok links\n\n"
            "Commands: /help /status"
        )
        await update.message.reply_text(welcome, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = (
            "🆘 **Help**\n\n"
            "**Music Recognition:**\n"
            "• Send voice messages, audio files\n"
            "• Works best with clear, popular songs\n"
            "• Try chorus sections\n\n"
            "**Media Downloader:**\n"
            "• YouTube, Instagram, TikTok links\n"
            "• Paste URL and wait\n\n"
            "**Tips:**\n"
            "• Update regularly: `pip install -U yt-dlp`\n"
            "• For YouTube issues, try different videos"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Status command handler"""
        status = (
            f"🤖 **Bot Status**\n\n"
            f"✅ Running\n"
            f"🎵 Music: {'✅' if self.audd_token else '❌'}\n"
            f"📥 Downloads: ✅\n"
            f"🔐 Restricted: {'Yes' if self.allowed_chats else 'No'}\n"
            f"⏱ Max duration: {self.max_seconds}s"
        )
        await update.message.reply_text(status, parse_mode='Markdown')

    def run(self):
        """Start the bot"""
        print("🚀 Starting bot...")
        app = Application.builder().token(self.telegram_token).build()
        
        # Add handlers
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(MessageHandler(
            filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, 
            self.handle_media
        ))
        app.add_handler(MessageHandler(
            filters.TEXT & filters.Regex("(instagram.com|youtu.be|youtube.com|tiktok.com)"), 
            self.handle_links
        ))
        
        print(f"✅ Bot running | Restricted: {'Yes' if self.allowed_chats else 'No'}")
        app.run_polling()

if __name__ == "__main__":
    try:
        bot = MediaBot()
        bot.run()
    except Exception as e:
        print(f"❌ Failed to start: {e}")