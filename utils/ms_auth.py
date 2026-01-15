"""
Microsoft Authentication Utilities
Handles automatic token refresh for Microsoft Graph API
"""
from datetime import datetime, timedelta
import msal
import os


def get_msal_app(user_settings):
    """Get MSAL application instance."""
    client_id = user_settings.azure_client_id or os.getenv('AZURE_CLIENT_ID')
    tenant_id = user_settings.azure_tenant_id or os.getenv('AZURE_TENANT_ID', 'common')
    
    return msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}"
    )


def is_token_expired(user_settings):
    """Check if the access token is expired or about to expire."""
    if not user_settings.ms_token_expires_at:
        return True
    
    # Consider token expired if it expires in the next 5 minutes
    expiry_buffer = datetime.utcnow() + timedelta(minutes=5)
    return datetime.utcnow() >= user_settings.ms_token_expires_at or expiry_buffer >= user_settings.ms_token_expires_at


def refresh_access_token(user_settings, db):
    """
    Refresh the Microsoft access token using the refresh token.
    Returns True if successful, False otherwise.
    """
    if not user_settings.ms_refresh_token:
        print(f"No refresh token available for user {user_settings.user_id}")
        return False
    
    try:
        app_msal = get_msal_app(user_settings)
        
        # Attempt to refresh the token - must use same scopes as initial auth
        # Note: offline_access is automatically handled by MSAL
        result = app_msal.acquire_token_by_refresh_token(
            user_settings.ms_refresh_token,
            scopes=[
                "User.Read",
                "Mail.Read",
                "Mail.ReadWrite",
                "OnlineMeetings.Read",
                "OnlineMeetingTranscript.Read.All",
                "Calendars.Read",
                "Chat.Read",
                "Mail.Send",
                "Files.Read.All",
                "Sites.Read.All"
            ]
        )
        
        if "access_token" in result:
            # Update tokens in database
            user_settings.ms_access_token = result['access_token']
            
            if 'refresh_token' in result:
                # Microsoft sometimes returns a new refresh token
                user_settings.ms_refresh_token = result['refresh_token']
            
            if 'expires_in' in result:
                user_settings.ms_token_expires_at = datetime.utcnow() + timedelta(seconds=result['expires_in'])
            
            db.session.commit()
            print(f"Successfully refreshed access token for user {user_settings.user_id}")
            return True
        else:
            error = result.get('error_description', result.get('error', 'Unknown error'))
            print(f"Failed to refresh token for user {user_settings.user_id}: {error}")
            return False
            
    except Exception as e:
        print(f"Error refreshing token for user {user_settings.user_id}: {e}")
        return False


def get_valid_access_token(user_settings, db):
    """
    Get a valid access token, refreshing if necessary.
    Returns the access token or None if refresh failed.
    """
    if not user_settings.ms_access_token:
        return None
    
    # Check if token is expired or about to expire
    if is_token_expired(user_settings):
        print(f"Access token expired or expiring soon for user {user_settings.user_id}, attempting refresh...")
        success = refresh_access_token(user_settings, db)
        
        if not success:
            print(f"Failed to refresh token for user {user_settings.user_id}")
            return None
    
    return user_settings.ms_access_token
