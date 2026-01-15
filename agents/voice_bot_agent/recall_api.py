"""
Recall.ai API Helper
Manages creation and monitoring of Recall.ai bots for Teams meetings.
"""
import os
import httpx
from typing import Optional, Dict, Any

RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"

# Module-level token storage (set by routes when needed)
_current_token: Optional[str] = None


def set_recall_token(token: str):
    """Set the Recall.ai token for API calls."""
    global _current_token
    _current_token = token


def get_recall_token() -> Optional[str]:
    """Get Recall.ai API token from module state or environment."""
    return _current_token or os.getenv('RECALL_AI_TOKEN')


async def create_bot(
    meeting_url: str,
    bot_name: str = "Alex",
    client_webpage_url: str = None,
    websocket_url: str = None,
    token: str = None
) -> Dict[str, Any]:
    """
    Create a Recall.ai bot to join a meeting.
    
    Args:
        meeting_url: Teams/Zoom/Meet URL
        bot_name: Display name for the bot
        client_webpage_url: URL to the React client (hosted on Netlify or server)
        websocket_url: WebSocket URL for the voice server
        token: Optional Recall.ai API token (uses module token if not provided)
    
    Returns:
        Dict with bot creation response
    """
    api_token = token or get_recall_token()
    if not api_token:
        return {"error": "RECALL_AI_TOKEN not configured"}
    
    headers = {
        "Authorization": f"Token {api_token}",
        "accept": "application/json",
        "content-type": "application/json"
    }
    
    # Build the client URL with websocket parameter
    if client_webpage_url and websocket_url:
        full_client_url = f"{client_webpage_url}?wss={websocket_url}&autostart=true"
    else:
        full_client_url = client_webpage_url or ""
    
    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "output_media": {
            "camera": {
                "kind": "webpage",
                "config": {
                    "url": full_client_url
                }
            }
        },
        "variant": {
            "zoom": "web_4_core",
            "google_meet": "web_4_core",
            "microsoft_teams": "web_4_core"
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{RECALL_API_BASE}/bot/",
                headers=headers,
                json=body
            )
            
            if response.status_code in [200, 201]:
                return {"success": True, "bot": response.json()}
            else:
                return {
                    "success": False,
                    "error": f"API error: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_bot_status(bot_id: str, token: str = None) -> Dict[str, Any]:
    """Get status of a Recall.ai bot."""
    api_token = token or get_recall_token()
    if not api_token:
        return {"error": "RECALL_AI_TOKEN not configured"}
    
    headers = {
        "Authorization": f"Token {api_token}",
        "accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers=headers
            )
            
            if response.status_code == 200:
                return {"success": True, "bot": response.json()}
            else:
                return {"success": False, "error": response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_bots(limit: int = 20, token: str = None) -> Dict[str, Any]:
    """List recent Recall.ai bots."""
    api_token = token or get_recall_token()
    if not api_token:
        return {"error": "RECALL_AI_TOKEN not configured"}
    
    headers = {
        "Authorization": f"Token {api_token}",
        "accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{RECALL_API_BASE}/bot/?limit={limit}",
                headers=headers
            )
            
            if response.status_code == 200:
                return {"success": True, "bots": response.json()}
            else:
                return {"success": False, "error": response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_bot(bot_id: str, token: str = None) -> Dict[str, Any]:
    """Delete/stop a Recall.ai bot."""
    api_token = token or get_recall_token()
    if not api_token:
        return {"error": "RECALL_AI_TOKEN not configured"}
    
    headers = {
        "Authorization": f"Token {api_token}",
        "accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers=headers
            )
            
            if response.status_code in [200, 204]:
                return {"success": True}
            else:
                return {"success": False, "error": response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Synchronous wrappers for Flask routes
def create_bot_sync(meeting_url: str, bot_name: str = "Alex", 
                    client_webpage_url: str = None, websocket_url: str = None,
                    token: str = None) -> Dict[str, Any]:
    """Synchronous wrapper for create_bot."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            create_bot(meeting_url, bot_name, client_webpage_url, websocket_url, token)
        )
    finally:
        loop.close()


def get_bot_status_sync(bot_id: str, token: str = None) -> Dict[str, Any]:
    """Synchronous wrapper for get_bot_status."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(get_bot_status(bot_id, token))
    finally:
        loop.close()


def list_bots_sync(limit: int = 20, token: str = None) -> Dict[str, Any]:
    """Synchronous wrapper for list_bots."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(list_bots(limit, token))
    finally:
        loop.close()


def delete_bot_sync(bot_id: str, token: str = None) -> Dict[str, Any]:
    """Synchronous wrapper for delete_bot."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(delete_bot(bot_id, token))
    finally:
        loop.close()

