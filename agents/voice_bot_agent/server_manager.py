import subprocess
import sys
import os
import time
import signal
import logging
from typing import Optional
from models import BotConfig, db
from app import app

logger = logging.getLogger(__name__)

class VoiceServerManager:
    _process: Optional[subprocess.Popen] = None
    
    @classmethod
    def is_running(cls) -> bool:
        if cls._process is None:
            return False
        return cls._process.poll() is None

    @classmethod
    def start_server(cls):
        if cls.is_running():
            logger.info("Voice server is already running.")
            return

        if os.getenv("EXTERNAL_VOICE_SERVER", "false").lower() == "true":
            logger.info("External voice server configured. Skipping subprocess start.")
            return

        logger.info("Starting Voice Bot Server...")
        
        # Fetch config from DB
        with app.app_context():
            config = BotConfig.query.first()
            if not config:
                logger.error("No BotConfig found. Cannot start server.")
                return
            
            # Prepare environment variables
            env = os.environ.copy()
            
            # Decrypt secrets
            # Note: models.BotConfig properties handle decryption automatically
            if config.deepgram_api_key:
                env['DEEPGRAM_API_KEY'] = config.deepgram_api_key
            if config.recall_ai_token:
                env['RECALL_AI_TOKEN'] = config.recall_ai_token
            
            env['VOICE_BOT_PORT'] = str(config.voice_bot_port or 8000)
            
            # OpenAI Key should come from settings or env
            # Here assuming it's in os.environ or we fetch from user settings if needed
            # For now, let's assume it's set in .env or passed through
            
        # Command to run module
        cmd = [sys.executable, "-m", "agents.voice_bot_agent.server"]
        
        try:
            cls._process = subprocess.Popen(
                cmd,
                env=env,
                cwd=os.getcwd(),
                # stdout=subprocess.PIPE, 
                # stderr=subprocess.PIPE
                # We let it print to main console for now for debug visibility
            )
            logger.info(f"Voice Bot Server started with PID {cls._process.pid}")
            
            # Wait a moment to check if it crashes immediately
            time.sleep(2)
            if not cls.is_running():
                logger.error("Voice Bot Server failed to start immediately.")
                cls._process = None
                
        except Exception as e:
            logger.error(f"Failed to start Voice Bot Server: {e}")

    @classmethod
    def stop_server(cls):
        if cls._process and cls.is_running():
            logger.info("Stopping Voice Bot Server...")
            cls._process.terminate()
            try:
                cls._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._process.kill()
            cls._process = None
            logger.info("Voice Bot Server stopped.")
