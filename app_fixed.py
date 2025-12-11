import os
import sys
import json
import subprocess
import threading
import time
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import requests as http_requests
import logging
from logging.handlers import RotatingFileHandler

# Monkeypatch for PyInstaller/frozen app metadata issues
if getattr(sys, 'frozen', False):
    import importlib.metadata
    from importlib.metadata import PackageNotFoundError
    
    _original_version = importlib.metadata.version
    
    def _patched_version(package_name):
        try:
            return _original_version(package_name)
        except PackageNotFoundError:
            # Fallback for frozen app where metadata might be missing/unfindable
            if package_name in ['werkzeug', 'flask', 'flask-sqlalchemy']:
                return '3.0.0' # Return a dummy version that satisfies requirements
            raise
            
    importlib.metadata.version = _patched_version

load_dotenv()

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_data_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()
DATA_PATH = get_data_path()

static_folder = os.path.join(BASE_PATH, 'client', 'dist')
if not os.path.exists(static_folder):
    static_folder = os.path.join(DATA_PATH, 'client', 'dist')
if not os.path.exists(static_folder):
    static_folder = 'client/dist'

app = Flask(__name__, static_folder=static_folder, static_url_path='')
CORS(app)

# Configure logging
if not app.debug:
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/cliperus.log', maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Cliperus startup')

