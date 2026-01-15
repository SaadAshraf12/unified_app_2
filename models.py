"""
Database Models for Unified AI Agents Application
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import os
import json

# Load .env file to ensure ENCRYPTION_KEY is available
load_dotenv(override=True)

db = SQLAlchemy()


def get_cipher():
    """Get Fernet cipher for encryption/decryption."""
    key = os.getenv('ENCRYPTION_KEY', '').strip()
    if not key:
        # Generate a key for development (not secure for production)
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(value):
    """Encrypt a string value."""
    if not value:
        return None
    cipher = get_cipher()
    return cipher.encrypt(value.encode()).decode()


def decrypt_value(encrypted_value):
    """Decrypt an encrypted string value."""
    if not encrypted_value:
        return None
    try:
        cipher = get_cipher()
        return cipher.decrypt(encrypted_value.encode()).decode()
    except Exception:
        return None


class User(UserMixin, db.Model):
    """User model for authentication."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    settings = db.relationship('UserSettings', backref='user', uselist=False, cascade='all, delete-orphan')
    email_config = db.relationship('EmailAgentConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    meeting_config = db.relationship('MeetingAgentConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    bot_config = db.relationship('BotConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    ats_config = db.relationship('ATSAgentConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    processed_emails = db.relationship('ProcessedEmail', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    processed_meetings = db.relationship('ProcessedMeeting', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    cv_candidates = db.relationship('CVCandidate', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.email}>'


class UserSettings(db.Model):
    """User API credentials and settings."""
    __tablename__ = 'user_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Microsoft Azure credentials (encrypted)
    azure_client_id = db.Column(db.String(256), nullable=True)
    azure_tenant_id = db.Column(db.String(256), nullable=True)
    _ms_access_token = db.Column('ms_access_token', db.Text, nullable=True)
    _ms_refresh_token = db.Column('ms_refresh_token', db.Text, nullable=True)
    ms_token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # ClickUp API key (encrypted)
    _clickup_api_key = db.Column('clickup_api_key', db.String(512), nullable=True)
    
    # OpenAI API key (encrypted, optional - uses app default if not set)
    _openai_api_key = db.Column('openai_api_key', db.String(512), nullable=True)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def clickup_api_key(self):
        return decrypt_value(self._clickup_api_key)
    
    @clickup_api_key.setter
    def clickup_api_key(self, value):
        self._clickup_api_key = encrypt_value(value)
    
    @property
    def openai_api_key(self):
        return decrypt_value(self._openai_api_key)
    
    @openai_api_key.setter
    def openai_api_key(self, value):
        self._openai_api_key = encrypt_value(value)
    
    @property
    def ms_access_token(self):
        return decrypt_value(self._ms_access_token)
    
    @ms_access_token.setter
    def ms_access_token(self, value):
        self._ms_access_token = encrypt_value(value)
    
    @property
    def ms_refresh_token(self):
        return decrypt_value(self._ms_refresh_token)
    
    @ms_refresh_token.setter
    def ms_refresh_token(self, value):
        self._ms_refresh_token = encrypt_value(value)


class EmailAgentConfig(db.Model):
    """Configuration for Email Agent per user."""
    __tablename__ = 'email_agent_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # ClickUp settings
    clickup_list_id = db.Column(db.String(50), nullable=True)
    
    # Filters (stored as JSON)
    _allowed_senders = db.Column('allowed_senders', db.Text, default='[]')
    _allowed_assignees = db.Column('allowed_assignees', db.Text, default='[]')
    _sensitive_keywords = db.Column('sensitive_keywords', db.Text, default='[]')
    _ignore_subject_prefixes = db.Column('ignore_subject_prefixes', db.Text, 
                                         default='["Automatic reply:", "Accepted:", "Declined:", "Tentative:", "Canceled:"]')
    
    # Agent settings
    is_enabled = db.Column(db.Boolean, default=True)
    auto_run_interval = db.Column(db.Integer, default=0)  # 0 = manual only, otherwise minutes
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def allowed_senders(self):
        return json.loads(self._allowed_senders or '[]')
    
    @allowed_senders.setter
    def allowed_senders(self, value):
        self._allowed_senders = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def allowed_assignees(self):
        return json.loads(self._allowed_assignees or '[]')
    
    @allowed_assignees.setter
    def allowed_assignees(self, value):
        self._allowed_assignees = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def sensitive_keywords(self):
        return json.loads(self._sensitive_keywords or '[]')
    
    @sensitive_keywords.setter
    def sensitive_keywords(self, value):
        self._sensitive_keywords = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def ignore_subject_prefixes(self):
        return json.loads(self._ignore_subject_prefixes or '[]')
    
    @ignore_subject_prefixes.setter
    def ignore_subject_prefixes(self, value):
        self._ignore_subject_prefixes = json.dumps(value if isinstance(value, list) else [])


class MeetingAgentConfig(db.Model):
    """Configuration for Meeting Agent per user."""
    __tablename__ = 'meeting_agent_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # ClickUp settings
    clickup_list_id = db.Column(db.String(50), nullable=True)
    target_space_id = db.Column(db.String(50), nullable=True)
    target_doc_name = db.Column(db.String(200), default='Daily Standup Summary By AI')
    
    # Email alerts
    helpdesk_email = db.Column(db.String(120), nullable=True)
    
    # Meeting filters (stored as JSON)
    _meeting_name_filters = db.Column('meeting_name_filters', db.Text, default='[]')
    _standup_meeting_keywords = db.Column('standup_meeting_keywords', db.Text, 
                                          default='["Daily Standup", "Stand-up", "Standup"]')
    _excluded_meeting_names = db.Column('excluded_meeting_names', db.Text, default='[]')
    
    # Agent settings
    is_enabled = db.Column(db.Boolean, default=True)
    auto_run_interval = db.Column(db.Integer, default=0)
    scan_days_back = db.Column(db.Integer, default=2)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def meeting_name_filters(self):
        return json.loads(self._meeting_name_filters or '[]')
    
    @meeting_name_filters.setter
    def meeting_name_filters(self, value):
        self._meeting_name_filters = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def standup_meeting_keywords(self):
        return json.loads(self._standup_meeting_keywords or '[]')
    
    @standup_meeting_keywords.setter
    def standup_meeting_keywords(self, value):
        self._standup_meeting_keywords = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def excluded_meeting_names(self):
        return json.loads(self._excluded_meeting_names or '[]')
    
    @excluded_meeting_names.setter
    def excluded_meeting_names(self, value):
        self._excluded_meeting_names = json.dumps(value if isinstance(value, list) else [])


class BotConfig(db.Model):
    """Configuration for Meeting Bot per user."""
    __tablename__ = 'bot_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Bot personality
    bot_name = db.Column(db.String(50), default='Alex')
    _wake_words = db.Column('wake_words', db.Text, default='["hello Alex", "hey Alex", "Alex"]')
    _dismissal_phrases = db.Column('dismissal_phrases', db.Text, 
                                   default='["that\'s all", "thanks Alex", "goodbye", "bye"]')
    
    # ClickUp context
    clickup_space_name = db.Column(db.String(100), default='AI Context')
    clickup_summary_doc_name = db.Column(db.String(200), default='Daily Standup Summary By AI')
    
    # Voice Bot API Keys (encrypted)
    _recall_ai_token = db.Column('recall_ai_token', db.String(512), nullable=True)
    _deepgram_api_key = db.Column('deepgram_api_key', db.String(512), nullable=True)
    
    # Voice Bot URLs
    voice_bot_client_url = db.Column(db.String(500), default='https://animated-torte-eca718.netlify.app')
    voice_bot_websocket_url = db.Column(db.String(500), nullable=True)
    voice_bot_port = db.Column(db.Integer, default=8000)
    
    # Settings
    is_enabled = db.Column(db.Boolean, default=True)
    timeout_seconds = db.Column(db.Integer, default=50)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def wake_words(self):
        return json.loads(self._wake_words or '[]')
    
    @wake_words.setter
    def wake_words(self, value):
        self._wake_words = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def dismissal_phrases(self):
        return json.loads(self._dismissal_phrases or '[]')
    
    @dismissal_phrases.setter
    def dismissal_phrases(self, value):
        self._dismissal_phrases = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def recall_ai_token(self):
        return decrypt_value(self._recall_ai_token)
    
    @recall_ai_token.setter
    def recall_ai_token(self, value):
        self._recall_ai_token = encrypt_value(value)
    
    @property
    def deepgram_api_key(self):
        return decrypt_value(self._deepgram_api_key)
    
    @deepgram_api_key.setter
    def deepgram_api_key(self, value):
        self._deepgram_api_key = encrypt_value(value)


class ProcessedEmail(db.Model):
    """Track processed emails per user."""
    __tablename__ = 'processed_emails'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    email_id = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(500), nullable=True)
    sender = db.Column(db.String(200), nullable=True)
    tasks_created = db.Column(db.Integer, default=0)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'email_id', name='unique_user_email'),
    )


class ProcessedMeeting(db.Model):
    """Track processed meetings/transcripts per user."""
    __tablename__ = 'processed_meetings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    transcript_id = db.Column(db.String(200), nullable=False)
    meeting_subject = db.Column(db.String(500), nullable=True)
    tasks_created = db.Column(db.Integer, default=0)
    standup_summary_created = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'transcript_id', name='unique_user_transcript'),
    )


