import time
import threading
import requests
from datetime import datetime
import os

class StreamMonitor:
    """
    Monitor streams across Twitch, YouTube, and Kick platforms.
    Automatically starts recording when streams go live if auto_record is enabled.
    """
    
    def __init__(self, app, db, Stream, Settings, obs_wrapper):
        self.app = app
        self.db = db
        self.Stream = Stream
        self.Settings = Settings
        self.obs = obs_wrapper
        self.running = False
        self.thread = None
        self.check_interval = 60  # Check every 60 seconds
        self.logger = app.logger if hasattr(app, 'logger') else None
    
    def start(self):
        """Start the stream monitoring thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            self._log("Stream monitor started")
    
    def stop(self):
        """Stop the stream monitoring thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self._log("Stream monitor stopped")
    
    def _log(self, message):
        """Log message to app logger or print"""
        if self.logger:
            self.logger.info(message)
        else:
            print(f"[StreamMonitor] {message}")
    
    def _monitor_loop(self):
        """Main monitoring loop - runs continuously while self.running is True"""
        while self.running:
            try:
                with self.app.app_context():
                    # Get all streams that have auto_record enabled
                    streams = self.Stream.query.filter_by(auto_record=True).all()
                    
                    for stream in streams:
                        try:
                            is_live = self._check_stream_live(stream)
                            
                            # Only log status changes
                            if is_live != stream.is_live:
                                stream.is_live = is_live
                                self._log(f"Stream '{stream.name}' status changed: {'LIVE' if is_live else 'OFFLINE'}")
                                
                                # Auto-start recording if stream went live
                                if is_live and not stream.is_recording and stream.auto_record:
                                    self._log(f"Auto-starting recording for '{stream.name}'")
                                    self._auto_start_recording(stream)
                                
                                # Note: We don't auto-stop recordings when stream goes offline
                                # This allows capturing the end of stream and post-stream content
                        
                        except Exception as e:
                            self._log(f"Error checking stream '{stream.name}': {e}")
                    
                    # Commit all status changes
                    self.db.session.commit()
                    
            except Exception as e:
                self._log(f"Stream monitor error: {e}")
                try:
                    self.db.session.rollback()
                except:
                    pass
            
            # Wait before next check
            time.sleep(self.check_interval)
    
    def _check_stream_live(self, stream):
        """
        Check if a stream is currently live.
        Returns True if live, False otherwise.
        """
        try:
            platform = stream.platform.lower()
            
            if platform == 'twitch':
                client_id = self._get_setting('twitch_client_id')
                client_secret = self._get_setting('twitch_client_secret')
                return self._check_twitch(stream.name, client_id, client_secret)
            
            elif platform == 'youtube':
                api_key = self._get_setting('youtube_api_key')
                return self._check_youtube(stream.channel_url or stream.channel_id, api_key)
            
            elif platform == 'kick':
                return self._check_kick(stream.name)
            
            else:
                self._log(f"Unknown platform: {platform}")
                return False
                
        except Exception as e:
            self._log(f"Error checking {stream.platform} stream '{stream.name}': {e}")
            return False
    
    def _check_twitch(self, channel_name, client_id, client_secret=None):
        """
        Check if a Twitch channel is live using the Helix API.
        Requires Client ID and optionally Client Secret for OAuth token.
        """
        if not client_id:
            return False
        
        try:
            access_token = None
            
            # Get OAuth token if we have client_secret
            if client_secret:
                try:
                    token_response = requests.post(
                        'https://id.twitch.tv/oauth2/token',
                        params={
                            'client_id': client_id,
                            'client_secret': client_secret,
                            'grant_type': 'client_credentials'
                        },
                        timeout=10
                    )
                    
                    if token_response.status_code == 200:
                        access_token = token_response.json().get('access_token')
                except Exception as e:
                    self._log(f"Error getting Twitch OAuth token: {e}")
            
            # Build headers
            headers = {'Client-ID': client_id}
            if access_token:
                headers['Authorization'] = f'Bearer {access_token}'
            
            # Check stream status
            response = requests.get(
                f'https://api.twitch.tv/helix/streams?user_login={channel_name}',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json().get('data', [])
                return len(data) > 0
            else:
                self._log(f"Twitch API returned status {response.status_code} for '{channel_name}'")
                return False
            
        except Exception as e:
            self._log(f"Twitch API error for '{channel_name}': {e}")
            return False
    
    def _check_youtube(self, channel_identifier, api_key):
        """
        Check if a YouTube channel is live.
        channel_identifier can be a channel URL, channel ID, or username.
        """
        if not api_key or not channel_identifier:
            return False
        
        try:
            channel_id = None
            
            # Parse channel identifier
            if 'youtube.com' in channel_identifier or 'youtu.be' in channel_identifier:
                # Extract from URL
                if '/channel/' in channel_identifier:
                    channel_id = channel_identifier.split('/channel/')[-1].split('/')[0].split('?')[0]
                
                elif '/@' in channel_identifier:
                    # Handle @username format
                    username = channel_identifier.split('/@')[-1].split('/')[0].split('?')[0]
                    
                    # Convert username to channel ID
                    search_response = requests.get(
                        'https://www.googleapis.com/youtube/v3/search',
                        params={
                            'part': 'snippet',
                            'q': username,
                            'type': 'channel',
                            'key': api_key,
                            'maxResults': 1
                        },
                        timeout=10
                    )
                    
                    if search_response.status_code == 200:
                        items = search_response.json().get('items', [])
                        if items:
                            channel_id = items[0]['id']['channelId']
                        else:
                            return False
                    else:
                        return False
                
                elif '/c/' in channel_identifier or '/user/' in channel_identifier:
                    # Custom URL - need to search
                    username = channel_identifier.split('/c/' if '/c/' in channel_identifier else '/user/')[-1].split('/')[0].split('?')[0]
                    
                    search_response = requests.get(
                        'https://www.googleapis.com/youtube/v3/search',
                        params={
                            'part': 'snippet',
                            'q': username,
                            'type': 'channel',
                            'key': api_key,
                            'maxResults': 1
                        },
                        timeout=10
                    )
                    
                    if search_response.status_code == 200:
                        items = search_response.json().get('items', [])
                        if items:
                            channel_id = items[0]['id']['channelId']
                        else:
                            return False
                    else:
                        return False
            else:
                # Assume it's a channel ID
                channel_id = channel_identifier
            
            if not channel_id:
                return False
            
            # Check for live streams on this channel
            response = requests.get(
                'https://www.googleapis.com/youtube/v3/search',
                params={
                    'part': 'snippet',
                    'channelId': channel_id,
                    'eventType': 'live',
                    'type': 'video',
                    'key': api_key,
                    'maxResults': 1
                },
                timeout=10
            )
            
            if response.status_code == 200:
                items = response.json().get('items', [])
                return len(items) > 0
            else:
                self._log(f"YouTube API returned status {response.status_code}")
                return False
                
        except Exception as e:
            self._log(f"YouTube API error: {e}")
            return False
    
    def _check_kick(self, channel_name):
        """
        Check if a Kick channel is live using their public API.
        """
        try:
            response = requests.get(
                f'https://kick.com/api/v2/channels/{channel_name}',
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                livestream = data.get('livestream')
                
                # Check if livestream exists and is live
                if livestream:
                    return livestream.get('is_live', False)
                return False
            else:
                self._log(f"Kick API returned status {response.status_code} for '{channel_name}'")
                return False
                
        except Exception as e:
            self._log(f"Kick API error for '{channel_name}': {e}")
            return False
    
    def _get_setting(self, key):
        """Get a setting value from the database"""
        try:
            setting = self.Settings.query.filter_by(key=key).first()
            return setting.value if setting else None
        except:
            return None
    
    def _auto_start_recording(self, stream):
        """
        Trigger auto-start of recording when stream goes live.
        Creates a recording entry and starts OBS recording if connected.
        """
        try:
            # Import here to avoid circular dependency
            from datetime import datetime
            
            # Check if OBS is connected
            obs_connected = self.obs.get('connected') if self.obs else False
            
            if obs_connected:
                try:
                    from obswebsocket import requests as obs_requests
                    obs_client = self.obs.get('client')
                    if obs_client:
                        obs_client.call(obs_requests.StartRecord())
                        self._log(f"OBS recording started for '{stream.name}'")
                except Exception as e:
                    self._log(f"Error starting OBS recording: {e}")
            else:
                self._log(f"OBS not connected, creating recording entry only for '{stream.name}'")
            
            # Import Recording model
            from app import Recording, RECORDINGS_DIR, current_recording_info
            
            # Create recording entry
            filename = f"recording_{stream.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            filepath = os.path.join(RECORDINGS_DIR, filename)
            
            recording = Recording(
                stream_id=stream.id,
                filename=filename,
                filepath=filepath,
                segment_number=1,
                status='recording',
                platform=stream.platform
            )
            self.db.session.add(recording)
            
            # Update stream status
            stream.is_recording = True
            
            # Update global recording info
            current_recording_info.update({
                'is_recording': True,
                'current_segment': 1,
                'segment_start_time': datetime.now().isoformat(),
                'stream_id': stream.id,
                'recording_id': recording.id
            })
            
            self.db.session.commit()
            self._log(f"Recording entry created for stream '{stream.name}' (ID: {recording.id})")
            
        except Exception as e:
            self._log(f"Error auto-starting recording for '{stream.name}': {e}")
            try:
                self.db.session.rollback()
            except:
                pass
