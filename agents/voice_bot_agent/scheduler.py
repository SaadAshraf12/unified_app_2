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
    Now checks BOTH calendar events AND recent chats (for Meet Now/channel meetings).
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
        GRAPH_API = "https://graph.microsoft.com/v1.0"
        
        # Time window
        now = datetime.now(timezone.utc)
        start_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = (now + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # 1. Get Calendar Events
        cal_events = ms_service._get_calendar_events(headers, start_str, end_str)
        logger.info(f"Found {len(cal_events)} calendar events")
        
        # 2. Get Recent Chats (catches Meet Now, channel meetings)
        chat_meetings = ms_service._get_recent_chats(headers, start_str)
        logger.info(f"Found {len(chat_meetings)} chat meetings")
        
        # 3. Combine into unique meetings by join URL
        unique_meetings = {}
        
        for ev in cal_events:
            join_url = ms_service._extract_join_url(ev)
            
            # Fallback: Fetch full event if missing URL
            if not join_url:
                try:
                    full_resp = requests.get(f"{GRAPH_API}/me/events/{ev['id']}", headers=headers)
                    if full_resp.status_code == 200:
                        full_event = full_resp.json()
                        join_url = ms_service._extract_join_url(full_event)
                except:
                    pass
            
            if join_url:
                unique_meetings[join_url] = {
                    "joinUrl": join_url,
                    "subject": ev.get("subject") or "Calendar Event",
                    "start_time": ev.get("start", {}).get("dateTime")
                }
        
        for chat in chat_meetings:
            url = chat.get("joinUrl")
            if url and url not in unique_meetings:
                unique_meetings[url] = {
                    "joinUrl": url,
                    "subject": chat.get("subject") or "Teams Call",
                    "start_time": None  # Chats don't have start time
                }
        
        logger.info(f"Total unique meetings to check: {len(unique_meetings)}")
        
        # 4. Get already joined bots
        recall_token = user.bot_config.recall_ai_token
        active_bots_data = list_bots_sync(token=recall_token)
        active_bots = active_bots_data.get('results', [])
        if 'bots' in active_bots_data:
             active_bots = active_bots_data['bots'].get('results', [])
        
        joined_urls = set()
        for b in active_bots:
            m_url = b.get('meeting_url')
            if isinstance(m_url, str):
                joined_urls.add(m_url)

        joined_count = 0
        
        # 5. Process each meeting
        for meeting in unique_meetings.values():
            join_url = meeting["joinUrl"]
            subject = meeting["subject"]
            start_time_str = meeting.get("start_time")
            
            logger.info(f"Checking: '{subject}' | URL: {join_url[:40]}...")
            
            # Check if already joined
            if join_url in joined_urls:
                logger.info("   -> Already joined, skipping")
                continue
            
            # Time check (only for calendar events with start time)
            if start_time_str:
                try:
                    start_dt = parser.isoparse(start_time_str)
                    if not start_dt.tzinfo:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    else:
                        start_dt = start_dt.astimezone(timezone.utc)
                    
                    time_to_meeting = (start_dt - now).total_seconds()
                    logger.info(f"   -> Starts in: {time_to_meeting:.0f}s")
                    
                    # Only join if within window: 5 min before to 3 min after
                    if not (-300 < time_to_meeting < 180):
                        logger.info("   -> Outside time window, skipping")
                        continue
                except Exception as e:
                    logger.warning(f"   -> Date parse error: {e}")
            else:
                # For chat meetings without start time, always try to join
                logger.info("   -> Chat meeting (no start time), attempting join...")
            
            # JOIN!
            logger.info(f"   -> JOINING '{subject}'!")
            
            VoiceServerManager.start_server()
            
            create_bot_sync(
                meeting_url=join_url,
                bot_name=user.bot_config.bot_name or "Alex",
                client_webpage_url=user.bot_config.voice_bot_client_url,
                websocket_url=user.bot_config.voice_bot_websocket_url,
                token=recall_token
            )
            joined_count += 1
                
        return {"status": "success", "joined": joined_count}