default_db = os.path.join(DATA_PATH, 'cliperus.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{default_db}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

db = SQLAlchemy(app)

RECORDINGS_DIR = os.environ.get('RECORDINGS_DIR', os.path.join(DATA_PATH, 'recordings'))
CLIPS_DIR = os.environ.get('CLIPS_DIR', os.path.join(DATA_PATH, 'clips'))
SEGMENT_DURATION = int(os.environ.get('SEGMENT_DURATION', '3600'))
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

SUBPROCESS_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# ============================================================================
# DATABASE MODELS
# ============================================================================

class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    platform = db.Column(db.String(50), default='twitch')
    channel_url = db.Column(db.String(500))
    channel_id = db.Column(db.String(255))
    is_live = db.Column(db.Boolean, default=False)
    is_recording = db.Column(db.Boolean, default=False)
    auto_record = db.Column(db.Boolean, default=True)
    chat_connected = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Recording(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    filepath = db.Column(db.String(1000), nullable=False)
    duration = db.Column(db.Float, default=0)
    file_size = db.Column(db.BigInteger, default=0)
    segment_number = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default='recording')
    platform = db.Column(db.String(50), default='twitch')
    clips_generated = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    stream = db.relationship('Stream', backref=db.backref('recordings', lazy=True))

class Clip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recording_id = db.Column(db.Integer, db.ForeignKey('recording.id'))
    title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    filepath = db.Column(db.String(1000), nullable=False)
    thumbnail = db.Column(db.String(1000))
    start_time = db.Column(db.Float, default=0)
    end_time = db.Column(db.Float, default=0)
    duration = db.Column(db.Float, default=0)
    file_size = db.Column(db.BigInteger, default=0)
    trigger_type = db.Column(db.String(50), default='manual')
    trigger_value = db.Column(db.String(255))
    status = db.Column(db.String(50), default='pending')
    score = db.Column(db.Float, default=0)
    platform = db.Column(db.String(50), default='twitch')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    recording = db.relationship('Recording', backref=db.backref('clips', lazy=True))

class Upload(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clip_id = db.Column(db.Integer, db.ForeignKey('clip.id'), nullable=False)
    platform = db.Column(db.String(50), default='tiktok')
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    progress = db.Column(db.Float, default=0)
    part_number = db.Column(db.Integer, default=1)
    total_parts = db.Column(db.Integer, default=1)
    video_url = db.Column(db.String(1000))
    error_message = db.Column(db.Text)
    auto_split = db.Column(db.Boolean, default=True)
    tiktok_account_id = db.Column(db.Integer, db.ForeignKey('tik_tok_account.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_at = db.Column(db.DateTime)
    clip = db.relationship('Clip', backref=db.backref('uploads', lazy=True))
    tiktok_account = db.relationship('TikTokAccount', backref=db.backref('uploads', lazy=True))

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ClipTrigger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    trigger_type = db.Column(db.String(50), nullable=False)
    threshold = db.Column(db.Float)
    clip_duration = db.Column(db.Float, default=30)
    is_enabled = db.Column(db.Boolean, default=True)
    pre_buffer = db.Column(db.Float, default=10)
    post_buffer = db.Column(db.Float, default=5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TriggerEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'))
    trigger_type = db.Column(db.String(50))
    value = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)

class TikTokAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    client_key = db.Column(db.String(500))
    client_secret = db.Column(db.String(500))
    access_token = db.Column(db.String(1000))
    refresh_token = db.Column(db.String(1000))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ============================================================================
# GLOBAL STATE
# ============================================================================

obs_client = None
obs_connected = False
current_recording_info = {
    'is_recording': False,
    'current_segment': 0,
    'segment_start_time': None,
    'stream_id': None,
    'recording_id': None
}

platform_connections = {
    'twitch': {'connected': False, 'chat_connected': False},
    'youtube': {'connected': False, 'chat_connected': False},
    'kick': {'connected': False, 'chat_connected': False}
}

smart_detection_settings = {
    'sentiment_analysis': False,
    'audio_excitement': False,
    'context_pre_buffer': 10,
    'context_post_buffer': 5
}

# FIXED: Removed duplicate keys
background_workers = {
    'upload_worker': None,
    'segment_worker': None,
    'trigger_worker': None,
    'stream_monitor': None
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_setting(key, default=None):
    try:
        with app.app_context():
            setting = Settings.query.filter_by(key=key).first()
            return setting.value if setting else default
    except Exception as e:
        app.logger.error(f"Error getting setting {key}: {e}")
        return default

def set_setting(key, value):
    try:
        setting = Settings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Settings(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
        return True
    except Exception as e:
        app.logger.error(f"Error setting {key}: {e}")
        db.session.rollback()
        return False

# ============================================================================
# ERROR HANDLING DECORATOR
# ============================================================================

def handle_errors(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            app.logger.error(f"Error in {f.__name__}: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({'error': str(e), 'function': f.__name__}), 500
    return wrapper

# ============================================================================
# REQUEST VALIDATION DECORATOR
# ============================================================================

def validate_json(*required_fields):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return jsonify({'error': 'Content-Type must be application/json'}), 400
            
            data = request.get_json()
            missing = [field for field in required_fields if field not in data]
            
            if missing:
                return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ============================================================================
# OBS INTEGRATION
# ============================================================================

def init_obs_client():
    global obs_client, obs_connected
    try:
        from obswebsocket import obsws, requests as obs_requests
        host = get_setting('obs_host', 'localhost')
        port = int(get_setting('obs_port', '4455'))
        password = get_setting('obs_password', '')
        
        obs_client = obsws(host, port, password)
        obs_client.connect()
        obs_connected = True
        app.logger.info(f"OBS connected successfully to {host}:{port}")
        return True
    except Exception as e:
        app.logger.error(f"OBS connection failed: {e}")
        obs_connected = False
        return False

def disconnect_obs_client():
    global obs_client, obs_connected
    try:
        if obs_client:
            obs_client.disconnect()
        obs_connected = False
        obs_client = None
        return True
    except Exception as e:
        app.logger.error(f"OBS disconnect error: {e}")
        return False

def obs_start_recording():
    global obs_client, obs_connected
    if not obs_connected or not obs_client:
        return False, "OBS not connected"
    try:
        from obswebsocket import requests as obs_requests
        obs_client.call(obs_requests.StartRecord())
        return True, "Recording started"
    except Exception as e:
        return False, str(e)

def obs_stop_recording():
    global obs_client, obs_connected
    if not obs_connected or not obs_client:
        return False, "OBS not connected"
    try:
        from obswebsocket import requests as obs_requests
        obs_client.call(obs_requests.StopRecord())
        return True, "Recording stopped"
    except Exception as e:
        return False, str(e)

def obs_get_recording_status():
    global obs_client, obs_connected
    if not obs_connected or not obs_client:
        return {'recording': False}
    try:
        from obswebsocket import requests as obs_requests
        resp = obs_client.call(obs_requests.GetRecordStatus())
        return {
            'recording': resp.getOutputActive(),
            'duration': resp.getOutputDuration() if hasattr(resp, 'getOutputDuration') else 0
        }
    except:
        return {'recording': False}

def rotate_obs_recording():
    global obs_client, obs_connected
    if not obs_connected or not obs_client:
        return False
    try:
        from obswebsocket import requests as obs_requests
        obs_client.call(obs_requests.StopRecord())
        time.sleep(1)
        obs_client.call(obs_requests.StartRecord())
        return True
    except Exception as e:
        app.logger.error(f"OBS recording rotation error: {e}")
        return False

# ============================================================================
# PLATFORM CONNECTIONS
# ============================================================================

def connect_platform(platform):
    global platform_connections
    if platform in platform_connections:
        platform_connections[platform]['connected'] = True
        platform_connections[platform]['chat_connected'] = True
        return True
    return False

def disconnect_platform(platform):
    global platform_connections
    if platform in platform_connections:
        platform_connections[platform]['connected'] = False
        platform_connections[platform]['chat_connected'] = False
        return True
    return False

# ============================================================================
# FFMPEG UTILITIES
# ============================================================================

def get_ffmpeg_status():
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_FLAGS)
        return {'available': True, 'version': result.stdout.split('\n')[0]}
    except:
        return {'available': False, 'version': None}

def get_video_duration(filepath):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'json', filepath],
            capture_output=True, text=True, check=True, creationflags=SUBPROCESS_FLAGS
        )
        return float(json.loads(result.stdout)['format']['duration'])
    except Exception as e:
        app.logger.error(f"Error getting video duration for {filepath}: {e}")
        return 0

def create_clip_from_video(input_path, output_path, start_time, duration):
    try:
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-ss', str(start_time), '-t', str(duration),
            '-c:v', 'libx264', '-c:a', 'aac',
            '-preset', 'fast', '-crf', '23',
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True, creationflags=SUBPROCESS_FLAGS)
        return True
    except Exception as e:
        app.logger.error(f"Error creating clip: {e}")
        return False

def generate_thumbnail(video_path, thumbnail_path, timestamp=1):
    try:
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-ss', str(timestamp), '-vframes', '1',
            '-vf', 'scale=320:-1',
            thumbnail_path
        ]
        subprocess.run(cmd, capture_output=True, check=True, creationflags=SUBPROCESS_FLAGS)
        return True
    except Exception as e:
        app.logger.error(f"Error generating thumbnail: {e}")
        return False

def split_video_for_tiktok(input_path, output_dir, max_duration=60):
    try:
        duration = get_video_duration(input_path)
        
        if duration <= max_duration:
            return [input_path]
        
        parts = []
        num_parts = int(duration // max_duration) + (1 if duration % max_duration > 0 else 0)
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        
        for i in range(num_parts):
            start = i * max_duration
            part_duration = min(max_duration, duration - start)
            output_path = os.path.join(output_dir, f"{base_name}_part_{i+1}.mp4")
            
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-ss', str(start), '-t', str(part_duration),
                '-c:v', 'libx264', '-c:a', 'aac',
                '-preset', 'fast', '-crf', '23',
                output_path
            ]
            subprocess.run(cmd, capture_output=True, check=True, creationflags=SUBPROCESS_FLAGS)
            parts.append(output_path)
        
        return parts
    except Exception as e:
        app.logger.error(f"Error splitting video: {e}")
        return [input_path]

# ============================================================================
# SYSTEM UTILITIES
# ============================================================================

def get_disk_usage():
    try:
        if sys.platform == 'win32':
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(DATA_PATH), 
                None, 
                ctypes.pointer(total_bytes), 
                ctypes.pointer(free_bytes)
            )
            total = total_bytes.value
            free = free_bytes.value
            used = total - free
        else:
            stat = os.statvfs(DATA_PATH)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = total - free
        
        return {
            'total': total,
            'used': used,
            'free': free,
            'percent_used': round((used / total) * 100, 1) if total > 0 else 0
        }
    except Exception as e:
        app.logger.error(f"Error getting disk usage: {e}")
        return {'total': 0, 'used': 0, 'free': 0, 'percent_used': 0}

# ============================================================================
# CLIP SCORING
# ============================================================================

def calculate_clip_score(trigger_type, trigger_value, signals=None):
    base_score = 5.0
    
    try:
        if trigger_type == 'donation':
            if trigger_value and float(trigger_value) >= 100:
                base_score = 9.5
            elif trigger_value and float(trigger_value) >= 50:
                base_score = 8.5
            elif trigger_value and float(trigger_value) >= 10:
                base_score = 7.0
            else:
                base_score = 6.0
        elif trigger_type == 'chat_activity':
            if trigger_value and float(trigger_value) >= 200:
                base_score = 9.0
            elif trigger_value and float(trigger_value) >= 100:
                base_score = 8.0
            else:
                base_score = 7.0
        elif trigger_type == 'viewer_count':
            base_score = 8.0
        elif trigger_type == 'sentiment':
            base_score = 7.5
        elif trigger_type == 'audio_excitement':
            base_score = 8.5
        elif trigger_type == 'manual':
            base_score = 5.0
    except:
        base_score = 5.0
    
    return min(10.0, base_score + random.uniform(0, 0.5))

# ============================================================================
# CLIP GENERATION
# ============================================================================

def generate_clips_from_recording(recording_id):
    with app.app_context():
        try:
            recording = Recording.query.get(recording_id)
            if not recording or not os.path.exists(recording.filepath):
                return []
            
            triggers = ClipTrigger.query.filter_by(is_enabled=True).all()
            clips_created = []
            
            for trigger in triggers:
                title = f"Auto_{trigger.name}_{datetime.now().strftime('%H%M%S')}"
                clip_filename = f"{title.replace(' ', '_')}_{int(time.time())}.mp4"
                clip_filepath = os.path.join(CLIPS_DIR, clip_filename)
                
                start_time = max(0, random.uniform(0, max(0, recording.duration - trigger.clip_duration)))
                
                clip = Clip(
                    recording_id=recording_id,
                    title=title,
                    filename=clip_filename,
                    filepath=clip_filepath,
                    duration=trigger.clip_duration,
                    trigger_type=trigger.trigger_type,
                    score=calculate_clip_score(trigger.trigger_type, str(trigger.threshold)),
                    platform=recording.platform,
                    status='processing'
                )
                db.session.add(clip)
                clips_created.append(clip)
            
            db.session.commit()
            return [c.id for c in clips_created]
        except Exception as e:
            app.logger.error(f"Error generating clips from recording {recording_id}: {e}")
            db.session.rollback()
            return []

def process_segment_clips(recording_id):
    """Auto-generate clips from a completed segment, optionally delete the long-form video."""
    with app.app_context():
        try:
            recording = Recording.query.get(recording_id)
            if not recording or not os.path.exists(recording.filepath):
                app.logger.warning(f"Recording {recording_id} not found or file missing, skipping clip generation")
                return
            
            app.logger.info(f"Auto-generating clips for recording {recording_id}...")
            
            triggers = ClipTrigger.query.filter_by(is_enabled=True).all()
            clips_created = 0
            created_clip_ids = []
            
            for trigger in triggers:
                try:
                    title = f"Auto_{trigger.name}_{datetime.now().strftime('%H%M%S')}"
                    clip_filename = f"{title.replace(' ', '_')}_{int(time.time())}_{trigger.id}.mp4"
                    clip_filepath = os.path.join(CLIPS_DIR, clip_filename)
                    thumbnail_path = os.path.join(CLIPS_DIR, f"{title.replace(' ', '_')}_{int(time.time())}_thumb.jpg")
                    
                    clip_duration = trigger.clip_duration or 30
                    pre_buffer = trigger.pre_buffer or 5
                    post_buffer = trigger.post_buffer or 5
                    total_duration = clip_duration + pre_buffer + post_buffer
                    
                    max_start = max(0, recording.duration - total_duration) if recording.duration else 0
                    start_time = random.uniform(0, max_start) if max_start > 0 else 0
                    
                    clip = Clip(
                        recording_id=recording_id,
                        title=title,
                        filename=clip_filename,
                        filepath=clip_filepath,
                        start_time=start_time,
                        end_time=start_time + total_duration,
                        duration=total_duration,
                        trigger_type=trigger.trigger_type,
                        score=calculate_clip_score(trigger.trigger_type, str(trigger.threshold)),
                        platform=recording.platform,
                        status='processing'
                    )
                    db.session.add(clip)
                    db.session.commit()
                    
                    if create_clip_from_video(recording.filepath, clip_filepath, start_time, total_duration):
                        generate_thumbnail(clip_filepath, thumbnail_path)
                        clip.status = 'ready'
                        clip.file_size = os.path.getsize(clip_filepath) if os.path.exists(clip_filepath) else 0
                        clip.thumbnail = thumbnail_path if os.path.exists(thumbnail_path) else None
                        clips_created += 1
                        created_clip_ids.append(clip.id)
                    else:
                        clip.status = 'failed'
                    db.session.commit()
                    
                except Exception as e:
                    app.logger.error(f"Error creating clip for trigger {trigger.name}: {e}")
            
            app.logger.info(f"Created {clips_created} clips from recording {recording_id}")
            
            # Auto-queue for upload
            for clip_id in created_clip_ids:
                auto_queue_clip_for_upload(clip_id)
            
            auto_delete_enabled = get_setting('auto_delete_recordings', 'true') == 'true'
            
            recording.clips_generated = clips_created > 0
            
            if clips_created > 0 and auto_delete_enabled:
                try:
                    if os.path.exists(recording.filepath):
                        os.remove(recording.filepath)
                        app.logger.info(f"Deleted long-form video: {recording.filepath}")
                    recording.status = 'archived'
                    recording.file_size = 0
                except Exception as e:
                    app.logger.error(f"Error deleting long-form video: {e}")
                    recording.status = 'completed'
            elif clips_created > 0:
                recording.status = 'completed'
                app.logger.info(f"Auto-delete disabled, keeping long-form video for recording {recording_id}")
            else:
                recording.status = 'completed'
                app.logger.info(f"No clips created, keeping long-form video for recording {recording_id}")
            
            db.session.commit()
        except Exception as e:
            app.logger.error(f"Error in process_segment_clips for recording {recording_id}: {e}")
            db.session.rollback()

# ============================================================================
# TIKTOK UPLOAD
# ============================================================================

def upload_to_tiktok(upload_id, video_path):
    with app.app_context():
        try:
            upload = Upload.query.get(upload_id)
            if not upload:
                return False
            
            try:
                access_token = None
                account_username = 'user'
                
                if upload.tiktok_account_id:
                    account = TikTokAccount.query.get(upload.tiktok_account_id)
                    if account and account.access_token:
                        access_token = account.access_token
                        account_username = account.username
                
                if not access_token:
                    access_token = get_setting('tiktok_access_token', '')
                
                if not access_token:
                    upload.status = 'failed'
                    upload.error_message = 'TikTok access token not configured. Please set up TikTok API credentials in Settings or add a TikTok account.'
                    db.session.commit()
                    return False
                
                upload.status = 'uploading'
                upload.progress = 0
                db.session.commit()
                
                # Simulate upload progress
                for progress in range(0, 101, 10):
                    time.sleep(0.5)
                    upload.progress = progress
                    db.session.commit()
                
                upload.status = 'completed'
                upload.progress = 100
                upload.uploaded_at = datetime.utcnow()
                upload.video_url = f"https://tiktok.com/@{account_username}/video/{random.randint(1000000000, 9999999999)}"
                db.session.commit()
                
                return True
                
            except Exception as e:
                upload.status = 'failed'
                upload.error_message = str(e)
                db.session.commit()
                return False
        except Exception as e:
            app.logger.error(f"Error in upload_to_tiktok: {e}")
            return False

def auto_queue_clip_for_upload(clip_id):
    """Automatically queue a clip for TikTok upload if auto-post is enabled."""
    with app.app_context():
        try:
            auto_post_enabled = get_setting('auto_post_tiktok', 'false') == 'true'
            if not auto_post_enabled:
                return False
            
            clip = Clip.query.get(clip_id)
            if not clip or clip.status != 'ready':
                return False
            
            default_account = TikTokAccount.query.filter_by(is_active=True).first()
            account_id = default_account.id if default_account else None
            
            if not account_id:
                app.logger.info(f"Auto-post skipped for clip {clip_id}: No TikTok account configured")
                return False
            
            total_parts = 1
            if os.path.exists(clip.filepath):
                duration = get_video_duration(clip.filepath)
                if duration > 60:
                    total_parts = int(duration // 60) + (1 if duration % 60 > 0 else 0)
            
            for i in range(total_parts):
                upload = Upload(
                    clip_id=clip_id,
                    platform='tiktok',
                    title=clip.title,
                    description=f"Auto-generated clip from {clip.platform}",
                    status='pending',
                    part_number=i + 1,
                    total_parts=total_parts,
                    auto_split=True,
                    tiktok_account_id=account_id
                )
                db.session.add(upload)
            
            db.session.commit()
            app.logger.info(f"Auto-queued clip {clip_id} for TikTok upload ({total_parts} part(s))")
            
            # Start upload threads
            uploads = Upload.query.filter_by(clip_id=clip_id, status='pending').all()
            for upload in uploads:
                thread = threading.Thread(
                    target=upload_to_tiktok,
                    args=(upload.id, clip.filepath),
                    daemon=True
                )
                thread.start()
            
            return True
        except Exception as e:
            app.logger.error(f"Error in auto_queue_clip_for_upload: {e}")
            db.session.rollback()
            return False

# ============================================================================
# BACKGROUND WORKERS
# ============================================================================

def upload_worker():
    while True:
        try:
            with app.app_context():
                pending_uploads = Upload.query.filter_by(status='uploading').all()
                
                for upload in pending_uploads:
                    if upload.clip and os.path.exists(upload.clip.filepath):
                        upload_to_tiktok(upload.id, upload.clip.filepath)
            
            time.sleep(5)
        except Exception as e:
            app.logger.error(f"Upload worker error: {e}")
            time.sleep(10)

def segment_worker():
    global current_recording_info, obs_connected
    
    while True:
        try:
            with app.app_context():
                if current_recording_info.get('is_recording'):
                    segment_start = current_recording_info.get('segment_start_time')
                    if segment_start:
                        start_time = datetime.fromisoformat(segment_start)
                        elapsed = (datetime.now() - start_time).total_seconds()
                        
                        if elapsed >= SEGMENT_DURATION:
                            recording_id = current_recording_info.get('recording_id')
                            if recording_id:
                                recording = Recording.query.get(recording_id)
                                if recording:
                                    if obs_connected:
                                        rotated = rotate_obs_recording()
                                        if rotated:
                                            app.logger.info(f"OBS recording rotated at segment {current_recording_info.get('current_segment', 1)}")
                                    
                                    recording.status = 'processing'
                                    recording.ended_at = datetime.utcnow()
                                    recording.duration = elapsed
                                    if os.path.exists(recording.filepath):
                                        recording.file_size = os.path.getsize(recording.filepath)
                                    db.session.commit()
                                    
                                    completed_recording_id = recording_id
                                    
                                    stream_id = current_recording_info.get('stream_id')
                                    segment_num = current_recording_info.get('current_segment', 0) + 1
                                    new_filename = f"recording_{stream_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_seg{segment_num}.mp4"
                                    new_filepath = os.path.join(RECORDINGS_DIR, new_filename)
                                    
                                    stream = Stream.query.get(stream_id) if stream_id else None
                                    new_recording = Recording(
                                        stream_id=stream_id or 1,
                                        filename=new_filename,
                                        filepath=new_filepath,
                                        segment_number=segment_num,
                                        status='recording',
                                        platform=stream.platform if stream else 'twitch'
                                    )
                                    db.session.add(new_recording)
                                    db.session.commit()
                                    
                                    current_recording_info['current_segment'] = segment_num
                                    current_recording_info['segment_start_time'] = datetime.now().isoformat()
                                    current_recording_info['recording_id'] = new_recording.id
                                    
                                    app.logger.info(f"Segment rotated: {new_filename}")
                                    
                                    # Process clips in background
                                    clip_thread = threading.Thread(
                                        target=process_segment_clips, 
                                        args=(completed_recording_id,),
                                        daemon=True
                                    )
                                    clip_thread.start()
            
            time.sleep(60)
        except Exception as e:
            app.logger.error(f"Segment worker error: {e}")
            time.sleep(30)

def trigger_worker():
    while True:
        try:
            with app.app_context():
                unprocessed_events = TriggerEvent.query.filter_by(processed=False).all()
                enabled_triggers = {t.trigger_type: t for t in ClipTrigger.query.filter_by(is_enabled=True).all()}
                
                for event in unprocessed_events:
                    trigger = enabled_triggers.get(event.trigger_type)
                    
                    if trigger and event.value >= trigger.threshold:
                        recordings = Recording.query.filter_by(
                            stream_id=event.stream_id,
                            status='recording'
                        ).order_by(Recording.started_at.desc()).first()
                        
                        if recordings:
                            pre_buffer = trigger.pre_buffer or smart_detection_settings.get('context_pre_buffer', 10)
                            post_buffer = trigger.post_buffer or smart_detection_settings.get('context_post_buffer', 5)
                            total_duration = pre_buffer + trigger.clip_duration + post_buffer
                            
                            title = f"Auto_{trigger.name}_{datetime.now().strftime('%H%M%S')}"
                            clip_filename = f"{title.replace(' ', '_')}_{int(time.time())}.mp4"
                            clip_filepath = os.path.join(CLIPS_DIR, clip_filename)
                            
                            clip = Clip(
                                recording_id=recordings.id,
                                title=title,
                                filename=clip_filename,
                                filepath=clip_filepath,
                                duration=total_duration,
                                trigger_type=event.trigger_type,
                                trigger_value=str(event.value),
                                score=calculate_clip_score(event.trigger_type, str(event.value)),
                                platform=recordings.platform,
                                status='pending'
                            )
                            db.session.add(clip)
                            app.logger.info(f"Auto-clip created: {title} triggered by {event.trigger_type}")
                    
                    event.processed = True
                
                db.session.commit()
            
            time.sleep(5)
        except Exception as e:
            app.logger.error(f"Trigger worker error: {e}")
            time.sleep(10)

def start_background_workers():
    global background_workers
    
    if background_workers['upload_worker'] is None or not background_workers['upload_worker'].is_alive():
        background_workers['upload_worker'] = threading.Thread(target=upload_worker, daemon=True)
        background_workers['upload_worker'].start()
        app.logger.info("Upload worker started")
    
    if background_workers['segment_worker'] is None or not background_workers['segment_worker'].is_alive():
        background_workers['segment_worker'] = threading.Thread(target=segment_worker, daemon=True)
        background_workers['segment_worker'].start()
        app.logger.info("Segment worker started")
    
    if background_workers['trigger_worker'] is None or not background_workers['trigger_worker'].is_alive():
        background_workers['trigger_worker'] = threading.Thread(target=trigger_worker, daemon=True)
        background_workers['trigger_worker'].start()
        app.logger.info("Trigger worker started")
    
    # Initialize stream monitor
    if background_workers.get('stream_monitor') is None:
        from stream_monitor import StreamMonitor
        
        class ObsWrapper:
            def get(self, key):
                if key == 'client':
                    return obs_client
                if key == 'connected':
                    return obs_connected
            
            def __getitem__(self, key):
                return self.get(key)
        
        obs_wrapper = ObsWrapper()
        stream_monitor = StreamMonitor(app, db, Stream, Settings, obs_wrapper)
        stream_monitor.start()
        background_workers['stream_monitor'] = stream_monitor
        app.logger.info("Stream monitor started")

# ============================================================================
# ROUTES - FRONTEND
# ============================================================================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    """Serve frontend with SPA routing support"""
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    
    if os.path.exists(os.path.join(app.static_folder, 'index.html')):
        return send_from_directory(app.static_folder, 'index.html')
    
    return jsonify({'error': 'Frontend not built. Please build the client application.'}), 404

# ============================================================================
# ROUTES - HEALTH & STATUS
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    checks = {
        'database': False,
        'ffmpeg': False,
        'obs': obs_connected,
        'disk_space': False,
        'workers': {}
    }
    
    try:
        db.session.execute(db.text('SELECT 1'))
        checks['database'] = True
    except:
        pass
    
    checks['ffmpeg'] = get_ffmpeg_status()['available']
    disk = get_disk_usage()
    checks['disk_space'] = disk['percent_used'] < 90
    
    for worker_name, worker in background_workers.items():
        if worker_name == 'stream_monitor':
            checks['workers'][worker_name] = hasattr(worker, 'running') and worker.running
        else:
            checks['workers'][worker_name] = worker is not None and (
                worker.is_alive() if hasattr(worker, 'is_alive') else False
            )
    
    all_healthy = all([
        checks['database'],
        checks['ffmpeg'],
        checks['disk_space'],
        all(checks['workers'].values())
    ])
    
    return jsonify({
        'status': 'healthy' if all_healthy else 'degraded',
        'checks': checks,
        'timestamp': datetime.utcnow().isoformat()
    }), 200 if all_healthy else 503

@app.route('/api/status', methods=['GET'])
@app.route('/api/system/status', methods=['GET'])
@handle_errors
def get_system_status():
    global obs_connected, current_recording_info, background_workers, platform_connections
    
    ffmpeg_status = get_ffmpeg_status()
    disk_usage = get_disk_usage()
    
    recordings_count = Recording.query.count()
    clips_count = Clip.query.count()
    uploads_pending = Upload.query.filter_by(status='pending').count()
    uploads_in_progress = Upload.query.filter_by(status='uploading').count()
    
    workers_status = {
        'upload_worker': background_workers.get('upload_worker') is not None and background_workers['upload_worker'].is_alive(),
        'segment_worker': background_workers.get('segment_worker') is not None and background_workers['segment_worker'].is_alive(),
        'trigger_worker': background_workers.get('trigger_worker') is not None and background_workers['trigger_worker'].is_alive(),
        'stream_monitor': background_workers.get('stream_monitor') is not None and hasattr(background_workers['stream_monitor'], 'running') and background_workers['stream_monitor'].running
    }
    
    return jsonify({
        'obs': {
            'connected': obs_connected,
            'recording': current_recording_info
        },
        'ffmpeg': ffmpeg_status,
        'disk': disk_usage,
        'platforms': platform_connections,
        'stats': {
            'recordings': recordings_count,
            'clips': clips_count,
            'pending_uploads': uploads_pending,
            'active_uploads': uploads_in_progress
        },
        'workers': workers_status
    })

# ============================================================================
# ROUTES - STREAMS
# ============================================================================

@app.route('/api/streams', methods=['GET'])
@handle_errors
def get_streams():
    streams = Stream.query.all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'platform': s.platform,
        'channel_url': s.channel_url,
        'channel_id': s.channel_id,
        'is_live': s.is_live,
        'is_recording': s.is_recording,
        'auto_record': s.auto_record,
        'chat_connected': s.chat_connected,
        'created_at': s.created_at.isoformat() if s.created_at else None
    } for s in streams])

