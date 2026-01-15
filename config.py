import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
    
    # Database - support both PostgreSQL (production) and SQLite (local)
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///app.db')
    # Railway PostgreSQL uses postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis for Celery
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    
    # OpenAI (default app-level key, users can override)
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
    
    # Microsoft Azure AD
    AZURE_CLIENT_ID = os.getenv('AZURE_CLIENT_ID', '')
    AZURE_CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET', '')
    AZURE_TENANT_ID = os.getenv('AZURE_TENANT_ID', 'common')
    AZURE_AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
    
    # Microsoft Graph Scopes
    GRAPH_SCOPES = [
        "User.Read",
        "Mail.Read", 
        "OnlineMeetings.Read",
        "OnlineMeetingTranscript.Read.All",
        "Calendars.Read",
        "Chat.Read",
        "Mail.Send"
    ]
    
    # Encryption for stored secrets
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')
    
    # API Endpoints
    GRAPH_API = "https://graph.microsoft.com/v1.0"
    CLICKUP_API = "https://api.clickup.com/api/v2"
    CLICKUP_API_V3 = "https://api.clickup.com/api/v3"
    
    # Background job intervals (in seconds)
    MEETING_SCAN_INTERVAL = 30 * 60  # 30 minutes
    EMAIL_SCAN_INTERVAL = 5 * 60     # 5 minutes (polling fallback)


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
