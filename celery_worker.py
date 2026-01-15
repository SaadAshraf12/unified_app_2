"""
Celery Worker Configuration
Background tasks for Email and Meeting agents
"""
import os
import sys

# Add the current directory to Python path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from celery import Celery
from celery.schedules import crontab

# Initialize Celery
celery = Celery('unified_app')

# Configure from environment
celery.conf.update(
    broker_url=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    result_backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minute timeout per task
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Beat schedule - periodic tasks
celery.conf.beat_schedule = {
    'scan-meetings-every-30-minutes': {
        'task': 'celery_worker.scan_all_users_meetings',
        'schedule': 30 * 60,  # 30 minutes in seconds
    },
    'scan-emails-every-5-minutes': {
        'task': 'celery_worker.scan_all_users_emails',
        'schedule': 5 * 60,  # 5 minutes in seconds
    },
    'scan-ats-every-30-minutes': {
        'task': 'ats_agent.scheduled_scan',
        'schedule': 30 * 60,  # 30 minutes in seconds
    },
    'scan-upcoming-meetings-every-minute': {
        'task': 'celery_worker.scan_all_voice_bots',
        'schedule': 60.0,
    },
}

# Import ATS tasks to register them with Celery
import agents.ats_agent.tasks  # noqa: F401



def get_flask_app():
    """Create Flask app instance for Celery tasks."""
    from flask import Flask
    from flask_login import LoginManager
    from models import db, User
    from config import config
    
    config_name = os.getenv('FLASK_ENV', 'production')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))
    
    with app.app_context():
        db.create_all()
    
    return app


@celery.task(bind=True)
def scan_all_users_meetings(self):
    """Scan meetings for all enabled users."""
    from models import db, MeetingAgentConfig
    
    app = get_flask_app()
    with app.app_context():
        # Get all users with enabled meeting agent
        enabled_configs = MeetingAgentConfig.query.filter_by(is_enabled=True).all()
        
        results = []
        for config in enabled_configs:
            user = config.user
            
            # Check if user has required settings
            if not user.settings or not user.settings.ms_access_token:
                continue
            if not config.clickup_list_id:
                continue
            if not user.settings.clickup_api_key:
                continue
            
            # Queue individual user scan
            scan_user_meetings.delay(user.id)
            results.append(f"Queued meeting scan for user {user.id}")
        
        return {'users_queued': len(results), 'details': results}


@celery.task(bind=True, max_retries=3)
def scan_user_meetings(self, user_id):
    """Scan meetings for a specific user."""
    from models import db, User, ActivityLog
    from agents.meeting_agent.service import MeetingAgentService
    import asyncio
    
    app = get_flask_app()
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user:
            return {'error': 'User not found'}
        
        try:
            service = MeetingAgentService(user)
            result = asyncio.run(service.process_meetings())
            
            # Log activity
            log = ActivityLog(
                user_id=user.id,
                agent_type='meeting',
                action='scheduled_scan',
                message=f"Auto-scan: {result['meetings_checked']} meetings, {result['tasks_created']} tasks",
                status='success' if result['success'] else 'error'
            )
            db.session.add(log)
            db.session.commit()
            
            return result
            
        except Exception as e:
            # Log error
            log = ActivityLog(
                user_id=user.id,
                agent_type='meeting',
                action='scheduled_scan',
                message=f"Auto-scan error: {str(e)}",
                status='error'
            )
            db.session.add(log)
            db.session.commit()
            
            # Retry on failure
            raise self.retry(exc=e, countdown=60)


@celery.task(bind=True)
def scan_all_users_emails(self):
    """Scan emails for all enabled users."""
    from models import db, EmailAgentConfig
    
    app = get_flask_app()
    with app.app_context():
        # Get all users with enabled email agent
        enabled_configs = EmailAgentConfig.query.filter_by(is_enabled=True).all()
        
        results = []
        for config in enabled_configs:
            user = config.user
            
            # Check if user has required settings
            if not user.settings or not user.settings.ms_access_token:
                continue
            if not config.clickup_list_id:
                continue
            if not user.settings.clickup_api_key:
                continue
            
            # Queue individual user scan
            scan_user_emails.delay(user.id)
            results.append(f"Queued email scan for user {user.id}")
        
        return {'users_queued': len(results), 'details': results}


@celery.task(bind=True, max_retries=3)
def scan_user_emails(self, user_id):
    """Scan emails for a specific user."""
    from models import db, User, ActivityLog
    from agents.email_agent.service import EmailAgentService
    import asyncio
    
    app = get_flask_app()
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user:
            return {'error': 'User not found'}
        
        try:
            service = EmailAgentService(user)
            result = asyncio.run(service.process_emails())
            
            # Log activity
            log = ActivityLog(
                user_id=user.id,
                agent_type='email',
                action='scheduled_scan',
                message=f"Auto-scan: {result['emails_checked']} emails, {result['tasks_created']} tasks",
                status='success' if result['success'] else 'error'
            )
            db.session.add(log)
            db.session.commit()
            
            return result
            
        except Exception as e:
            # Log error
            log = ActivityLog(
                user_id=user.id,
                agent_type='email',
                action='scheduled_scan',
                message=f"Auto-scan error: {str(e)}",
                status='error'
            )
            db.session.add(log)
            db.session.commit()
            
            # Retry on failure
            raise self.retry(exc=e, countdown=60)


# Task triggered by webhook when new email arrives
@celery.task(bind=True)
def process_new_email_notification(self, user_id, email_id):
    """Process a single incoming email (triggered by webhook)."""
    from models import db, User, ActivityLog
    from agents.email_agent.service import EmailAgentService
    import asyncio
    
    app = get_flask_app()
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user:
            return {'error': 'User not found'}
        
        try:
            service = EmailAgentService(user)
            # Process just this specific email
            result = asyncio.run(service.process_single_email(email_id))
            
            if result.get('processed'):
                log = ActivityLog(
                    user_id=user.id,
                    agent_type='email',
                    action='webhook_scan',
                    message=f"Real-time: Processed email, created {result.get('tasks_created', 0)} tasks",
                    status='success'
                )
                db.session.add(log)
                db.session.commit()
            
            return result
            
        except Exception as e:
            return {'error': str(e)}


@celery.task(bind=True)
def scan_all_voice_bots(self):
    """Scan upcoming meetings for voice bots (Auto-Join)."""
    from models import db, User
    from agents.voice_bot_agent.scheduler import check_and_join_meetings
    
    app = get_flask_app()
    with app.app_context():
        users = User.query.all()
        results = []
        for user in users:
            if user.bot_config and user.bot_config.is_enabled:
               try:
                   check_and_join_meetings(user.id)
                   results.append(f"Checked user {user.id}")
               except Exception as e:
                   results.append(f"Error checking user {user.id}: {e}")
        return results
