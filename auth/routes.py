"""
Authentication Routes
"""
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, UserSettings, EmailAgentConfig, MeetingAgentConfig, BotConfig, ProcessedEmail, ProcessedMeeting, ActivityLog
import msal
import os

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        name = request.form.get('name', '').strip()
        
        # Validation
        if not email or not password:
            flash('Email and password are required.', 'error')
            return render_template('auth/register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('auth/register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return render_template('auth/register.html')
        
        # Create user
        user = User(email=email, name=name or email.split('@')[0])
        user.set_password(password)
        db.session.add(user)
        
        # Create default settings and configs
        settings = UserSettings(user=user)
        email_config = EmailAgentConfig(user=user)
        meeting_config = MeetingAgentConfig(user=user)
        bot_config = BotConfig(user=user)
        
        db.session.add_all([settings, email_config, meeting_config, bot_config])
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user, remember=bool(remember))
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('auth.dashboard'))
        
        flash('Invalid email or password.', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard with statistics."""
    from datetime import timedelta
    
    # Get statistics
    stats = {
        'emails_scanned': ProcessedEmail.query.filter_by(user_id=current_user.id).count(),
        'meetings_processed': ProcessedMeeting.query.filter_by(user_id=current_user.id).count(),
        'tasks_created_email': db.session.query(db.func.sum(ProcessedEmail.tasks_created)).filter_by(user_id=current_user.id).scalar() or 0,
        'tasks_created_meeting': db.session.query(db.func.sum(ProcessedMeeting.tasks_created)).filter_by(user_id=current_user.id).scalar() or 0,
        'standup_summaries': ProcessedMeeting.query.filter_by(user_id=current_user.id, standup_summary_created=True).count(),
    }
    stats['total_tasks'] = stats['tasks_created_email'] + stats['tasks_created_meeting']
    
    # Calculate weekly data for charts
    today = datetime.utcnow().date()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    
    weekly_emails = []
    weekly_meetings = []
    weekly_tasks = []
    
    for i in range(7):
        day = start_of_week + timedelta(days=i)
        next_day = day + timedelta(days=1)
        
        # Count emails for this day
        email_count = ProcessedEmail.query.filter(
            ProcessedEmail.user_id == current_user.id,
            ProcessedEmail.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedEmail.processed_at < datetime.combine(next_day, datetime.min.time())
        ).count()
        weekly_emails.append(email_count)
        
        # Count meetings for this day
        meeting_count = ProcessedMeeting.query.filter(
            ProcessedMeeting.user_id == current_user.id,
            ProcessedMeeting.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedMeeting.processed_at < datetime.combine(next_day, datetime.min.time())
        ).count()
        weekly_meetings.append(meeting_count)
        
        # Count tasks for this day
        email_tasks = db.session.query(db.func.sum(ProcessedEmail.tasks_created)).filter(
            ProcessedEmail.user_id == current_user.id,
            ProcessedEmail.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedEmail.processed_at < datetime.combine(next_day, datetime.min.time())
        ).scalar() or 0
        
        meeting_tasks = db.session.query(db.func.sum(ProcessedMeeting.tasks_created)).filter(
            ProcessedMeeting.user_id == current_user.id,
            ProcessedMeeting.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedMeeting.processed_at < datetime.combine(next_day, datetime.min.time())
        ).scalar() or 0
        
        weekly_tasks.append(email_tasks + meeting_tasks)
    
    # Get recent activity
    recent_activity = ActivityLog.query.filter_by(user_id=current_user.id)\
        .order_by(ActivityLog.created_at.desc()).limit(10).all()
    
    # Get recent processed items
    recent_emails = ProcessedEmail.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedEmail.processed_at.desc()).limit(5).all()
    recent_meetings = ProcessedMeeting.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedMeeting.processed_at.desc()).limit(5).all()
    
    # Check configuration status
    config_status = {
        'has_clickup_key': bool(current_user.settings and current_user.settings.clickup_api_key),
        'has_openai_key': bool(current_user.settings and current_user.settings.openai_api_key),
        'has_ms_token': bool(current_user.settings and current_user.settings.ms_access_token),
        'email_configured': bool(current_user.email_config and current_user.email_config.clickup_list_id),
        'meeting_configured': bool(current_user.meeting_config and current_user.meeting_config.clickup_list_id),
    }
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         recent_activity=recent_activity,
                         recent_emails=recent_emails,
                         recent_meetings=recent_meetings,
                         config_status=config_status,
                         weekly_emails=weekly_emails,
                         weekly_meetings=weekly_meetings,
                         weekly_tasks=weekly_tasks)


@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings for API keys."""
    if not current_user.settings:
        current_user.settings = UserSettings(user=current_user)
        db.session.commit()
    
    # Ensure bot_config exists
    if not current_user.bot_config:
        current_user.bot_config = BotConfig(user=current_user)
        db.session.commit()
    
    if request.method == 'POST':
        # Update API keys
        clickup_key = request.form.get('clickup_api_key', '').strip()
        openai_key = request.form.get('openai_api_key', '').strip()
        azure_client_id = request.form.get('azure_client_id', '').strip()
        azure_tenant_id = request.form.get('azure_tenant_id', '').strip()
        
        if clickup_key and '•' not in clickup_key:
            current_user.settings.clickup_api_key = clickup_key
        if openai_key and '•' not in openai_key:
            current_user.settings.openai_api_key = openai_key
        if azure_client_id:
            current_user.settings.azure_client_id = azure_client_id
        if azure_tenant_id:
            current_user.settings.azure_tenant_id = azure_tenant_id
        
        # Voice Bot Configuration
        recall_token = request.form.get('recall_ai_token', '').strip()
        deepgram_key = request.form.get('deepgram_api_key', '').strip()
        voice_bot_client_url = request.form.get('voice_bot_client_url', '').strip()
        voice_bot_websocket_url = request.form.get('voice_bot_websocket_url', '').strip()
        voice_bot_port = request.form.get('voice_bot_port', '').strip()
        
        if recall_token and '•' not in recall_token:
            current_user.bot_config.recall_ai_token = recall_token
        if deepgram_key and '•' not in deepgram_key:
            current_user.bot_config.deepgram_api_key = deepgram_key
        if voice_bot_client_url:
            current_user.bot_config.voice_bot_client_url = voice_bot_client_url
        if voice_bot_websocket_url:
            current_user.bot_config.voice_bot_websocket_url = voice_bot_websocket_url
        if voice_bot_port:
            try:
                current_user.bot_config.voice_bot_port = int(voice_bot_port)
            except ValueError:
                pass
        
        db.session.commit()
        flash('Settings saved successfully!', 'success')
        return redirect(url_for('auth.settings'))
    
    return render_template('auth/settings.html')


@auth_bp.route('/settings/test-clickup', methods=['POST'])
@login_required
def test_clickup():
    """Test ClickUp API connection."""
    import requests
    
    if not current_user.settings or not current_user.settings.clickup_api_key:
        return {'success': False, 'message': 'ClickUp API key not configured'}
    
    try:
        headers = {'Authorization': current_user.settings.clickup_api_key}
        resp = requests.get('https://api.clickup.com/api/v2/team', headers=headers, timeout=10)
        
        if resp.status_code == 200:
            teams = resp.json().get('teams', [])
            return {
                'success': True, 
                'message': f'Connected! Found {len(teams)} workspace(s).',
                'teams': [{'id': t['id'], 'name': t['name']} for t in teams]
            }
        else:
            return {'success': False, 'message': f'API Error: {resp.status_code}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


# Microsoft OAuth Routes
# Note: offline_access is automatically added by MSAL for device flow
GRAPH_SCOPES = [
    "User.Read",
    "Mail.Read", 
    "Mail.ReadWrite",  # For reading email attachments
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
    "Calendars.Read",
    "Chat.Read",
    "Mail.Send",
    "Files.Read.All",  # For OneDrive/SharePoint CV access
    "Sites.Read.All"   # For SharePoint access
]


def get_msal_app(user_settings=None):
    """Get MSAL application instance."""
    client_id = os.getenv('AZURE_CLIENT_ID')
    tenant_id = os.getenv('AZURE_TENANT_ID', 'common')
    
    if user_settings:
        client_id = user_settings.azure_client_id or client_id
        tenant_id = user_settings.azure_tenant_id or tenant_id
    
    return msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}"
    )


