"""
Voice Bot Agent Routes
Flask routes for managing voice bots in Teams meetings.
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from models import db, BotConfig
import os

voice_bot_bp = Blueprint('voice_bot', __name__, url_prefix='/voice-bot')


def get_voice_bot_config():
    """Get voice bot configuration from user's bot_config."""
    if not current_user.bot_config:
        # Create default config if not exists
        current_user.bot_config = BotConfig(user=current_user)
        db.session.commit()
    
    config = current_user.bot_config
    return {
        'recall_token': config.recall_ai_token,
        'deepgram_key': config.deepgram_api_key,
        'client_url': config.voice_bot_client_url or 'https://animated-torte-eca718.netlify.app',
        'websocket_url': config.voice_bot_websocket_url or '',
        'port': config.voice_bot_port or 8000,
        'enabled': bool(config.recall_ai_token and config.deepgram_api_key)
    }


@voice_bot_bp.route('/')
@login_required
def dashboard():
    """Voice bot management dashboard."""
    config = get_voice_bot_config()
    
    # Get recent bots
    bots = []
    if config['recall_token']:
        from agents.voice_bot_agent.recall_api import list_bots_sync
        result = list_bots_sync(limit=10, token=config['recall_token'])
        if result.get('success'):
            bots = result.get('bots', {}).get('results', [])
    
    return render_template('voice_bot/dashboard.html',
                         config=config,
                         bots=bots)


@voice_bot_bp.route('/create', methods=['POST'])
@login_required
def create_bot():
    """Create a new voice bot for a meeting."""
    meeting_url = request.form.get('meeting_url', '').strip()
    bot_name = request.form.get('bot_name', 'Alex').strip()
    
    if not meeting_url:
        flash('Meeting URL is required', 'error')
        return redirect(url_for('voice_bot.dashboard'))
    
    config = get_voice_bot_config()
    
    if not config['recall_token']:
        flash('Recall.ai Token not configured. Go to Settings to add it.', 'error')
        return redirect(url_for('voice_bot.dashboard'))
    
    from agents.voice_bot_agent.recall_api import create_bot_sync
    
    result = create_bot_sync(
        meeting_url=meeting_url,
        bot_name=bot_name,
        client_webpage_url=config['client_url'],
        websocket_url=config['websocket_url'],
        token=config['recall_token']
    )
    
    if result.get('success'):
        bot_id = result.get('bot', {}).get('id', 'unknown')
        flash(f'Bot created successfully! ID: {bot_id}', 'success')
    else:
        error = result.get('error', 'Unknown error')
        details = result.get('details', '')
        flash(f'Failed to create bot: {error}. {details}', 'error')
    
    return redirect(url_for('voice_bot.dashboard'))


@voice_bot_bp.route('/status/<bot_id>')
@login_required
def bot_status(bot_id):
    """Get status of a specific bot."""
    config = get_voice_bot_config()
    from agents.voice_bot_agent.recall_api import get_bot_status_sync
    
    result = get_bot_status_sync(bot_id, token=config['recall_token'])
    return jsonify(result)


@voice_bot_bp.route('/delete/<bot_id>', methods=['POST'])
@login_required
def delete_bot(bot_id):
    """Delete/stop a bot."""
    config = get_voice_bot_config()
    from agents.voice_bot_agent.recall_api import delete_bot_sync
    
    result = delete_bot_sync(bot_id, token=config['recall_token'])
    
    if result.get('success'):
        flash('Bot stopped successfully', 'success')
    else:
        flash(f'Failed to stop bot: {result.get("error")}', 'error')
    
    return redirect(url_for('voice_bot.dashboard'))


@voice_bot_bp.route('/api/create', methods=['POST'])
@login_required
def api_create_bot():
    """API endpoint to create a bot (returns JSON)."""
    data = request.get_json() or {}
    meeting_url = data.get('meeting_url', '').strip()
    bot_name = data.get('bot_name', 'Alex').strip()
    
    if not meeting_url:
        return jsonify({'success': False, 'error': 'Meeting URL is required'}), 400
    
    config = get_voice_bot_config()
    
    if not config['recall_token']:
        return jsonify({'success': False, 'error': 'Recall.ai Token not configured'}), 500
    
    from agents.voice_bot_agent.recall_api import create_bot_sync
    
    result = create_bot_sync(
        meeting_url=meeting_url,
        bot_name=bot_name,
        client_webpage_url=config['client_url'],
        websocket_url=config['websocket_url'],
        token=config['recall_token']
    )
    
    return jsonify(result)


@voice_bot_bp.route('/check-schedule', methods=['POST'])
@login_required
def check_schedule():
    """Check for upcoming meetings and auto-join."""
    from agents.voice_bot_agent.scheduler import check_and_join_meetings
    result = check_and_join_meetings(current_user.id)
    return jsonify(result)

@voice_bot_bp.route('/server/status')
@login_required
def server_status():
    """Check if the internal voice server is running."""
    from agents.voice_bot_agent.server_manager import VoiceServerManager
    return jsonify({'running': VoiceServerManager.is_running()})

@voice_bot_bp.route('/server/start', methods=['POST'])
@login_required
def start_server():
    """Start the internal voice server."""
    from agents.voice_bot_agent.server_manager import VoiceServerManager
    VoiceServerManager.start_server()
    return jsonify({'success': True, 'running': VoiceServerManager.is_running()})

@voice_bot_bp.route('/server/stop', methods=['POST'])
@login_required
def stop_server():
    """Stop the internal voice server."""
    from agents.voice_bot_agent.server_manager import VoiceServerManager
    VoiceServerManager.stop_server()
    return jsonify({'success': True, 'running': VoiceServerManager.is_running()})

@voice_bot_bp.route('/api/bots')
@login_required
def api_list_bots():
    """API endpoint to list bots (returns JSON)."""
    config = get_voice_bot_config()
    from agents.voice_bot_agent.recall_api import list_bots_sync
    
    result = list_bots_sync(limit=20, token=config['recall_token'])
    return jsonify(result)

