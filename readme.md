🎵📥 Telegram Media Bot
A powerful and simple  Telegram bot that combines music recognition and media downloading capabilities. Send voice messages to identify songs, or paste links to download videos and audio from popular platforms.
✨ Features:
🎵 Music Recognition

Voice Message Recognition - Send voice notes to identify songs
Audio File Support - Upload MP3, M4A, WAV, and other audio formats
Video Note Processing - Extract audio from Telegram video notes
Multiple Streaming Links - Get links to Spotify, Apple Music, Deezer
Fast Processing - Optimized audio conversion and API calls

📥 Media Downloader:

YouTube Support - Download videos, shorts, and audio
Instagram Integration - Download posts, reels, and stories
TikTok Downloads - Save TikTok videos directly
Real-time Progress - Live progress bars in Telegram
Smart Fallback - Auto-switches to audio if video fails
File Size Management - Automatic compression for large files

🛠️ Technical Features:

Async Processing - Non-blocking operations for better performance
Error Recovery - Robust error handling and retry mechanisms
Resource Management - Automatic cleanup of temporary files
Rate Limiting - Respects API limits and Telegram restrictions
Cross-platform - Works on Windows, Linux, and macOS

🚀 Quick Start:
Prerequisites

Python 3.8 or higher
FFmpeg installed on your system
Telegram Bot Token
AudD API Token (for music recognition)

Installation

Clone the repository
bashgit clone https://github.com/yourusername/telegram-media-bot.git
cd telegram-media-bot

Install dependencies
bashpip install -r requirements.txt

Install FFmpeg
Windows:

Download from FFmpeg.org
Add to system PATH

Ubuntu/Debian:
bashsudo apt update
sudo apt install ffmpeg
macOS:
bashbrew install ffmpeg

Set up environment variables
Create a .env file:
envTELEGRAM_TOKEN=your_bot_token_here
AUDD_API_TOKEN=your_audd_token_here
FFMPEG_BINARY=ffmpeg
MAX_SECONDS=30
ALLOWED_CHATS=

Run the bot
bashpython bot.py


🔧 Configuration
Environment Variables
VariableDescriptionDefaultRequiredTELEGRAM_TOKENYour Telegram bot token from @BotFather-✅AUDD_API_TOKENAPI token from AudD.io for music recognition-✅FFMPEG_BINARYPath to FFmpeg executableffmpeg⚠️MAX_SECONDSMaximum audio duration for recognition (seconds)18❌ALLOWED_CHATSComma-separated list of allowed chat IDs (empty = all)``❌
Getting API Tokens
Telegram Bot Token

Message @BotFather on Telegram
Use /newbot command
Follow the setup process
Copy your bot token

AudD API Token

Visit AudD.io
Sign up for a free account
Go to your dashboard
Copy your API token

📱 Usage
Music Recognition

Voice Messages - Record and send a voice note
Audio Files - Upload MP3, M4A, WAV files
Video Notes - Send circular video messages
Audio Documents - Upload audio files as documents

The bot will:

Convert audio to optimal format
Send to AudD recognition service
Return song title, artist, and streaming links

Media Downloads
Simply send a link from supported platforms:
Supported Platforms:

youtube.com / youtu.be - Videos and audio
instagram.com - Posts, reels, stories
tiktok.com - Videos

Example:
https://www.youtube.com/watch?v=dQw4w9WgXcQ
The bot will:

Show download progress in real-time
Upload the media file to Telegram
Fallback to audio if video fails

#-----------------------------------------------------------------------------------------------------------#
**!!!ATTENTION: At the moment youtube downloader is currently unavailalbe for fixing itt on next versions!!!**
#-----------------------------------------------------------------------------------------------------------#

🤖 Commands

/start - Welcome message and bot introduction
/help - Detailed usage instructions and tips

📋 Requirements
Python Packages
python-telegram-bot>=20.0
yt-dlp>=2023.12.30
pydub>=0.25.1
requests>=2.31.0
python-dotenv>=1.0.0
System Requirements

FFmpeg - For audio/video processing
Python 3.8+ - Core runtime
Internet Connection - For API calls and downloads

🔍 Troubleshooting
Common Issues
Music Recognition Not Working

✅ Check AudD API token is valid
✅ Ensure FFmpeg is properly installed
✅ Try with clearer audio samples
✅ Check audio file isn't corrupted

Download Failures

✅ Update yt-dlp: pip install -U yt-dlp
✅ Check if content is private/restricted
✅ Verify internet connection
✅ Try with different video URLs

Progress Bar in Terminal

✅ Check Telegram message edit permissions
✅ Verify bot token is correct
✅ Look for rate limiting issues in logs

File Access Errors (Windows)

✅ Run as administrator if needed
✅ Check antivirus isn't blocking files
✅ Ensure downloads folder has write permissions

Debugging
Enable detailed logging by modifying the logging level:
pythonlogging.basicConfig(level=logging.DEBUG)
🛡️ Security & Privacy

No Data Storage - Files are processed and immediately deleted
Temporary Processing - All downloads use unique temporary names
API Rate Limiting - Respects service limits and quotas
Error Isolation - Errors don't expose sensitive information

📊 Performance

Concurrent Processing - Handles multiple users simultaneously
Memory Efficient - Automatic cleanup prevents memory leaks
Network Optimized - Chunked downloads and progress tracking
Resource Limits - Configurable file size and duration limits

🤝 Contributing

Fork the repository
Create a feature branch (git checkout -b feature/amazing-feature)
Commit your changes (git commit -m 'Add amazing feature')
Push to the branch (git push origin feature/amazing-feature)
Open a Pull Request

Development Setup
bash# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest

# Format code
black bot.py

# Lint code
flake8 bot.py
📝 License
This project is licensed under the MIT License - see the LICENSE file for details.
🙏 Acknowledgments

python-telegram-bot - Telegram Bot API wrapper
yt-dlp - Video downloading library
AudD.io - Music recognition API
pydub - Audio processing library

📞 Support

🐛 Bug Reports: GitHub Issues
💡 Feature Requests: GitHub Discussions
📧 Contact: araad.arrsh@gmail.com