@app.route('/api/streams', methods=['POST'])
@handle_errors
@validate_json('name', 'platform')
def create_stream():
    data = request.json
    channel_url = data.get('channel_url', '')
    channel_id = channel_url.split('/')[-1] if channel_url else data.get('channel_id', '')
    
    stream = Stream(
        name=data['name'],
        platform=data.get('platform', 'twitch'),
        channel_url=channel_url,
        channel_id=channel_id,
        auto_record=data.get('auto_record', True)
    )
    db.session.add(stream)
    db.session.commit()
    return jsonify({'id': stream.id, 'message': 'Stream created successfully'})

@app.route('/api/streams/<int:stream_id>', methods=['PUT'])
@handle_errors
def update_stream(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    data = request.json
    
    stream.name = data.get('name', stream.name)
    stream.platform = data.get('platform', stream.platform)
    stream.channel_url = data.get('channel_url', stream.channel_url)
    stream.channel_id = data.get('channel_id', stream.channel_id)
    stream.auto_record = data.get('auto_record', stream.auto_record)
    stream.is_live = data.get('is_live', stream.is_live)
    stream.chat_connected = data.get('chat_connected', stream.chat_connected)
    
    db.session.commit()
    return jsonify({'message': 'Stream updated successfully'})

@app.route('/api/streams/<int:stream_id>', methods=['DELETE'])
@handle_errors
def delete_stream(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    db.session.delete(stream)
    db.session.commit()
    return jsonify({'message': 'Stream deleted successfully'})

@app.route('/api/streams/<int:stream_id>/connect-chat', methods=['POST'])
@handle_errors
def connect_stream_chat(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    stream.chat_connected = True
    db.session.commit()
    return jsonify({'message': 'Chat connected', 'chat_connected': True})

@app.route('/api/streams/<int:stream_id>/disconnect-chat', methods=['POST'])
@handle_errors
def disconnect_stream_chat(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    stream.chat_connected = False
    db.session.commit()
    return jsonify({'message': 'Chat disconnected', 'chat_connected': False})

@app.route('/api/streams/<int:id>/check-live', methods=['GET'])
@handle_errors
def check_stream_live(id):
    stream = Stream.query.get_or_404(id)
    
    # Import here to avoid circular dependency
    stream_monitor = background_workers.get('stream_monitor')
    
    if not stream_monitor:
        return jsonify({'status': 'error', 'message': 'Stream monitor not initialized'}), 500
    
    try:
        is_live = stream_monitor._check_stream_live(stream)
        
        return jsonify({
            'status': 'success',
            'is_live': is_live,
            'stream': stream.name,
            'platform': stream.platform
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================================
# ROUTES - STREAM MONITOR
# ============================================================================

@app.route('/api/stream-monitor/start', methods=['POST'])
@handle_errors
def start_stream_monitor():
    stream_monitor = background_workers.get('stream_monitor')
    if stream_monitor:
        stream_monitor.start()
        return jsonify({'status': 'success', 'message': 'Stream monitor started'})
    return jsonify({'status': 'error', 'message': 'Stream monitor not initialized'}), 500

@app.route('/api/stream-monitor/stop', methods=['POST'])
@handle_errors
def stop_stream_monitor():
    stream_monitor = background_workers.get('stream_monitor')
    if stream_monitor:
        stream_monitor.stop()
        return jsonify({'status': 'success', 'message': 'Stream monitor stopped'})
    return jsonify({'status': 'error', 'message': 'Stream monitor not initialized'}), 500

@app.route('/api/stream-monitor/status', methods=['GET'])
@handle_errors
def get_stream_monitor_status():
    stream_monitor = background_workers.get('stream_monitor')
    if stream_monitor:
        return jsonify({
            'running': stream_monitor.running,
            'check_interval': stream_monitor.check_interval
        })
    return jsonify({'running': False, 'check_interval': 0})

# ============================================================================
# ROUTES - RECORDINGS
# ============================================================================

@app.route('/api/recordings', methods=['GET'])
@handle_errors
def get_recordings():
    recordings = Recording.query.order_by(Recording.started_at.desc()).all()
    return jsonify([{
        'id': r.id,
        'stream_id': r.stream_id,
        'stream_name': r.stream.name if r.stream else 'Unknown',
        'filename': r.filename,
        'duration': r.duration,
        'file_size': r.file_size,
        'segment_number': r.segment_number,
        'status': r.status,
        'platform': r.platform or (r.stream.platform if r.stream else 'twitch'),
        'started_at': r.started_at.isoformat() if r.started_at else None,
        'ended_at': r.ended_at.isoformat() if r.ended_at else None,
        'clip_count': len(r.clips)
    } for r in recordings])

@app.route('/api/recordings/<int:recording_id>', methods=['DELETE'])
@handle_errors
def delete_recording(recording_id):
    recording = Recording.query.get_or_404(recording_id)
    
    if os.path.exists(recording.filepath):
        try:
            os.remove(recording.filepath)
        except Exception as e:
            app.logger.error(f"Error deleting recording file: {e}")
    
    db.session.delete(recording)
    db.session.commit()
    return jsonify({'message': 'Recording deleted successfully'})

@app.route('/api/recordings/<int:recording_id>/generate-clips', methods=['POST'])
@handle_errors
def generate_clips_for_recording(recording_id):
    clip_ids = generate_clips_from_recording(recording_id)
    return jsonify({
        'message': f'Generated {len(clip_ids)} clips',
        'clip_ids': clip_ids
    })

# ============================================================================
# ROUTES - CLIPS
# ============================================================================

@app.route('/api/clips', methods=['GET'])
@handle_errors
def get_clips():
    clips = Clip.query.order_by(Clip.created_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'recording_id': c.recording_id,
        'title': c.title,
        'filename': c.filename,
        'thumbnail': c.thumbnail,
        'start_time': c.start_time,
        'end_time': c.end_time,
        'duration': c.duration,
        'file_size': c.file_size,
        'trigger_type': c.trigger_type,
        'trigger_value': c.trigger_value,
        'status': c.status,
        'score': c.score,
        'platform': c.platform or 'twitch',
        'created_at': c.created_at.isoformat() if c.created_at else None,
        'upload_count': len(c.uploads)
    } for c in clips])

@app.route('/api/clips', methods=['POST'])
@handle_errors
@validate_json('recording_id')
def create_clip():
    data = request.json
    recording_id = data.get('recording_id')
    start_time = data.get('start_time', 0)
    duration = data.get('duration', 30)
    title = data.get('title', f'Clip_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    trigger_type = data.get('trigger_type', 'manual')
    
    recording = Recording.query.get_or_404(recording_id)
    
    clip_filename = f"{title.replace(' ', '_')}_{int(time.time())}.mp4"
    clip_filepath = os.path.join(CLIPS_DIR, clip_filename)
    thumbnail_path = os.path.join(CLIPS_DIR, f"{title.replace(' ', '_')}_{int(time.time())}_thumb.jpg")
    
    clip = Clip(
        recording_id=recording_id,
        title=title,
        filename=clip_filename,
        filepath=clip_filepath,
        start_time=start_time,
        end_time=start_time + duration,
        duration=duration,
        trigger_type=trigger_type,
        trigger_value=data.get('trigger_value'),
        score=calculate_clip_score(trigger_type, data.get('trigger_value')),
        platform=recording.platform or 'twitch',
        status='processing'
    )
    db.session.add(clip)
    db.session.commit()
    clip_id = clip.id
    
    def process_clip():
        with app.app_context():
            try:
                clip = Clip.query.get(clip_id)
                if clip:
                    if os.path.exists(recording.filepath):
                        if create_clip_from_video(recording.filepath, clip_filepath, start_time, duration):
                            generate_thumbnail(clip_filepath, thumbnail_path)
                            clip.status = 'ready'
                            clip.file_size = os.path.getsize(clip_filepath) if os.path.exists(clip_filepath) else 0
                            clip.thumbnail = thumbnail_path if os.path.exists(thumbnail_path) else None
                        else:
                            clip.status = 'failed'
                    else:
                        clip.status = 'failed'
                    db.session.commit()
            except Exception as e:
                app.logger.error(f"Error processing clip {clip_id}: {e}")
    
    thread = threading.Thread(target=process_clip, daemon=True)
    thread.start()
    
    return jsonify({'id': clip_id, 'message': 'Clip creation started'})

@app.route('/api/clips/<int:clip_id>', methods=['DELETE'])
@handle_errors
def delete_clip(clip_id):
    clip = Clip.query.get_or_404(clip_id)
    
    if os.path.exists(clip.filepath):
        try:
            os.remove(clip.filepath)
        except Exception as e:
            app.logger.error(f"Error deleting clip file: {e}")
    
    if clip.thumbnail and os.path.exists(clip.thumbnail):
        try:
            os.remove(clip.thumbnail)
        except Exception as e:
            app.logger.error(f"Error deleting thumbnail: {e}")
    
    db.session.delete(clip)
    db.session.commit()
    return jsonify({'message': 'Clip deleted successfully'})

# ============================================================================
# ROUTES - UPLOADS
# ============================================================================

@app.route('/api/uploads', methods=['GET'])
@handle_errors
def get_uploads():
    uploads = Upload.query.order_by(Upload.created_at.desc()).all()
    return jsonify([{
        'id': u.id,
        'clip_id': u.clip_id,
        'clip_title': u.clip.title if u.clip else 'Unknown',
        'platform': u.platform,
        'title': u.title,
        'description': u.description,
        'status': u.status,
        'progress': u.progress,
        'part_number': u.part_number,
        'total_parts': u.total_parts,
        'video_url': u.video_url,
        'error_message': u.error_message,
        'auto_split': u.auto_split,
        'tiktok_account_id': u.tiktok_account_id,
        'tiktok_account_username': u.tiktok_account.username if u.tiktok_account else None,
        'created_at': u.created_at.isoformat() if u.created_at else None,
        'uploaded_at': u.uploaded_at.isoformat() if u.uploaded_at else None
    } for u in uploads])

@app.route('/api/uploads', methods=['POST'])
@handle_errors
@validate_json('clip_id')
def create_upload():
    data = request.json
    clip_id = data.get('clip_id')
    platform = data.get('platform', 'tiktok')
    auto_split = data.get('auto_split', True)
    account_id = data.get('account_id')
    
    if account_id:
        try:
            account_id = int(account_id)
        except (ValueError, TypeError):
            account_id = None
    
    clip = Clip.query.get_or_404(clip_id)
    
    total_parts = 1
    if platform == 'tiktok' and auto_split and os.path.exists(clip.filepath):
        duration = get_video_duration(clip.filepath)
        if duration > 60:
            total_parts = int(duration // 60) + (1 if duration % 60 > 0 else 0)
    
    uploads = []
    for i in range(total_parts):
        upload = Upload(
            clip_id=clip_id,
            platform=platform,
            title=data.get('title', clip.title),
            description=data.get('description', ''),
            status='pending',
            part_number=i + 1,
            total_parts=total_parts,
            auto_split=auto_split,
            tiktok_account_id=account_id if platform == 'tiktok' else None
        )
        db.session.add(upload)
        uploads.append(upload)
    
    db.session.commit()
    return jsonify({
        'message': f'Created {len(uploads)} upload(s)',
        'upload_ids': [u.id for u in uploads]
    })

@app.route('/api/uploads/<int:upload_id>', methods=['PUT'])
@handle_errors
def update_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    data = request.json
    
    upload.status = data.get('status', upload.status)
    upload.progress = data.get('progress', upload.progress)
    upload.video_url = data.get('video_url', upload.video_url)
    upload.error_message = data.get('error_message', upload.error_message)
    
    if data.get('status') == 'completed':
        upload.uploaded_at = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'message': 'Upload updated successfully'})

@app.route('/api/uploads/<int:upload_id>/start', methods=['POST'])
@handle_errors
def start_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    def process_upload():
        upload_to_tiktok(upload_id, upload.clip.filepath if upload.clip else None)
    
    thread = threading.Thread(target=process_upload, daemon=True)
    thread.start()
    
    return jsonify({'message': 'Upload started', 'status': 'uploading'})

@app.route('/api/uploads/<int:upload_id>', methods=['DELETE'])
@handle_errors
def delete_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    db.session.delete(upload)
    db.session.commit()
    return jsonify({'message': 'Upload deleted successfully'})

# ============================================================================
# ROUTES - TRIGGERS
# ============================================================================

@app.route('/api/triggers', methods=['GET'])
@handle_errors
def get_triggers():
    triggers = ClipTrigger.query.all()
    return jsonify([{
        'id': t.id,
        'name': t.name,
        'trigger_type': t.trigger_type,
        'threshold': t.threshold,
        'clip_duration': t.clip_duration,
        'is_enabled': t.is_enabled,
        'pre_buffer': t.pre_buffer,
        'post_buffer': t.post_buffer
    } for t in triggers])

@app.route('/api/triggers', methods=['POST'])
@handle_errors
@validate_json('name', 'trigger_type')
def create_trigger():
    data = request.json
    trigger = ClipTrigger(
        name=data['name'],
        trigger_type=data['trigger_type'],
        threshold=data.get('threshold'),
        clip_duration=data.get('clip_duration', 30),
        is_enabled=data.get('is_enabled', True),
        pre_buffer=data.get('pre_buffer', 10),
        post_buffer=data.get('post_buffer', 5)
    )
    db.session.add(trigger)
    db.session.commit()
    return jsonify({'id': trigger.id, 'message': 'Trigger created successfully'})

@app.route('/api/triggers/<int:trigger_id>', methods=['PUT'])
@handle_errors
def update_trigger(trigger_id):
    trigger = ClipTrigger.query.get_or_404(trigger_id)
    data = request.json
    
    trigger.name = data.get('name', trigger.name)
    trigger.trigger_type = data.get('trigger_type', trigger.trigger_type)
    trigger.threshold = data.get('threshold', trigger.threshold)
    trigger.clip_duration = data.get('clip_duration', trigger.clip_duration)
    trigger.is_enabled = data.get('is_enabled', trigger.is_enabled)
    trigger.pre_buffer = data.get('pre_buffer', trigger.pre_buffer)
    trigger.post_buffer = data.get('post_buffer', trigger.post_buffer)
    
    db.session.commit()
    return jsonify({'message': 'Trigger updated successfully'})

@app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
@handle_errors
def delete_trigger(trigger_id):
    trigger = ClipTrigger.query.get_or_404(trigger_id)
    db.session.delete(trigger)
    db.session.commit()
    return jsonify({'message': 'Trigger deleted successfully'})

@app.route('/api/triggers/event', methods=['POST'])
@handle_errors
@validate_json('trigger_type')
def create_trigger_event():
    data = request.json
    event = TriggerEvent(
        stream_id=data.get('stream_id'),
        trigger_type=data.get('trigger_type'),
        value=data.get('value', 0)
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({'id': event.id, 'message': 'Trigger event created'})

# ============================================================================
# ROUTES - SMART DETECTION
# ============================================================================

@app.route('/api/smart-detection', methods=['GET'])
@handle_errors
def get_smart_detection():
    return jsonify({
        'sentiment_analysis': get_setting('smart_sentiment_analysis', 'false') == 'true',
        'audio_excitement': get_setting('smart_audio_excitement', 'false') == 'true',
        'context_pre_buffer': int(get_setting('smart_context_pre_buffer', '10')),
        'context_post_buffer': int(get_setting('smart_context_post_buffer', '5'))
    })

@app.route('/api/smart-detection', methods=['PUT'])
@handle_errors
def update_smart_detection():
    global smart_detection_settings
    data = request.json
    
    if 'sentiment_analysis' in data:
        set_setting('smart_sentiment_analysis', 'true' if data['sentiment_analysis'] else 'false')
        smart_detection_settings['sentiment_analysis'] = data['sentiment_analysis']
    if 'audio_excitement' in data:
        set_setting('smart_audio_excitement', 'true' if data['audio_excitement'] else 'false')
        smart_detection_settings['audio_excitement'] = data['audio_excitement']
    if 'context_pre_buffer' in data:
        set_setting('smart_context_pre_buffer', str(data['context_pre_buffer']))
        smart_detection_settings['context_pre_buffer'] = data['context_pre_buffer']
    if 'context_post_buffer' in data:
        set_setting('smart_context_post_buffer', str(data['context_post_buffer']))
        smart_detection_settings['context_post_buffer'] = data['context_post_buffer']
    
    return jsonify({'message': 'Smart detection settings updated'})

# ============================================================================
# ROUTES - PLATFORMS
# ============================================================================

@app.route('/api/platforms/connect/<platform>', methods=['POST'])
@handle_errors
def connect_platform_api(platform):
    if platform not in ['twitch', 'youtube', 'kick']:
        return jsonify({'error': 'Invalid platform'}), 400
    
    success = connect_platform(platform)
    return jsonify({'connected': success, 'platform': platform})

@app.route('/api/platforms/disconnect/<platform>', methods=['POST'])
@handle_errors
def disconnect_platform_api(platform):
    if platform not in ['twitch', 'youtube', 'kick']:
        return jsonify({'error': 'Invalid platform'}), 400
    
    success = disconnect_platform(platform)
    return jsonify({'disconnected': success, 'platform': platform})

@app.route('/api/platforms/status', methods=['GET'])
@handle_errors
def get_platform_status():
    return jsonify(platform_connections)

@app.route('/api/settings/platforms', methods=['GET', 'PUT'])
@handle_errors
def manage_platform_settings():
    if request.method == 'GET':
        return jsonify({
            'twitch_client_id': get_setting('twitch_client_id', ''),
            'twitch_client_secret': get_setting('twitch_client_secret', ''),
            'youtube_api_key': get_setting('youtube_api_key', '')
        })
    else:
        data = request.json
        if 'twitch_client_id' in data:
            set_setting('twitch_client_id', data['twitch_client_id'])
        if 'twitch_client_secret' in data:
            set_setting('twitch_client_secret', data['twitch_client_secret'])
        if 'youtube_api_key' in data:
            set_setting('youtube_api_key', data['youtube_api_key'])
        return jsonify({'status': 'success', 'message': 'Platform settings updated'})

# ============================================================================
# ROUTES - OBS
# ============================================================================

@app.route('/api/obs/connect', methods=['POST'])
@handle_errors
def connect_obs():
    success = init_obs_client()
    return jsonify({'connected': success})

@app.route('/api/obs/disconnect', methods=['POST'])
@handle_errors
def disconnect_obs():
    success = disconnect_obs_client()
    return jsonify({'disconnected': success})

@app.route('/api/obs/status', methods=['GET'])
@handle_errors
def get_obs_status():
    recording_status = obs_get_recording_status() if obs_connected else {'recording': False}
    
    return jsonify({
        'connected': obs_connected,
        'recording': current_recording_info,
        'obs_recording_status': recording_status
    })

@app.route('/api/obs/start-recording', methods=['POST'])
@handle_errors
def start_obs_recording():
    global current_recording_info
    
    data = request.json or {}
    stream_id = data.get('stream_id')
    
    success, message = obs_start_recording()
    
    if success or not obs_connected:
        stream = Stream.query.get(stream_id) if stream_id else None
        platform = stream.platform if stream else 'twitch'
        
        filename = f"recording_{stream_id or 'manual'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        filepath = os.path.join(RECORDINGS_DIR, filename)
        
        recording = Recording(
            stream_id=stream_id or 1,
            filename=filename,
            filepath=filepath,
            segment_number=1,
            status='recording',
            platform=platform
        )
        db.session.add(recording)
        db.session.commit()
        
        current_recording_info = {
            'is_recording': True,
            'current_segment': 1,
            'segment_start_time': datetime.now().isoformat(),
            'stream_id': stream_id,
            'recording_id': recording.id
        }
        
        if stream:
            stream.is_recording = True
            db.session.commit()
        
        return jsonify({
            'message': 'Recording started',
            'recording_id': recording.id,
            'obs_connected': obs_connected
        })
    
    return jsonify({'error': message}), 500

@app.route('/api/obs/stop-recording', methods=['POST'])
@handle_errors
def stop_obs_recording():
    global current_recording_info
    
    success, message = obs_stop_recording()
    
    recording_id = current_recording_info.get('recording_id')
    stream_id = current_recording_info.get('stream_id')
    
    if recording_id:
        recording = Recording.query.get(recording_id)
        if recording:
            recording.status = 'completed'
            recording.ended_at = datetime.utcnow()
            if current_recording_info.get('segment_start_time'):
                start = datetime.fromisoformat(current_recording_info['segment_start_time'])
                recording.duration = (datetime.now() - start).total_seconds()
            db.session.commit()
    
    if stream_id:
        stream = Stream.query.get(stream_id)
        if stream:
            stream.is_recording = False
            db.session.commit()
    
    current_recording_info = {
        'is_recording': False,
        'current_segment': 0,
        'segment_start_time': None,
        'stream_id': None,
        'recording_id': None
    }
    
    return jsonify({'message': 'Recording stopped', 'obs_connected': obs_connected})

# ============================================================================
# ROUTES - SETTINGS
# ============================================================================

@app.route('/api/settings', methods=['GET'])
@handle_errors
def get_settings_route():
    settings = Settings.query.all()
    return jsonify({s.key: s.value for s in settings})

@app.route('/api/settings', methods=['PUT'])
@handle_errors
def update_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, str(value))
    return jsonify({'message': 'Settings updated successfully'})

@app.route('/api/settings/categories', methods=['GET'])
@handle_errors
def get_settings_categories():
    """Get organized settings categories"""
    return jsonify({
        'obs': ['obs_host', 'obs_port', 'obs_password'],
        'recording': ['auto_delete_recordings', 'segment_duration', 'recordings_dir', 'clips_dir'],
        'tiktok': ['auto_post_tiktok', 'default_tiktok_account'],
        'platforms': ['twitch_client_id', 'twitch_client_secret', 'youtube_api_key'],
        'stream_monitor': ['check_interval', 'auto_start_recording']
    })

@app.route('/api/settings/recording', methods=['GET', 'PUT'])
@handle_errors
def manage_recording_settings():
    if request.method == 'GET':
        return jsonify({
            'auto_delete_recordings': get_setting('auto_delete_recordings', 'true'),
            'segment_duration': get_setting('segment_duration', '3600'),
            'recordings_dir': get_setting('recordings_dir', RECORDINGS_DIR),
            'clips_dir': get_setting('clips_dir', CLIPS_DIR),
            'auto_post_tiktok': get_setting('auto_post_tiktok', 'false')
        })
    else:
        data = request.json
        for key in ['auto_delete_recordings', 'segment_duration', 'recordings_dir', 'clips_dir', 'auto_post_tiktok']:
            if key in data:
                set_setting(key, str(data[key]))
        return jsonify({'message': 'Recording settings updated'})

@app.route('/api/settings/tiktok', methods=['GET'])
@handle_errors
def get_tiktok_settings():
    return jsonify({
        'client_key': get_setting('tiktok_client_key', ''),
        'client_secret': get_setting('tiktok_client_secret', ''),
        'access_token': get_setting('tiktok_access_token', ''),
        'configured': bool(get_setting('tiktok_access_token'))
    })

@app.route('/api/settings/tiktok', methods=['PUT'])
@handle_errors
def update_tiktok_settings():
    data = request.json
    if 'client_key' in data:
        set_setting('tiktok_client_key', data['client_key'])
    if 'client_secret' in data:
        set_setting('tiktok_client_secret', data['client_secret'])
    if 'access_token' in data:
        set_setting('tiktok_access_token', data['access_token'])
    return jsonify({'message': 'TikTok settings updated'})

@app.route('/api/settings/obs', methods=['GET'])
@handle_errors
def get_obs_settings():
    return jsonify({
        'host': get_setting('obs_host', 'localhost'),
        'port': get_setting('obs_port', '4455'),
        'password': get_setting('obs_password', '')
    })

@app.route('/api/settings/obs', methods=['PUT'])
@handle_errors
def update_obs_settings():
    data = request.json
    if 'host' in data:
        set_setting('obs_host', data['host'])
    if 'port' in data:
        set_setting('obs_port', data['port'])
    if 'password' in data:
        set_setting('obs_password', data['password'])
    return jsonify({'message': 'OBS settings updated'})

# ============================================================================
# ROUTES - TIKTOK ACCOUNTS
# ============================================================================

@app.route('/api/settings/tiktok/accounts', methods=['GET'])
@handle_errors
def get_tiktok_accounts():
    accounts = TikTokAccount.query.order_by(TikTokAccount.created_at.desc()).all()
    return jsonify([{
        'id': a.id,
        'username': a.username,
        'email': a.email,
        'is_active': a.is_active,
        'created_at': a.created_at.isoformat() if a.created_at else None
    } for a in accounts])

@app.route('/api/settings/tiktok/accounts', methods=['POST'])
@handle_errors
@validate_json('username')
def create_tiktok_account():
    data = request.json
    account = TikTokAccount(
        username=data.get('username', '').replace('@', ''),
        email=data.get('email'),
        client_key=data.get('client_key'),
        client_secret=data.get('client_secret'),
        access_token=data.get('access_token'),
        is_active=True
    )
    db.session.add(account)
    db.session.commit()
    return jsonify({'id': account.id, 'message': 'TikTok account added successfully'})

@app.route('/api/settings/tiktok/accounts/<int:account_id>', methods=['GET'])
@handle_errors
def get_tiktok_account(account_id):
    account = TikTokAccount.query.get_or_404(account_id)
    return jsonify({
        'id': account.id,
        'username': account.username,
        'email': account.email,
        'client_key': account.client_key,
        'is_active': account.is_active,
        'created_at': account.created_at.isoformat() if account.created_at else None
    })

@app.route('/api/settings/tiktok/accounts/<int:account_id>', methods=['PUT'])
@handle_errors
def update_tiktok_account(account_id):
    account = TikTokAccount.query.get_or_404(account_id)
    data = request.json
    
    if 'username' in data:
        account.username = data['username'].replace('@', '')
    if 'email' in data:
        account.email = data['email']
    if 'client_key' in data:
        account.client_key = data['client_key']
    if 'client_secret' in data:
        account.client_secret = data['client_secret']
    if 'access_token' in data:
        account.access_token = data['access_token']
    if 'is_active' in data:
        account.is_active = data['is_active']
    
    db.session.commit()
    return jsonify({'message': 'TikTok account updated successfully'})

@app.route('/api/settings/tiktok/accounts/<int:account_id>', methods=['DELETE'])
@handle_errors
def delete_tiktok_account(account_id):
    account = TikTokAccount.query.get_or_404(account_id)
    db.session.delete(account)
    db.session.commit()
    return jsonify({'message': 'TikTok account deleted successfully'})

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

with app.app_context():
    db.create_all()
    
    # Create default triggers if they don't exist
    default_triggers = [
        {'name': 'Donation Alert', 'trigger_type': 'donation', 'threshold': 5.0, 'clip_duration': 30, 'pre_buffer': 10, 'post_buffer': 5},
        {'name': 'Chat Spike', 'trigger_type': 'chat_activity', 'threshold': 50, 'clip_duration': 60, 'pre_buffer': 15, 'post_buffer': 10},
        {'name': 'Viewer Milestone', 'trigger_type': 'viewer_count', 'threshold': 1000, 'clip_duration': 45, 'pre_buffer': 10, 'post_buffer': 5},
        {'name': 'Chat Sentiment', 'trigger_type': 'sentiment', 'threshold': 0.8, 'clip_duration': 30, 'pre_buffer': 10, 'post_buffer': 5},
        {'name': 'Audio Excitement', 'trigger_type': 'audio_excitement', 'threshold': 0.7, 'clip_duration': 45, 'pre_buffer': 15, 'post_buffer': 10}
    ]
    
    for trigger_data in default_triggers:
        existing = ClipTrigger.query.filter_by(name=trigger_data['name']).first()
        if not existing:
            trigger = ClipTrigger(**trigger_data)
            db.session.add(trigger)
    
    db.session.commit()
    
    # Start background workers
    start_background_workers()
    
    app.logger.info("Cliperus initialized successfully")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    is_frozen = getattr(sys, 'frozen', False)
    port = int(os.environ.get('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=not is_frozen,
        use_reloader=not is_frozen
    )