class ActivityLog(db.Model):
    """Activity logs for dashboard."""
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    agent_type = db.Column(db.String(20), nullable=False)  # 'email', 'meeting', 'bot', 'ats'
    action = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='success')  # 'success', 'error', 'warning'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('activity_logs', lazy='dynamic'))


class ATSAgentConfig(db.Model):
    """Configuration for ATS Scoring Agent per user."""
    __tablename__ = 'ats_agent_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Job Details
    job_title = db.Column(db.String(255), nullable=True)
    job_description = db.Column(db.Text, nullable=True)
    _required_skills = db.Column('required_skills', db.Text, default='[]')
    
    # Filters
    _allowed_locations = db.Column('allowed_locations', db.Text, default='[]')
    min_experience = db.Column(db.Integer, default=0)
    max_experience = db.Column(db.Integer, default=99)
    min_education_level = db.Column(db.String(50), nullable=True)  # Bachelors, Masters, etc.
    _must_have_skills = db.Column('must_have_skills', db.Text, default='[]')
    
    # Scoring Weights (must sum to 1.0)
    weight_skills = db.Column(db.Numeric(4, 2), default=0.40)
    weight_title = db.Column(db.Numeric(4, 2), default=0.20)
    weight_experience = db.Column(db.Numeric(4, 2), default=0.20)
    weight_education = db.Column(db.Numeric(4, 2), default=0.10)
    weight_keywords = db.Column(db.Numeric(4, 2), default=0.10)
    
    # CV Sources
    onedrive_enabled = db.Column(db.Boolean, default=False)
    onedrive_folder_path = db.Column(db.String(255), default='CVs')
    google_drive_enabled = db.Column(db.Boolean, default=False)
    google_drive_folder_id = db.Column(db.String(255), nullable=True)
    sharepoint_enabled = db.Column(db.Boolean, default=False)
    sharepoint_site_url = db.Column(db.String(500), nullable=True)
    sharepoint_library = db.Column(db.String(255), nullable=True)
    email_folder_enabled = db.Column(db.Boolean, default=False)
    email_folder_name = db.Column(db.String(255), default='Recruitment')
    email_inbox_enabled = db.Column(db.Boolean, default=False)
    
    # Output Config
    top_n_candidates = db.Column(db.Integer, default=10)
    min_threshold_score = db.Column(db.Integer, default=60)
    
    # Agent settings
    is_enabled = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def required_skills(self):
        return json.loads(self._required_skills or '[]')
    
    @required_skills.setter
    def required_skills(self, value):
        self._required_skills = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def allowed_locations(self):
        return json.loads(self._allowed_locations or '[]')
    
    @allowed_locations.setter
    def allowed_locations(self, value):
        self._allowed_locations = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def must_have_skills(self):
        return json.loads(self._must_have_skills or '[]')
    
    @must_have_skills.setter
    def must_have_skills(self, value):
        self._must_have_skills = json.dumps(value if isinstance(value, list) else [])