@auth_bp.route('/ms-login')
@login_required
def ms_login():
    """Start Microsoft OAuth flow using device code."""
    if not current_user.settings:
        current_user.settings = UserSettings(user=current_user)
        db.session.commit()
    
    app_msal = get_msal_app(current_user.settings)
    
    # Use device flow for simplicity
    flow = app_msal.initiate_device_flow(scopes=GRAPH_SCOPES)
    
    if "user_code" not in flow:
        flash('Failed to initiate Microsoft login. Please check Azure configuration.', 'error')
        return redirect(url_for('auth.settings'))
    
    # Store flow in session
    session['ms_flow'] = flow
    
    return render_template('auth/ms_login.html', 
                         flow=flow,
                         verification_uri=flow.get('verification_uri'),
                         user_code=flow.get('user_code'))


@auth_bp.route('/ms-login/complete', methods=['POST'])
@login_required
def ms_login_complete():
    """Complete Microsoft OAuth flow."""
    flow = session.get('ms_flow')
    
    if not flow:
        flash('Login session expired. Please try again.', 'error')
        return redirect(url_for('auth.settings'))
    
    app_msal = get_msal_app(current_user.settings)
    
    try:
        result = app_msal.acquire_token_by_device_flow(flow)
        
        if "access_token" in result:
            # Save tokens
            current_user.settings.ms_access_token = result['access_token']
            if 'refresh_token' in result:
                current_user.settings.ms_refresh_token = result['refresh_token']
            if 'expires_in' in result:
                from datetime import timedelta
                current_user.settings.ms_token_expires_at = datetime.utcnow() + timedelta(seconds=result['expires_in'])
            
            db.session.commit()
            session.pop('ms_flow', None)
            
            flash('Microsoft account connected successfully!', 'success')
        else:
            error = result.get('error_description', 'Unknown error')
            flash(f'Microsoft login failed: {error}', 'error')
            
    except Exception as e:
        flash(f'Microsoft login error: {str(e)}', 'error')
    
    return redirect(url_for('auth.settings'))


@auth_bp.route('/ms-disconnect')
@login_required
def ms_disconnect():
    """Disconnect Microsoft account."""
    if current_user.settings:
        current_user.settings._ms_access_token = None
        current_user.settings._ms_refresh_token = None
        current_user.settings.ms_token_expires_at = None
        db.session.commit()
    
    flash('Microsoft account disconnected.', 'info')
    return redirect(url_for('auth.settings'))
