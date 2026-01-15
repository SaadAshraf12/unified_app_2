"""
Meeting Agent Routes
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, MeetingAgentConfig, ProcessedMeeting, ActivityLog
import asyncio

meeting_bp = Blueprint('meeting', __name__)


@meeting_bp.route('/dashboard')
@login_required
def dashboard():
    """Meeting agent dashboard."""
    from datetime import datetime, timedelta
    
    config = current_user.meeting_config
    
    # Get statistics
    stats = {
        'total_processed': ProcessedMeeting.query.filter_by(user_id=current_user.id).count(),
        'tasks_created': db.session.query(db.func.sum(ProcessedMeeting.tasks_created)).filter_by(user_id=current_user.id).scalar() or 0,
        'standup_summaries': ProcessedMeeting.query.filter_by(user_id=current_user.id, standup_summary_created=True).count(),
    }
    
    # Calculate weekly data for charts
    today = datetime.utcnow().date()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    
    weekly_meetings = []
    weekly_tasks = []
    
    for i in range(7):
        day = start_of_week + timedelta(days=i)
        next_day = day + timedelta(days=1)
        
        # Count meetings for this day
        meeting_count = ProcessedMeeting.query.filter(
            ProcessedMeeting.user_id == current_user.id,
            ProcessedMeeting.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedMeeting.processed_at < datetime.combine(next_day, datetime.min.time())
        ).count()
        weekly_meetings.append(meeting_count)
        
        # Count tasks for this day
        tasks_sum = db.session.query(db.func.sum(ProcessedMeeting.tasks_created)).filter(
            ProcessedMeeting.user_id == current_user.id,
            ProcessedMeeting.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedMeeting.processed_at < datetime.combine(next_day, datetime.min.time())
        ).scalar() or 0
        weekly_tasks.append(tasks_sum)
    
    # Get recent activity
    recent_logs = ActivityLog.query.filter_by(
        user_id=current_user.id, 
        agent_type='meeting'
    ).order_by(ActivityLog.created_at.desc()).limit(20).all()
    
    # Get recent meetings
    recent_meetings = ProcessedMeeting.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedMeeting.processed_at.desc()).limit(10).all()
    
    # Check if configured
    is_configured = bool(
        current_user.settings and 
        current_user.settings.clickup_api_key and
        config and config.clickup_list_id
    )
    
    return render_template('meeting/dashboard.html', 
                         config=config,
                         stats=stats,
                         recent_logs=recent_logs,
                         recent_meetings=recent_meetings,
                         is_configured=is_configured,
                         weekly_meetings=weekly_meetings,
                         weekly_tasks=weekly_tasks)


@meeting_bp.route('/config', methods=['GET', 'POST'])
@login_required
def config():
    """Meeting agent configuration."""
    if not current_user.meeting_config:
        current_user.meeting_config = MeetingAgentConfig(user=current_user)
        db.session.commit()
    
    cfg = current_user.meeting_config
    
    if request.method == 'POST':
        # Update configuration
        cfg.clickup_list_id = request.form.get('clickup_list_id', '').strip()
        cfg.target_space_id = request.form.get('target_space_id', '').strip()
        cfg.target_doc_name = request.form.get('target_doc_name', '').strip() or 'Daily Standup Summary By AI'
        cfg.helpdesk_email = request.form.get('helpdesk_email', '').strip()
        cfg.scan_days_back = int(request.form.get('scan_days_back', 2))
        
        # Parse lists
        standup_keywords = request.form.get('standup_meeting_keywords', '')
        cfg.standup_meeting_keywords = [k.strip() for k in standup_keywords.split('\n') if k.strip()]
        
        meeting_filters = request.form.get('meeting_name_filters', '')
        cfg.meeting_name_filters = [f.strip() for f in meeting_filters.split('\n') if f.strip()]
        
        # Parse excluded meetings (new feature)
        excluded_meetings = request.form.get('excluded_meeting_names', '')
        cfg.excluded_meeting_names = [e.strip() for e in excluded_meetings.split('\n') if e.strip()]
        
        cfg.is_enabled = 'is_enabled' in request.form
        
        db.session.commit()
        flash('Meeting agent configuration saved!', 'success')
        return redirect(url_for('meeting.config'))
    
    return render_template('meeting/config.html', config=cfg)


@meeting_bp.route('/run')
@login_required
def run():
    """Run meeting scan."""
    # Check configuration
    if not current_user.settings or not current_user.settings.clickup_api_key:
        flash('Please configure your ClickUp API key first.', 'warning')
        return redirect(url_for('auth.settings'))
    
    if not current_user.meeting_config or not current_user.meeting_config.clickup_list_id:
        flash('Please configure your Meeting Agent settings first.', 'warning')
        return redirect(url_for('meeting.config'))
    
    if not current_user.settings.ms_access_token:
        flash('Please connect your Microsoft account first.', 'warning')
        return redirect(url_for('auth.settings'))
    
    # Run the meeting processing
    try:
        from agents.meeting_agent.service import MeetingAgentService
        
        service = MeetingAgentService(current_user)
        result = asyncio.run(service.process_meetings())
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='meeting',
            action='scan',
            message=f"Scanned {result['meetings_checked']} meetings, created {result['tasks_created']} tasks, {result['summaries_created']} summaries",
            status='success' if result['success'] else 'error'
        )
        db.session.add(log)
        db.session.commit()
        
        if result['success']:
            flash(f"Meeting scan complete! Checked {result['meetings_checked']} meetings, created {result['tasks_created']} tasks.", 'success')
        else:
            flash(f"Meeting scan failed: {result.get('error', 'Unknown error')}", 'error')
            
    except Exception as e:
        flash(f'Error running meeting scan: {str(e)}', 'error')
        
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='meeting',
            action='scan',
            message=str(e),
            status='error'
        )
        db.session.add(log)
        db.session.commit()
    
    return redirect(url_for('meeting.dashboard'))


@meeting_bp.route('/run-ajax', methods=['POST'])
@login_required
def run_ajax():
    """Run meeting scan via AJAX (triggers background Celery task)."""
    # Check configuration
    if not current_user.settings or not current_user.settings.clickup_api_key:
        return jsonify({'success': False, 'error': 'ClickUp API key not configured'})
    
    if not current_user.meeting_config or not current_user.meeting_config.clickup_list_id:
        return jsonify({'success': False, 'error': 'Meeting agent not configured'})
    
    if not current_user.settings.ms_access_token:
        return jsonify({'success': False, 'error': 'Microsoft account not connected'})
    
    try:
        # Trigger background Celery task instead of running synchronously
        from celery_worker import scan_user_meetings
        scan_user_meetings.delay(current_user.id)
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='meeting',
            action='scan_triggered',
            message='Meeting scan started (running in background)',
            status='success'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Meeting scan started! Refresh the page in a few moments to see results.',
            'info': 'The scan is running in the background and may take 1-2 minutes.'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@meeting_bp.route('/history')
@login_required
def history():
    """View processed meetings history."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    meetings = ProcessedMeeting.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedMeeting.processed_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('meeting/history.html', meetings=meetings)