class CVCandidate(db.Model):
    """CV candidates and their scoring results."""
    __tablename__ = 'cv_candidates'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_id = db.Column(db.Integer, nullable=True)  # For future multi-job support
    
    # Basic Info (parsed from CV)
    full_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)
    
    # Extracted Data
    years_of_experience = db.Column(db.Numeric(4, 1), nullable=True)
    _skills = db.Column('skills', db.Text, default='[]')
    education_level = db.Column(db.String(50), nullable=True)
    current_job_title = db.Column(db.String(255), nullable=True)
    
    # CV Data
    cv_text = db.Column(db.Text, nullable=True)  # Full extracted text
    cv_file_path = db.Column(db.String(500), nullable=True)  # Stored file location
    cv_source = db.Column(db.String(50), nullable=True)  # 'google_drive', 'sharepoint', 'outlook', 'email'
    source_file_id = db.Column(db.String(500), nullable=True)  # Original file ID from source (Microsoft Graph IDs can be 380+ chars)
    source_file_name = db.Column(db.String(255), nullable=True)
    
    # Scoring Results
    status = db.Column(db.String(50), default='pending')  # 'pending', 'scored', 'filtered_out', 'rejected'
    skills_score = db.Column(db.Integer, nullable=True)
    skills_reasoning = db.Column(db.Text, nullable=True)
    title_score = db.Column(db.Integer, nullable=True)
    title_reasoning = db.Column(db.Text, nullable=True)
    experience_score = db.Column(db.Integer, nullable=True)
    experience_reasoning = db.Column(db.Text, nullable=True)
    education_score = db.Column(db.Integer, nullable=True)
    education_reasoning = db.Column(db.Text, nullable=True)
    keywords_score = db.Column(db.Integer, nullable=True)
    keywords_reasoning = db.Column(db.Text, nullable=True)
    final_weighted_score = db.Column(db.Numeric(5, 2), nullable=True)
    overall_assessment = db.Column(db.Text, nullable=True)
    _red_flags = db.Column('red_flags', db.Text, default='[]')
    
    # Metadata
    processed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'source_file_id', name='unique_user_cv'),
    )
    
    @property
    def skills(self):
        return json.loads(self._skills or '[]')
    
    @skills.setter
    def skills(self, value):
        self._skills = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def red_flags(self):
        return json.loads(self._red_flags or '[]')
    
    @red_flags.setter
    def red_flags(self, value):
        self._red_flags = json.dumps(value if isinstance(value, list) else [])


class ATSScanHistory(db.Model):
    """Track ATS scan history and statistics."""
    __tablename__ = 'ats_scan_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    total_cvs_found = db.Column(db.Integer, default=0)
    cvs_processed = db.Column(db.Integer, default=0)
    cvs_filtered_out = db.Column(db.Integer, default=0)
    cvs_scored = db.Column(db.Integer, default=0)
    top_candidates_count = db.Column(db.Integer, default=0)
    
    scan_started_at = db.Column(db.DateTime, default=datetime.utcnow)
    scan_completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='running')  # 'running', 'completed', 'failed'
    error_message = db.Column(db.Text, nullable=True)
    
    user = db.relationship('User', backref=db.backref('ats_scan_history', lazy='dynamic'))
