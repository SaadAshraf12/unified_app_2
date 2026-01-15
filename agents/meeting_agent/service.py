"""
Meeting Agent Service - Adapted from MS TEAMS PROJECT/latest.py
Processes Teams meeting transcripts and creates ClickUp tasks
"""
import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from models import db, ProcessedMeeting

# API Endpoints
GRAPH_API = "https://graph.microsoft.com/v1.0"
CLICKUP_API = "https://api.clickup.com/api/v2"
CLICKUP_API_V3 = "https://api.clickup.com/api/v3"


class MeetingAgentService:
    """Service for processing meetings and creating ClickUp tasks."""
    
    def __init__(self, user):
        self.user = user
        self.config = user.meeting_config
        self.settings = user.settings
        self.logs = []
        
        # Get API keys
        self.clickup_api_key = self.settings.clickup_api_key
        self.openai_api_key = self.settings.openai_api_key or os.getenv('OPENAI_API_KEY')
        self.ms_access_token = self.settings.ms_access_token
        
        # Cache for ClickUp data
        self.clickup_users = {}
        self.clickup_tasks = []
    
    async def process_meetings(self):
        """Main entry point for meeting processing."""
        # Run synchronously since Graph API calls are sync
        return self._process_meetings_sync()
    
    def _process_meetings_sync(self):
        """Synchronous meeting processing."""
        result = {
            'success': False,
            'meetings_checked': 0,
            'tasks_created': 0,
            'summaries_created': 0,
            'logs': [],
            'error': None
        }
        
        if not self.clickup_api_key or not self.ms_access_token:
            result['error'] = 'Missing API credentials'
            return result
        
        try:
            # Refresh access token if needed
            from utils.ms_auth import get_valid_access_token
            access_token = get_valid_access_token(self.settings, db)
            if not access_token:
                result['error'] = 'Microsoft access token expired. Please re-authenticate.'
                return result
            
            # Use the refreshed token
            self.ms_access_token = access_token
            headers = {"Authorization": f"Bearer {access_token}"}
            
            # Get ClickUp data
            self.logs.append("--- FETCHING CLICKUP DATA ---")
            self._get_clickup_members()
            self._get_active_tasks()
            
            # Calculate time range
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=self.config.scan_days_back or 2)
            start_iso = start.strftime('%Y-%m-%dT%H:%M:%SZ')
            end_iso = end.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            self.logs.append(f"--- SCANNING MEETINGS ({start_iso} to {end_iso}) ---")
            
            # Get calendar events and meetings
            cal_events = self._get_calendar_events(headers, start_iso, end_iso)
            chat_meetings = self._get_recent_chats(headers, start_iso)
            
            # Deduplicate by join URL
            unique_meetings = {}
            for ev in cal_events:
                url = self._extract_join_url(ev)
                if url:
                    unique_meetings[url] = {
                        "joinUrl": url,
                        "subject": ev.get("subject", "Untitled Event"),
                        "start_time": ev.get("start", {}).get("dateTime"),
                        "end_time": ev.get("end", {}).get("dateTime")
                    }
            
            for chat in chat_meetings:
                url = chat["joinUrl"]
                if url not in unique_meetings:
                    unique_meetings[url] = {
                        "joinUrl": url,
                        "subject": chat["subject"],
                        "start_time": None,
                        "end_time": None
                    }
            
            result['meetings_checked'] = len(unique_meetings)
            self.logs.append(f"🔍 Unique Meetings Found: {len(unique_meetings)}")
            
            # Load processed transcripts
            processed_ids = set(
                m.transcript_id for m in ProcessedMeeting.query.filter_by(user_id=self.user.id).all()
            )
            
            tasks_created = 0
            summaries_created = 0
            processed_mids = set()
            
            # Get excluded meeting names
            excluded_names = [n.lower() for n in (self.config.excluded_meeting_names or [])]
            
            for item in unique_meetings.values():
                subject = item["subject"]
                
                # Check if meeting should be excluded
                if excluded_names:
                    should_exclude = any(excl in subject.lower() for excl in excluded_names)
                    if should_exclude:
                        self.logs.append(f"⏭️ Skipping excluded meeting: {subject[:40]}")
                        continue
                
                mid = self._get_meeting_id_by_join_url(headers, item["joinUrl"])
                if mid and mid not in processed_mids:
                    tc, sc = self._process_single_meeting(
                        headers, mid, subject, processed_ids,
                        item.get("start_time"), item.get("end_time")
                    )
                    tasks_created += tc
                    summaries_created += sc
                    processed_mids.add(mid)
            
            db.session.commit()
            
            result['success'] = True
            result['tasks_created'] = tasks_created
            result['summaries_created'] = summaries_created
            result['logs'] = self.logs
            
        except Exception as e:
            result['error'] = str(e)
            result['logs'] = self.logs
        
        return result
    
    def _get_clickup_members(self):
        """Get ClickUp team members."""
        if not self.clickup_api_key:
            return
        
        headers = {"Authorization": self.clickup_api_key}
        try:
            resp = requests.get(f"{CLICKUP_API}/team", headers=headers)
            if resp.status_code == 200:
                teams = resp.json().get('teams', [])
                if teams:
                    for m in teams[0].get('members', []):
                        user = m.get('user', {})
                        uid = user.get('id')
                        if uid:
                            if user.get('username'):
                                self.clickup_users[user.get('username').lower()] = uid
                            if user.get('email'):
                                self.clickup_users[user.get('email').lower()] = uid
                    self.logs.append(f"👥 Loaded {len(self.clickup_users)} ClickUp users.")
        except Exception as e:
            self.logs.append(f"❌ Error loading ClickUp members: {e}")
    
    def _get_active_tasks(self):
        """Get active ClickUp tasks for deduplication."""
        if not self.clickup_api_key or not self.config.clickup_list_id:
            return
        
        headers = {"Authorization": self.clickup_api_key}
        params = {"archived": "false", "subtasks": "true"}
        
        try:
            resp = requests.get(
                f"{CLICKUP_API}/list/{self.config.clickup_list_id}/task",
                headers=headers, params=params
            )
            if resp.status_code == 200:
                for t in resp.json().get('tasks', []):
                    self.clickup_tasks.append({
                        'name': t['name'],
                        'description': (t.get('description') or "")[:300]
                    })
        except Exception:
            pass
    
    def _get_calendar_events(self, headers, start_iso, end_iso):
        """Get calendar events from Graph API."""
        url = f"{GRAPH_API}/me/calendarView?startDateTime={start_iso}&endDateTime={end_iso}&$select=id,subject,start,end,onlineMeeting,onlineMeetingUrl,bodyPreview"
        events = []
        
        while True:
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                return events
            data = resp.json()
            events.extend(data.get("value", []))
            if not data.get("@odata.nextLink"):
                break
            url = data.get("@odata.nextLink")
        
        return events
    
    def _get_recent_chats(self, headers, start_iso):
        """Get recent chats with meetings."""
        url = f"{GRAPH_API}/me/chats?$top=20"
        chats = []
        
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            
            try:
                start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
            except:
                start_dt = datetime.now(timezone.utc) - timedelta(days=2)
            
            for chat in resp.json().get("value", []):
                updated_at_str = chat.get("lastUpdatedDateTime")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        if updated_at < start_dt:
                            continue
                    except:
                        pass
                
                online_info = chat.get("onlineMeetingInfo")
                if online_info and online_info.get("joinWebUrl"):
                    subject = chat.get("topic") or "Untitled Call"
                    chats.append({
                        "id": chat.get("id"),
                        "subject": subject,
                        "joinUrl": online_info.get("joinWebUrl")
                    })
        except Exception as e:
            self.logs.append(f"❌ Error fetching chats: {e}")
        
        return chats
    
    def _extract_join_url(self, ev):
        """Extract Teams join URL from event."""
        jm = ev.get("onlineMeeting") or {}
        if isinstance(jm, dict) and jm.get("joinUrl"):
            return jm.get("joinUrl")
        url = ev.get("onlineMeetingUrl")
        if url:
            return url
        bp = ev.get("bodyPreview") or ""
        m = re.search(r"https://teams\.microsoft\.com/[^\s\"]+", bp)
        if m:
            return m.group(0)
        return None
    
    def _get_meeting_id_by_join_url(self, headers, join_url):
        """Get meeting ID from join URL."""
        from urllib.parse import quote
        
        encoded = quote(join_url, safe="")
        url = f"{GRAPH_API}/me/onlineMeetings?$filter=JoinWebUrl%20eq%20'{encoded}'"
        
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                if items:
                    return items[0]["id"]
        except:
            pass
        return None
    
    def _process_single_meeting(self, headers, meeting_id, subject, processed_ids, start_time, end_time):
        """Process a single meeting's transcripts."""
        tasks_created = 0
        summaries_created = 0
        
        # Get transcripts
        transcripts = self._get_transcripts_metadata(headers, meeting_id)
        if not transcripts:
            return 0, 0
        
        for t_meta in transcripts:
            transcript_id = t_meta['id']
            transcript_date = t_meta.get('createdDateTime', '')
            
            if transcript_id in processed_ids:
                continue
            
            self.logs.append(f"🆕 Found NEW transcript for '{subject[:30]}' (Date: {transcript_date})")
            
            # Download transcript
            transcript_text = self._download_transcript(headers, meeting_id, transcript_id)
            if not transcript_text:
                self.logs.append(f"❌ Failed to download transcript {transcript_id}")
                continue
            
            self.logs.append(f"✓ Transcript downloaded ({len(transcript_text)} chars)")
            
            # Check if standup meeting
            is_standup = any(
                kw.lower() in subject.lower() 
                for kw in self.config.standup_meeting_keywords
            )
            
            if is_standup:
                self.logs.append(f"📋 Generating standup summary...")
                summary = self._extract_standup_summary(transcript_text, transcript_date)
                if summary:
                    if self._write_summary_to_clickup(summary):
                        summaries_created += 1
                        self.logs.append("✅ Standup summary written to ClickUp.")
            
            # Extract and create tasks
            tasks = self._extract_tasks(transcript_text)
            if tasks:
                self.logs.append(f"🚀 Found {len(tasks)} tasks")
                for task in tasks:
                    if self._create_clickup_task(task, subject, headers, start_time, end_time):
                        tasks_created += 1
            
            # Log processed meeting
            processed = ProcessedMeeting(
                user_id=self.user.id,
                transcript_id=transcript_id,
                meeting_subject=subject[:500],
                tasks_created=len(tasks) if tasks else 0,
                standup_summary_created=is_standup and summaries_created > 0
            )
            db.session.add(processed)
        
        return tasks_created, summaries_created
    
    def _get_transcripts_metadata(self, headers, meeting_id):
        """Get list of transcripts for a meeting."""
        url = f"{GRAPH_API}/me/onlineMeetings/{meeting_id}/transcripts"
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                transcripts = resp.json().get("value", [])
                transcripts.sort(key=lambda x: x.get('createdDateTime', ''), reverse=True)
                return transcripts
        except:
            pass
        return []
    
    def _download_transcript(self, headers, meeting_id, transcript_id):
        """Download transcript content."""
        url = f"{GRAPH_API}/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content?$format=text/vtt"
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                return self._vtt_to_text(resp.text)
        except:
            pass
        return None
    
    def _vtt_to_text(self, vtt):
        """Convert VTT to plain text."""
        lines = []
        for line in vtt.splitlines():
            s = line.strip()
            if not s or "-->" in s or s in ["WEBVTT", "NOTE"]:
                continue
            if re.match(r"^\d+$", s):
                continue
            s = re.sub(r"<v ([^>]+)>", r"\1: ", s)
            s = re.sub(r"<[^>]+>", "", s)
            lines.append(s)
        return "\n".join(lines)
    
    def _extract_tasks(self, text):
        """Extract tasks from transcript using OpenAI."""
        if not self.openai_api_key:
            return []
        
        client = OpenAI(api_key=self.openai_api_key)
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        system_prompt = (
            f"You are an expert Project Manager. Today's date is {today_str}. "
            "Analyze the transcript. Extract actionable WORK tasks. Output JSON:\n"
            "{\n"
            "  \"summary\": \"Brief summary.\",\n"
            "  \"tasks\": [\n"
            "    {\n"
            "      \"title\": \"Concise Task Name\",\n"
            "      \"assignee_name\": \"Name or 'Unassigned'\",\n"
            "      \"description\": \"Context.\",\n"
            "      \"due_date_YYYY_MM_DD\": \"YYYY-MM-DD or null\",\n"
            "      \"priority_level\": \"Urgent/High/Normal/Low or null\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
        
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Transcript:\n{text[:25000]}"}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            result = json.loads(resp.choices[0].message.content)
            return result.get("tasks", [])
        except Exception as e:
            self.logs.append(f"❌ AI Error: {e}")
            return []
    
    def _extract_standup_summary(self, text, meeting_date=None):
        """Extract standup summary from transcript."""
        if not self.openai_api_key:
            return None
        
        client = OpenAI(api_key=self.openai_api_key)
        
        if not meeting_date:
            meeting_date = datetime.now().strftime("%Y-%m-%d")
        else:
            try:
                dt = datetime.fromisoformat(meeting_date.replace('Z', '+00:00'))
                meeting_date = dt.strftime("%Y-%m-%d")
            except:
                meeting_date = datetime.now().strftime("%Y-%m-%d")
        
        system_prompt = (
            f"Extract standup updates from the transcript.\n\n"
            f"Format:\nDate: {meeting_date}\n[Person Name]\n"
            f"What I did Yesterday? [update]\nWhat I will work on today? [update]\n"
            f"Do I need help from anyone? [Yes/No and details]\n\n"
            f"Extract for each person who spoke. Use plain text, no markdown."
        )
        
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Transcript:\n{text[:25000]}"}
                ],
                temperature=0.3
            )
            return resp.choices[0].message.content
        except Exception as e:
            self.logs.append(f"❌ AI Error: {e}")
            return None
    
    def _write_summary_to_clickup(self, summary_text):
        """Write standup summary to ClickUp doc."""
        if not self.config.target_space_id or not self.config.target_doc_name:
            self.logs.append("⚠️ ClickUp doc not configured for standup summaries")
            return False
        
        self.logs.append(f"📝 Writing to ClickUp Doc: Space={self.config.target_space_id}, Doc='{self.config.target_doc_name}'")
        
        headers = {
            "Authorization": self.clickup_api_key,
            "Content-Type": "application/json"
        }
        
        try:
            # Get workspace ID
            resp = requests.get(f"{CLICKUP_API}/team", headers=headers)
            if resp.status_code != 200:
                self.logs.append(f"❌ Failed to get workspace: {resp.status_code}")
                return False
            
            teams = resp.json().get("teams", [])
            if not teams:
                self.logs.append("❌ No workspaces found")
                return False
            
            workspace_id = teams[0]["id"]
            self.logs.append(f"✓ Workspace ID: {workspace_id}")
            
            # Search for docs in space
            docs_url = f"{CLICKUP_API_V3}/workspaces/{workspace_id}/docs"
            params = {"parent_id": self.config.target_space_id, "parent_type": 4}
            
            self.logs.append(f"📂 Searching docs in space {self.config.target_space_id}...")
            resp = requests.get(docs_url, headers=headers, params=params)
            if resp.status_code != 200:
                self.logs.append(f"❌ Failed to list docs: {resp.status_code} - {resp.text[:200]}")
                return False
            
            docs = resp.json().get("docs", [])
            self.logs.append(f"✓ Found {len(docs)} docs in space")
            
            # Find target doc
            target_doc = None
            for doc in docs:
                doc_name = doc.get("name", "")
                self.logs.append(f"   - Doc: '{doc_name}'")
                if doc_name.lower() == self.config.target_doc_name.lower():
                    target_doc = doc
                    break
            
            if not target_doc:
                self.logs.append(f"❌ Doc '{self.config.target_doc_name}' not found in space")
                return False
            
            doc_id = target_doc['id']
            self.logs.append(f"✓ Found target doc: ID={doc_id}")
            
            # Get page ID
            pages_url = f"{CLICKUP_API_V3}/workspaces/{workspace_id}/docs/{doc_id}/pages"
            resp = requests.get(pages_url, headers=headers)
            if resp.status_code != 200:
                self.logs.append(f"❌ Failed to get pages: {resp.status_code}")
                return False
            
            pages_data = resp.json()
            pages = pages_data if isinstance(pages_data, list) else pages_data.get('pages', [])
            if not pages:
                self.logs.append("❌ Doc has no pages")
                return False
            
            page_id = pages[0].get('id')
            self.logs.append(f"✓ First page ID: {page_id}")
            
            # Update page content
            update_url = f"{CLICKUP_API_V3}/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}"
            payload = {
                "content": f"\n\n---\n\n{summary_text}",
                "content_edit_mode": "append",
                "content_format": "text/md"
            }
            
            self.logs.append(f"📤 Appending summary to page...")
            resp = requests.put(update_url, headers=headers, json=payload)
            
            if resp.status_code in [200, 204]:
                self.logs.append("✅ Summary successfully written to ClickUp Doc!")
                return True
            else:
                self.logs.append(f"❌ Failed to update doc: {resp.status_code} - {resp.text[:300]}")
                return False
            
        except Exception as e:
            self.logs.append(f"❌ ClickUp Doc Error: {e}")
            return False

    
    def _create_clickup_task(self, task_data, meeting_subject, graph_headers, start_time=None, end_time=None):
        """Create a ClickUp task."""
        task_name = f"{task_data.get('title')} | {meeting_subject}"
        ai_assignee = task_data.get('assignee_name', 'Unassigned')
        
        full_description = (
            f"**Source Meeting:** {meeting_subject}\n"
            f"**Assignee via Transcript:** {ai_assignee}\n"
            f"**Context:**\n{task_data.get('description', '')}\n"
        )
        
        # Check for duplicate
        if self._is_semantic_duplicate(task_name, full_description):
            self.logs.append(f"⏭️ Skipping Duplicate: {task_name[:40]}")
            return False
        
        # Resolve assignee
        assignee_id = None
        if ai_assignee.lower() not in ["unassigned", "me", "unknown"]:
            assignee_id = self.clickup_users.get(ai_assignee.lower())
        
        assignees_list = [assignee_id] if assignee_id else []
        
        # Priority
        priority_map = {"urgent": 1, "high": 2, "normal": 3, "low": 4}
        p_text = (task_data.get("priority_level") or "normal").lower()
        priority_val = priority_map.get(p_text, 3)
        
        # Due date
        due_date_ts = None
        date_str = task_data.get("due_date_YYYY_MM_DD")
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                due_date_ts = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            except:
                pass
        
        payload = {
            "name": task_name,
            "description": full_description,
            "status": "TO DO",
            "priority": priority_val,
            "assignees": assignees_list,
            "due_date": due_date_ts
        }
        
        try:
            headers = {"Authorization": self.clickup_api_key, "Content-Type": "application/json"}
            resp = requests.post(
                f"{CLICKUP_API}/list/{self.config.clickup_list_id}/task",
                headers=headers,
                json=payload
            )
            
            if resp.status_code == 200:
                self.logs.append(f"✅ Created: {task_name[:40]}")
                return True
            else:
                self.logs.append(f"❌ ClickUp Error: {resp.status_code}")
                return False
        except Exception as e:
            self.logs.append(f"❌ Error: {e}")
            return False
    
    def _is_semantic_duplicate(self, new_title, new_desc):
        """Check if task is a duplicate."""
        if not self.clickup_tasks or not self.openai_api_key:
            return False
        
        # Quick check
        for t in self.clickup_tasks[:30]:
            if t['name'].lower() == new_title.lower():
                return True
        
        client = OpenAI(api_key=self.openai_api_key)
        existing_str = "\n".join([f"{i+1}. {t['name']}" for i, t in enumerate(self.clickup_tasks[:30])])
        
        prompt = (
            "Strict task deduplication.\n"
            f"New Task: '{new_title}'\n"
            f"Existing Tasks:\n{existing_str}\n\n"
            "Is the New Task semantically identical to any Existing Task?\n"
            "JSON: {\"is_duplicate\": true/false}"
        )
        
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            result = json.loads(resp.choices[0].message.content)
            return result.get("is_duplicate", False)
        except:
            return False
