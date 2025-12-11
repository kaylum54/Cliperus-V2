# Cliperus - Intelligent Stream Clipper

Automatically record, clip, and upload your best streaming moments to TikTok.

## 🎯 Features

- **Multi-Platform Support**: Monitor Twitch, YouTube, and Kick streams
- **Auto-Recording**: Automatically start recording when streams go live
- **Smart Clip Detection**: AI-powered triggers for donations, chat spikes, sentiment
- **Segment Management**: Auto-rotate recordings every hour
- **TikTok Auto-Upload**: Automatically upload clips to TikTok accounts
- **OBS Integration**: Full OBS WebSocket support
- **Web Dashboard**: Modern React-based management interface

## 📋 Requirements

- **Python 3.10+**
- **OBS Studio** with WebSocket plugin (v5.0+)
- **FFmpeg** (for video processing)
- Windows 10/11 (for .exe version)

## 🚀 Quick Start

### Option 1: Run from Source (Development)

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/cliperus-app.git
cd cliperus-app
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your credentials
```

5. **Run the application**
```bash
python app.py
```

6. **Open browser**
```
http://localhost:5000
```

### Option 2: Windows Executable

1. Download `Cliperus.exe` from [Releases](../../releases)
2. Double-click to run
3. Open browser to `http://localhost:5000`

## ⚙️ Configuration

### OBS Setup

1. Install [OBS WebSocket plugin](https://github.com/obsproject/obs-websocket/releases)
2. In OBS: Tools > WebSocket Server Settings
3. Enable and set a password
4. In Cliperus: Settings > OBS
   - Host: `localhost`
   - Port: `4455`
   - Password: (your OBS password)

### Platform API Setup

#### Twitch
1. Go to [Twitch Developer Console](https://dev.twitch.tv/console)
2. Register a new application
3. Copy Client ID and Client Secret
4. In Cliperus: Settings > Platforms
   - Enter Twitch Client ID
   - Enter Twitch Client Secret

#### YouTube
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Enable YouTube Data API v3
3. Create API Key
4. In Cliperus: Settings > Platforms
   - Enter YouTube API Key

#### TikTok
1. Register at [TikTok for Developers](https://developers.tiktok.com)
2. Create an app and get OAuth credentials
3. In Cliperus: Settings > TikTok Accounts
   - Add account with credentials

## 📖 Usage

### Adding a Stream

1. Navigate to **Streams** tab
2. Click **Add Stream**
3. Enter:
   - Stream name (e.g., "xQc")
   - Platform (Twitch/YouTube/Kick)
   - Channel URL
   - Enable "Auto-Record"
4. Save

### Creating Triggers

1. Navigate to **Triggers** tab
2. Click **Add Trigger**
3. Configure:
   - Name: "Big Donation"
   - Type: Donation
   - Threshold: $50
   - Clip Duration: 30 seconds
   - Pre-buffer: 10 seconds (capture before)
   - Post-buffer: 5 seconds (capture after)
4. Enable trigger

### Manual Clipping

1. Navigate to **Recordings** tab
2. Find active recording
3. Click **Create Clip**
4. Set start time and duration
5. Clip will be processed automatically

### Auto-Upload to TikTok

1. Enable in Settings > Recording
2. Check "Auto-post to TikTok"
3. Select default TikTok account
4. Clips will auto-upload when ready

## 🔧 Advanced Features

### Segment Rotation

Recordings automatically rotate every hour (configurable):
- Prevents massive file sizes
- Allows parallel clip generation
- Optional auto-delete of long-form videos

### Smart Detection (Experimental)

Enable AI-powered clip detection:
- **Sentiment Analysis**: Detect positive chat reactions
- **Audio Excitement**: Detect voice pitch/volume spikes
- Requires additional setup (see docs)

### Background Workers

Three workers run automatically:
1. **Upload Worker**: Processes TikTok upload queue
2. **Segment Worker**: Rotates recordings hourly
3. **Trigger Worker**: Monitors for clip triggers
4. **Stream Monitor**: Checks stream status every 60s

## 🐛 Troubleshooting

### OBS Won't Connect
- Ensure OBS WebSocket plugin is installed
- Check OBS is running
- Verify password matches
- Try port 4455 (default)

### Streams Not Auto-Recording
- Check Stream Monitor is running (Health page)
- Verify API credentials are correct
- Check stream is actually live
- Enable auto-record on stream settings

### FFmpeg Errors
- Install FFmpeg: https://ffmpeg.org/download.html
- Add to PATH environment variable
- Restart Cliperus

### Clips Not Generating
- Check recordings directory has space
- Verify FFmpeg is working
- Check logs in `logs/cliperus.log`

## 📊 API Endpoints

### Health Check
```
GET /api/health
```

### Streams
```
GET    /api/streams
POST   /api/streams
PUT    /api/streams/{id}
DELETE /api/streams/{id}
GET    /api/streams/{id}/check-live
```

### Recordings
```
GET    /api/recordings
DELETE /api/recordings/{id}
POST   /api/recordings/{id}/generate-clips
```

### Clips
```
GET    /api/clips
POST   /api/clips
DELETE /api/clips/{id}
```

### Uploads
```
GET    /api/uploads
POST   /api/uploads
DELETE /api/uploads/{id}
POST   /api/uploads/{id}/start
```

### Settings
```
GET /api/settings
PUT /api/settings
GET /api/settings/categories
GET /api/settings/recording
PUT /api/settings/recording
```

## 🔐 Security Notes

- Change default SECRET_KEY in production
- Store API keys in environment variables
- Don't commit `.env` file
- Use HTTPS in production
- Enable authentication for production deployments

## 🏗️ Building from Source

### Build Windows Executable

```bash
pip install pyinstaller
pyinstaller --name=Cliperus \
  --onefile \
  --windowed \
  --add-data "client/dist;client/dist" \
  --hidden-import=flask \
  --hidden-import=flask_cors \
  --hidden-import=flask_sqlalchemy \
  --hidden-import=obswebsocket \
  --hidden-import=stream_monitor \
  app.py
```

Output: `dist/Cliperus.exe`

## 📁 Project Structure

```
cliperus/
├── app.py                 # Main application
├── stream_monitor.py      # Stream monitoring module
├── requirements.txt       # Python dependencies
├── .env                   # Environment configuration
├── logs/                  # Application logs
├── recordings/            # Raw recordings storage
├── clips/                 # Generated clips storage
├── client/                # Frontend React app
│   └── dist/              # Built frontend files
└── cliperus.db           # SQLite database
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📝 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- OBS WebSocket team
- FFmpeg developers
- Twitch, YouTube, and Kick APIs
- React and Flask communities

## 📞 Support

- GitHub Issues: [Report bugs](../../issues)
- Documentation: [Full docs](../../wiki)
- Discord: [Community server](#)

## 🗺️ Roadmap

- [ ] Discord notifications
- [ ] YouTube upload support
- [ ] Multi-language support
- [ ] Custom AI models
- [ ] Mobile app
- [ ] Cloud storage integration
- [ ] Advanced analytics dashboard

---

Made with ❤️ for streamers by streamers
