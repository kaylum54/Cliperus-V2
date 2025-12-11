# Cliperus Deployment Guide

## 🎯 Recommended Services for Building & Deployment

### Option 1: GitHub Actions (Recommended) ⭐

**Best for:** Automated builds, Windows executables, free hosting

#### Setup Steps:

1. **Create GitHub Repository**
```bash
# Initialize git
git init
git add .
git commit -m "Initial commit"

# Create repo on GitHub
# Then push
git remote add origin https://github.com/yourusername/cliperus.git
git branch -M main
git push -u origin main
```

2. **Create `.github/workflows/build.yml`**
```yaml
name: Build Cliperus

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build-windows:
    runs-on: windows-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pyinstaller
    
    - name: Build executable
      run: |
        pyinstaller --name=Cliperus ^
          --onefile ^
          --add-data "client/dist;client/dist" ^
          --hidden-import=flask ^
          --hidden-import=flask_cors ^
          --hidden-import=flask_sqlalchemy ^
          --hidden-import=obswebsocket ^
          --hidden-import=stream_monitor ^
          app.py
    
    - name: Upload artifact
      uses: actions/upload-artifact@v3
      with:
        name: cliperus-windows
        path: dist/Cliperus.exe
    
    - name: Create Release
      if: github.ref == 'refs/heads/main'
      uses: softprops/action-gh-release@v1
      with:
        files: dist/Cliperus.exe
        tag_name: v1.0.${{ github.run_number }}
        name: Release v1.0.${{ github.run_number }}
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

3. **Push and Wait**
- GitHub Actions will automatically build
- Check "Actions" tab in your repo
- Download from "Artifacts" or "Releases"

**Download Link:**
`https://github.com/yourusername/cliperus/releases/latest/download/Cliperus.exe`

---

### Option 2: Replit (For Testing)

**Best for:** Quick testing, online development

#### Setup:
1. Go to https://replit.com
2. Create new Repl → Import from GitHub
3. Connect your repo
4. Replit auto-detects Python
5. Click "Run" to start

**Limitations:**
- Can't build Windows .exe
- Free tier has limited resources
- Better for backend testing

---

### Option 3: Render.com (Backend Hosting)

**Best for:** Hosting the API backend 24/7

#### Setup:

1. **Create `render.yaml`**
```yaml
services:
  - type: web
    name: cliperus-api
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    envVars:
      - key: PORT
        value: 10000
      - key: DATABASE_URL
        sync: false
      - key: SECRET_KEY
        generateValue: true
      - key: TWITCH_CLIENT_ID
        sync: false
      - key: YOUTUBE_API_KEY
        sync: false
```

2. **Deploy:**
   - Sign up at https://render.com
   - New Web Service → Connect GitHub repo
   - Render auto-deploys on push
   - Free tier available

**URL:** `https://cliperus-api.onrender.com`

---

### Option 4: Railway.app (Modern Hosting)

**Best for:** Easy deployment, good free tier

#### Setup:
1. Go to https://railway.app
2. New Project → Deploy from GitHub
3. Connect repo
4. Add environment variables
5. Deploy!

**Features:**
- Automatic HTTPS
- Custom domains
- Database included
- $5 free credit/month

---

### Option 5: Heroku (Classic Choice)

**Best for:** Proven platform, lots of addons

#### Setup:

1. **Create `Procfile`**
```
web: python app.py
```

2. **Create `runtime.txt`**
```
python-3.11.0
```

3. **Deploy:**
```bash
heroku login
heroku create cliperus-app
git push heroku main
heroku config:set SECRET_KEY=your-secret-key
```

---

### Option 6: Local Windows Build

**Best for:** Building .exe on your own machine

#### Requirements:
- Windows 10/11
- Python 3.10+
- Git

#### Steps:

1. **Clone repository**
```bash
git clone https://github.com/yourusername/cliperus.git
cd cliperus
```

2. **Create virtual environment**
```bash
python -m venv venv
venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
pip install pyinstaller
```

4. **Build executable**
```bash
pyinstaller --name=Cliperus ^
  --onefile ^
  --add-data "client/dist;client/dist" ^
  --hidden-import=flask ^
  --hidden-import=flask_cors ^
  --hidden-import=flask_sqlalchemy ^
  --hidden-import=obswebsocket ^
  --hidden-import=stream_monitor ^
  app.py
```

5. **Find executable**
```
dist/Cliperus.exe
```

---

## 🔥 Quick Deploy Comparison

