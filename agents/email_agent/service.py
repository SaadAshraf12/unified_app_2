"""
Email Agent Service - Adapted from outlook project/main.py
Processes emails and creates ClickUp tasks
"""
import os
import json
import httpx
import difflib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
from models import db, ProcessedEmail

# Timezone
CENTRAL_TZ = ZoneInfo("America/Chicago")

# API Endpoints
GRAPH_API = "https://graph.microsoft.com/v1.0"
CLICKUP_API = "https://api.clickup.com/api/v2"


class EmailAgentService:
    """Service for processing emails and creating ClickUp tasks."""
    
    def __init__(self, user):
        self.user = user
        self.config = user.email_config
        self.settings = user.settings
        self.logs = []
        
        # Get API keys
        self.clickup_api_key = self.settings.clickup_api_key
        self.openai_api_key = self.settings.openai_api_key or os.getenv('OPENAI_API_KEY')
        self.ms_access_token = self.settings.ms_access_token
        
        # Cache for ClickUp data
        self.clickup_users = {}
        self.clickup_names_list = []
        self.clickup_tasks = []
    
    async def process_emails(self):
        """Main entry point for email processing."""
        result = {
            'success': False,
            'emails_checked': 0,
            'tasks_created': 0,
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
            
            # Update the token for this session
            self.ms_access_token = access_token
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get current user email
                headers = {"Authorization": f"Bearer {access_token}"}
                my_email = await self._get_current_user_email(client, headers)
                self.logs.append(f"👤 User: {my_email}")
                
                # Refresh ClickUp cache
                await self._refresh_clickup_cache(client)
                self.logs.append(f"👥 ClickUp Users: {len(self.clickup_users)}")
                
                my_id = self.clickup_users.get(my_email.lower()) if my_email else None
                
                # Get recent emails
                emails = await self._get_recent_emails(client, headers)
                result['emails_checked'] = len(emails)
                self.logs.append(f"📧 Recent Emails: {len(emails)}")
                
                # Load processed emails log
                processed_ids = set(
                    e.email_id for e in ProcessedEmail.query.filter_by(user_id=self.user.id).all()
                )
                
                tasks_created = 0
                
                for email in emails:
                    msg_id = email['id']
                    if msg_id in processed_ids:
                        continue
                    
                    subject = email.get('subject', 'No Subject')
                    sender = email.get('from', {}).get('emailAddress', {})
                    s_email = sender.get('address', '').lower()
                    
                    # Check if sender is allowed
                    if self.config.allowed_senders and s_email not in [s.lower() for s in self.config.allowed_senders]:
                        continue
                    
                    # Check for sensitive keywords
                    if any(w in subject.lower() for w in self.config.sensitive_keywords):
                        self.logs.append(f"🔒 Sensitive: {subject[:50]}")
                        continue
                    
                    # Check ignore prefixes
                    if any(subject.startswith(p) for p in self.config.ignore_subject_prefixes):
                        continue
                    
                    self.logs.append(f"Processing: {subject[:50]}")
                    
                    # Get email body
                    full_text = self._clean_html_body(email.get('body', {}).get('content', ''))
                    
                    # Analyze with AI
                    ai_result = await self._analyze_email_with_openai(
                        sender.get('name', 'Unknown'),
                        subject,
                        full_text
                    )
                    
                    email_tasks_created = 0
                    
                    if ai_result and ai_result.get('is_actionable'):
                        tasks = ai_result.get('tasks', [])
                        self.logs.append(f"🚀 {len(tasks)} tasks in '{subject[:30]}'")
                        
                        for task in tasks:
                            created = await self._create_clickup_task(
                                client, task, subject, sender.get('name'), s_email, my_id
                            )
                            if created:
                                email_tasks_created += 1
                                tasks_created += 1
                    else:
                        self.logs.append("💤 No actions.")
                    
                    # Log processed email
                    processed = ProcessedEmail(
                        user_id=self.user.id,
                        email_id=msg_id,
                        subject=subject[:500],
                        sender=s_email,
                        tasks_created=email_tasks_created
                    )
                    db.session.add(processed)
                
                db.session.commit()
                
                result['success'] = True
                result['tasks_created'] = tasks_created
                result['logs'] = self.logs
                
        except Exception as e:
            result['error'] = str(e)
            result['logs'] = self.logs
        
        return result
    
    async def _get_current_user_email(self, client, headers):
        """Get current user's email from Graph API."""
        resp = await client.get(f"{GRAPH_API}/me", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("mail") or data.get("userPrincipalName")
        return None
    
    async def _get_recent_emails(self, client, headers):
        """Get recent emails from inbox."""
        url = f"{GRAPH_API}/me/mailFolders/inbox/messages?$top=30&$select=id,subject,body,from,receivedDateTime,hasAttachments,toRecipients,ccRecipients&$orderby=receivedDateTime desc"
        response = await client.get(url, headers=headers)
        return response.json().get('value', []) if response.status_code == 200 else []
    
    async def _refresh_clickup_cache(self, client):
        """Refresh ClickUp users and tasks cache."""
        if not self.clickup_api_key:
            return
        
        headers = {"Authorization": self.clickup_api_key}
        
        try:
            # Fetch team members
            resp = await client.get(f"{CLICKUP_API}/team", headers=headers)
            teams = resp.json().get('teams', [])
            
            if teams:
                for m in teams[0].get('members', []):
                    user = m.get('user', {})
                    uid = user.get('id')
                    username = user.get('username')
                    if uid:
                        if username:
                            self.clickup_users[username.lower()] = uid
                            self.clickup_names_list.append(username)
                        if user.get('email'):
                            self.clickup_users[user.get('email').lower()] = uid
            
            # Fetch active tasks
            if self.config.clickup_list_id:
                params = {"archived": "false", "subtasks": "true", "page": 0}
                resp = await client.get(
                    f"{CLICKUP_API}/list/{self.config.clickup_list_id}/task",
                    headers=headers,
                    params=params
                )
                for t in resp.json().get('tasks', []):
                    desc = t.get('description', '') or ""
                    self.clickup_tasks.append({
                        'id': t['id'],
                        'name': t['name'],
                        'description': desc[:400],
                        'parent_id': t.get('parent')
                    })
        except Exception as e:
            self.logs.append(f"❌ ClickUp cache error: {e}")
    
    def _clean_html_body(self, html_content):
        """Clean HTML email body."""
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=' ', strip=True)
        return text[:30000]
    
    async def _analyze_email_with_openai(self, sender, subject, full_text):
        """Analyze email with OpenAI to extract tasks."""
        if not self.openai_api_key:
            return None
        
        client = AsyncOpenAI(api_key=self.openai_api_key)
        
        team_str = ", ".join(self.clickup_names_list[:50])
        allowed_assignees = ", ".join(self.config.allowed_assignees[:50]) if self.config.allowed_assignees else team_str
        
        system_prompt = (
            f"You are an Executive Assistant. Extract actionable WORK tasks.\n"
            f"TEAM MEMBERS: [{allowed_assignees}]\n"
            "1. If the email explicitly asks a specific team member to do something, set 'assignee_name' to their name.\n"
            "2. If it is for the receiver or general, set 'assignee_name' to 'Me'.\n"
            "3. Ignore spam/HR/Medical/Ads.\n"
            "Output JSON: {\"is_actionable\": bool, \"tasks\": [{\"title\": \"...\", \"assignee_name\": \"Name OR 'Me'\", \"description\": \"...\", \"priority_level\": \"...\", \"due_date_YYYY_MM_DD\": \"...\"}]}"
        )
        
        user_content = f"From: {sender}\nSub: {subject}\nBody: {full_text[:10000]}"
        
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            self.logs.append(f"❌ AI Error: {e}")
            return None
    
    def _resolve_assignee(self, ai_name, default_id):
        """Resolve assignee name to ClickUp user ID."""
        clean = str(ai_name).lower().strip()
        
        if not clean or clean in ["unassigned", "me", "unknown", "none", "no one"]:
            if default_id:
                self.logs.append(f"ℹ️ AI said '{ai_name}' -> Assigning to Current User.")
                return default_id
            return None
        
        if clean in self.clickup_users:
            return self.clickup_users[clean]
        
        # Check allowed assignees
        target = None
        for allowed in self.config.allowed_assignees:
            if clean == allowed.lower() or clean in allowed.lower().split():
                target = allowed
                break
        
        if not target:
            matches = difflib.get_close_matches(ai_name, self.config.allowed_assignees, n=1, cutoff=0.6)
            if matches:
                target = matches[0]
        
        if target:
            return self.clickup_users.get(target.lower())
        
        self.logs.append(f"⛔ Name '{ai_name}' not recognized in team.")
        return None
    
    async def _check_semantic_duplicate(self, new_title, new_desc):
        """Check if task is a semantic duplicate."""
        if not self.clickup_tasks:
            return {'is_duplicate': False}
        
        # Quick string match
        for t in self.clickup_tasks:
            if t['name'].lower() == new_title.lower():
                return {'is_duplicate': True, 'matched_task': t}
        
        if not self.openai_api_key:
            return {'is_duplicate': False}
        
        client = AsyncOpenAI(api_key=self.openai_api_key)
        recent_tasks = self.clickup_tasks[:15]
        existing_str = "\n".join([f"{i+1}. {t['name']}" for i, t in enumerate(recent_tasks)])
        
        prompt = (
            "Check duplicate.\n"
            f"NEW: '{new_title}'\nCTX: '{new_desc[:200]}'\n"
            f"EXISTING:\n{existing_str}\n"
            "JSON: {\"is_duplicate\": true, \"matched_task_title\": \"Exact Title\"} or {\"is_duplicate\": false}"
        )
        
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            res = json.loads(resp.choices[0].message.content)
            if res.get("is_duplicate"):
                matched_title = res.get("matched_task_title")
                for t in recent_tasks:
                    if t['name'] == matched_title:
                        return {'is_duplicate': True, 'matched_task': t}
        except Exception:
            pass
        
        return {'is_duplicate': False}
    
    async def _create_clickup_task(self, client, task_data, subject, sender_name, sender_email, my_id):
        """Create a ClickUp task."""
        assignee_id = self._resolve_assignee(task_data.get('assignee_name'), my_id)
        
        if not assignee_id:
            self.logs.append(f"❌ Skipping task '{task_data.get('title')[:30]}' - No valid assignee.")
            return False
        
        task_name = subject
        full_desc = (
            f"From: {sender_name}\n"
            f"Email: {sender_email}\n"
            f"Subject: {subject}\n\n"
            f"{task_data.get('description', '')}"
        )
        
        # Check for duplicates
        dedup = await self._check_semantic_duplicate(task_name, full_desc)
        
        target_parent_id = None
        if dedup['is_duplicate']:
            matched_task = dedup['matched_task']
            if matched_task.get('parent_id'):
                target_parent_id = matched_task['parent_id']
            else:
                target_parent_id = matched_task['id']
            task_name = f"Update: {task_name}"
            self.logs.append(f"📎 Attaching to parent: {matched_task['name'][:30]}")
        
        # Priority mapping
        p_val = 3
        if task_data.get("priority_level"):
            p_map = {"urgent": 1, "high": 2, "normal": 3, "low": 4}
            p_val = p_map.get(str(task_data.get("priority_level")).lower(), 3)
        
        # Due date
        due_ts = None
        if task_data.get("due_date_YYYY_MM_DD"):
            try:
                dt = datetime.strptime(task_data.get("due_date_YYYY_MM_DD"), "%Y-%m-%d")
                dt = dt.replace(tzinfo=CENTRAL_TZ)
                due_ts = int(dt.timestamp() * 1000)
            except Exception:
                pass
        
        payload = {
            "name": task_name,
            "description": full_desc,
            "status": "TO DO",
            "priority": p_val,
            "assignees": [assignee_id],
            "due_date": due_ts
        }
        
        if target_parent_id:
            payload["parent"] = target_parent_id
        
        try:
            headers = {"Authorization": self.clickup_api_key}
            resp = await client.post(
                f"{CLICKUP_API}/list/{self.config.clickup_list_id}/task",
                headers=headers,
                json=payload
            )
            
            if resp.status_code == 200:
                new_id = resp.json().get('id')
                self.logs.append(f"✅ Created: {task_name[:40]}")
                
                # Add to cache
                self.clickup_tasks.append({
                    'id': new_id,
                    'name': task_name,
                    'description': full_desc[:400],
                    'parent_id': target_parent_id
                })
                return True
            else:
                self.logs.append(f"❌ ClickUp Error: {resp.text[:100]}")
                return False
        except Exception as e:
            self.logs.append(f"❌ Error: {e}")
            return False
