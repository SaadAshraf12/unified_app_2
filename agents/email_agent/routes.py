"""
Email Agent Routes
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, EmailAgentConfig, ProcessedEmail, ActivityLog
import asyncio

email_bp = Blueprint('email', __name__)


@email_bp.route('/dashboard')
@login_required
def dashboard():
    """Email agent dashboard."""
    from datetime import datetime, timedelta
    
    config = current_user.email_config
    
    # Get statistics
    stats = {
        'total_scanned': ProcessedEmail.query.filter_by(user_id=current_user.id).count(),
        'tasks_created': db.session.query(db.func.sum(ProcessedEmail.tasks_created)).filter_by(user_id=current_user.id).scalar() or 0,
        'allowed_senders': len(config.allowed_senders) if config else 0,
        'allowed_assignees': len(config.allowed_assignees) if config else 0,
    }
    
    # Calculate weekly data for charts
    today = datetime.utcnow().date()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    
    weekly_emails = []
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
        
        # Count tasks for this day
        tasks_sum = db.session.query(db.func.sum(ProcessedEmail.tasks_created)).filter(
            ProcessedEmail.user_id == current_user.id,
            ProcessedEmail.processed_at >= datetime.combine(day, datetime.min.time()),
            ProcessedEmail.processed_at < datetime.combine(next_day, datetime.min.time())
        ).scalar() or 0
        weekly_tasks.append(tasks_sum)
    
    # Get recent activity
    recent_logs = ActivityLog.query.filter_by(
        user_id=current_user.id, 
        agent_type='email'
    ).order_by(ActivityLog.created_at.desc()).limit(20).all()
    
    # Get recent emails
    recent_emails = ProcessedEmail.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedEmail.processed_at.desc()).limit(10).all()
    
    # Check if configured
    is_configured = bool(
        current_user.settings and 
        current_user.settings.clickup_api_key and
        config and config.clickup_list_id
    )
    
    return render_template('email/dashboard.html', 
                         config=config,
                         stats=stats,
                         recent_logs=recent_logs,
                         recent_emails=recent_emails,
                         is_configured=is_configured,
                         weekly_emails=weekly_emails,
                         weekly_tasks=weekly_tasks)


@email_bp.route('/config', methods=['GET', 'POST'])
@login_required
def config():
    """Email agent configuration."""
    if not current_user.email_config:
        current_user.email_config = EmailAgentConfig(user=current_user)
        db.session.commit()
    
    cfg = current_user.email_config
    
    if request.method == 'POST':
        # Update configuration
        cfg.clickup_list_id = request.form.get('clickup_list_id', '').strip()
        
        # Parse comma-separated lists
        allowed_senders = request.form.get('allowed_senders', '')
        cfg.allowed_senders = [s.strip().lower() for s in allowed_senders.split('\n') if s.strip()]
        
        allowed_assignees = request.form.get('allowed_assignees', '')
        cfg.allowed_assignees = [a.strip() for a in allowed_assignees.split('\n') if a.strip()]
        
        sensitive_keywords = request.form.get('sensitive_keywords', '')
        cfg.sensitive_keywords = [k.strip().lower() for k in sensitive_keywords.split('\n') if k.strip()]
        
        ignore_prefixes = request.form.get('ignore_subject_prefixes', '')
        cfg.ignore_subject_prefixes = [p.strip() for p in ignore_prefixes.split('\n') if p.strip()]
        
        cfg.is_enabled = 'is_enabled' in request.form
        
        db.session.commit()
        flash('Email agent configuration saved!', 'success')
        return redirect(url_for('email.config'))
    
    return render_template('email/config.html', config=cfg)


@email_bp.route('/run')
@login_required
def run():
    """Run email scan."""
    # Check configuration
    if not current_user.settings or not current_user.settings.clickup_api_key:
        flash('Please configure your ClickUp API key first.', 'warning')
        return redirect(url_for('auth.settings'))
    
    if not current_user.email_config or not current_user.email_config.clickup_list_id:
        flash('Please configure your Email Agent settings first.', 'warning')
        return redirect(url_for('email.config'))
    
    if not current_user.settings.ms_access_token:
        flash('Please connect your Microsoft account first.', 'warning')
        return redirect(url_for('auth.settings'))
    
    # Run the email processing
    try:
        from agents.email_agent.service import EmailAgentService
        
        service = EmailAgentService(current_user)
        result = asyncio.run(service.process_emails())
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='email',
            action='scan',
            message=f"Scanned {result['emails_checked']} emails, created {result['tasks_created']} tasks",
            status='success' if result['success'] else 'error'
        )
        db.session.add(log)
        db.session.commit()
        
        if result['success']:
            flash(f"Email scan complete! Checked {result['emails_checked']} emails, created {result['tasks_created']} tasks.", 'success')
        else:
            flash(f"Email scan failed: {result.get('error', 'Unknown error')}", 'error')
            
    except Exception as e:
        flash(f'Error running email scan: {str(e)}', 'error')
        
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='email',
            action='scan',
            message=str(e),
            status='error'
        )
        db.session.add(log)
        db.session.commit()
    
    return redirect(url_for('email.dashboard'))


@email_bp.route('/run-ajax', methods=['POST'])
@login_required
def run_ajax():
    """Run email scan via AJAX."""
    # Check configuration
    if not current_user.settings or not current_user.settings.clickup_api_key:
        return jsonify({'success': False, 'error': 'ClickUp API key not configured'})
    
    if not current_user.email_config or not current_user.email_config.clickup_list_id:
        return jsonify({'success': False, 'error': 'Email agent not configured'})
    
    if not current_user.settings.ms_access_token:
        return jsonify({'success': False, 'error': 'Microsoft account not connected'})
    
    try:
        from agents.email_agent.service import EmailAgentService
        
        service = EmailAgentService(current_user)
        result = asyncio.run(service.process_emails())
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='email',
            action='scan',
            message=f"Scanned {result['emails_checked']} emails, created {result['tasks_created']} tasks",
            status='success' if result['success'] else 'error'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@email_bp.route('/history')
@login_required
def history():
    """View processed emails history."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    emails = ProcessedEmail.query.filter_by(user_id=current_user.id)\
        .order_by(ProcessedEmail.processed_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('email/history.html', emails=emails)
