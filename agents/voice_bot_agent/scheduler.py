import logging
from datetime import datetime, timezone, timedelta
from dateutil import parser
import requests

from app import app
from models import db, User, BotConfig
from agents.meeting_agent.service import MeetingAgentService
from agents.voice_bot_agent.recall_api import create_bot_sync, list_bots_sync
from agents.voice_bot_agent.server_manager import VoiceServerManager
from utils.ms_auth import get_valid_access_token

logger = logging.getLogger(__name__)

def check_and_join_meetings(user_id):
    """
    Check for upcoming meetings and auto-join if enabled.
    """
    logger.info(f"checking schedule for user {user_id}")
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user or not user.bot_config or not user.bot_config.is_enabled:
            logger.info("Bot disabled for user")
            return {"status": "disabled"}
            
        token = get_valid_access_token(user.settings, db)
        if not token:
            logger.warning("No Access Token")
            return {"status": "no_token"}
            
        ms_service = MeetingAgentService(user)
        headers = {"Authorization": f"Bearer {token}"}
        
        # Time window: Look 5 minutes ahead
        now = datetime.now(timezone.utc)
        start_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = (now + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        events = ms_service._get_calendar_events(headers, start_str, end_str)
        logger.info(f"Found {len(events)} events in window")
        
        recall_token = user.bot_config.recall_ai_token
        active_bots_data = list_bots_sync(token=recall_token)
        active_bots = active_bots_data.get('results', [])
        if 'bots' in active_bots_data:
             active_bots = active_bots_data['bots'].get('results', [])
        
        joined_urls = set()
        for b in active_bots:
            m_url = b.get('meeting_url')
            if isinstance(m_url, dict):
                 pass
            elif isinstance(m_url, str):
                joined_urls.add(m_url)

        joined_count = 0
        
        for event in events:
            # DEBUG: Log raw event basics
            subj = event.get('subject') or "No Subject"
            
            # Deep Debug of Payload
            is_online = event.get('isOnlineMeeting')
            om_url = event.get('onlineMeetingUrl')
            om_prop = event.get('onlineMeeting')
            body_prev = event.get('bodyPreview') or ""
            
            logger.info(f"Processing '{subj}' (ID: {event.get('id')[-5:]})")
            logger.info(f"   -> isOnline: {is_online} | URL: {om_url}")
            logger.info(f"   -> onlineMeeting Prop: {om_prop}")
            logger.info(f"   -> Body Preview: {body_prev[:50]}...")

            join_url = ms_service._extract_join_url(event)
            if not join_url:
                logger.warning(f"-> Skipped: No Join URL found for '{event.get('subject')}'")
                continue
                
            subject = event.get('subject', 'Untitled')
            # DEBUG: Log found URL
            logger.info(f"-> Found URL: {join_url[:30]}...")
            
            start_dt_str = event['start']['dateTime']
            
            try:
                start_dt = parser.isoparse(start_dt_str)
                if not start_dt.tzinfo:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                else:
                    start_dt = start_dt.astimezone(timezone.utc)
            except Exception as e:
                logger.error(f"-> Skipped: Date parse error for '{subject}': {e}")
                continue

            time_to_meeting = (start_dt - now).total_seconds()
            logger.info(f"Event: {subject}, Starts in: {time_to_meeting:.1f}s")
            
            if -300 < time_to_meeting < 180:
                if join_url in joined_urls:
                    logger.info("-> Already joined")
                    continue
                
                logger.info("-> JOINING!")
                
                # 1. Start Server (if local)
                VoiceServerManager.start_server()
                
                # 2. Create Bot
                create_bot_sync(
                    meeting_url=join_url,
                    bot_name=user.bot_config.bot_name or "Alex",
                    client_webpage_url=user.bot_config.voice_bot_client_url,
                    websocket_url=user.bot_config.voice_bot_websocket_url,
                    token=recall_token
                )
                joined_count += 1
                
        return {"status": "success", "joined": joined_count}