| Service | Cost | Build .exe | API Hosting | Database | Best For |
|---------|------|------------|-------------|----------|----------|
| **GitHub Actions** | Free | ✅ Yes | ❌ No | ❌ No | Building releases |
| **Replit** | Free* | ❌ No | ✅ Yes | ✅ Yes | Testing |
| **Render** | Free* | ❌ No | ✅ Yes | ✅ Yes | Production API |
| **Railway** | $5/mo | ❌ No | ✅ Yes | ✅ Yes | Full stack |
| **Heroku** | $7/mo | ❌ No | ✅ Yes | ✅ Addon | Enterprise |
| **Local Build** | Free | ✅ Yes | ❌ No | ❌ No | Distribution |

\* Free tier with limitations

---

## 🚀 Recommended Workflow

### For Distribution (Windows App):

```
Local Dev → GitHub → GitHub Actions → Release .exe
```

1. Develop locally
2. Push to GitHub
3. Actions builds .exe automatically
4. Users download from Releases page

### For SaaS (Web Service):

```
Local Dev → GitHub → Render/Railway → Production
```

1. Develop locally
2. Push to GitHub
3. Service auto-deploys
4. Users access web interface

---

## 📦 Building for Distribution

### Create Installer (Advanced)

Use **Inno Setup** to create a proper Windows installer:

1. **Download Inno Setup:** https://jrsoftware.org/isdl.php

2. **Create `installer.iss`:**
```iss
[Setup]
AppName=Cliperus
AppVersion=1.0
DefaultDirName={pf}\Cliperus
DefaultGroupName=Cliperus
OutputDir=installer
OutputBaseFilename=CliperusSetup

[Files]
Source: "dist\Cliperus.exe"; DestDir: "{app}"
Source: "README.md"; DestDir: "{app}"; Flags: isreadme

[Icons]
Name: "{group}\Cliperus"; Filename: "{app}\Cliperus.exe"
Name: "{commondesktop}\Cliperus"; Filename: "{app}\Cliperus.exe"

[Run]
Filename: "{app}\Cliperus.exe"; Description: "Launch Cliperus"; Flags: postinstall nowait skipifsilent
```

3. **Compile:**
   - Open `installer.iss` in Inno Setup
   - Click "Compile"
   - Get `CliperusSetup.exe`

---

## 🔐 Security Checklist

### Before Deploying:

- [ ] Change SECRET_KEY
- [ ] Use environment variables for all secrets
- [ ] Don't commit `.env` file
- [ ] Enable HTTPS in production
- [ ] Add authentication (for web version)
- [ ] Set up firewall rules
- [ ] Enable CORS properly
- [ ] Use secure database credentials
- [ ] Regular security updates

---

## 🧪 Testing Checklist

### Before Release:

- [ ] Test on clean Windows install
- [ ] Verify FFmpeg bundled or documented
- [ ] Test OBS connection
- [ ] Test all platform APIs
- [ ] Verify clip generation
- [ ] Test TikTok upload
- [ ] Check all routes working
- [ ] Test error handling
- [ ] Verify logging works
- [ ] Test auto-recording
- [ ] Check segment rotation
- [ ] Verify workers start correctly

---

## 📊 Monitoring (Production)

### Recommended Tools:

1. **Sentry** - Error tracking
   ```python
   pip install sentry-sdk
   ```

2. **Prometheus** - Metrics
   ```python
   pip install prometheus-flask-exporter
   ```

3. **Papertrail** - Log aggregation
   ```python
   # Configure log forwarding
   ```

4. **UptimeRobot** - Uptime monitoring
   - Monitor `/api/health` endpoint

---

## 📞 Getting Help

### Build Issues:

1. Check Python version (3.10+)
2. Update pip: `python -m pip install --upgrade pip`
3. Clear cache: `pip cache purge`
4. Try virtual environment
5. Check PyInstaller logs

### Deployment Issues:

1. Check service logs
2. Verify environment variables
3. Test health endpoint
4. Check database connection
5. Verify port binding

### Runtime Issues:

1. Check `logs/cliperus.log`
2. Test `/api/health`
3. Verify workers running
4. Check disk space
5. Test FFmpeg installation

---

## 🎉 Success Checklist

Your deployment is successful when:

- [ ] Application starts without errors
- [ ] `/api/health` returns `healthy`
- [ ] All workers showing as running
- [ ] Can create streams
- [ ] Can start recording
- [ ] Clips generate successfully
- [ ] Uploads work (if configured)
- [ ] Stream monitoring works
- [ ] OBS connects (if configured)
- [ ] No errors in logs

---

## 📝 Next Steps

After successful deployment:

1. **Configure API keys** for platforms
2. **Set up OBS** WebSocket connection
3. **Add streams** to monitor
4. **Create triggers** for auto-clipping
5. **Configure TikTok** accounts
6. **Test end-to-end** workflow
7. **Monitor logs** for issues
8. **Set up backups** for database
9. **Document** your specific setup
10. **Share** with users!

---

**Need more help?**
- GitHub Issues: Report bugs
- Documentation: Full guides
- Discord: Community support

Good luck with your deployment! 🚀
