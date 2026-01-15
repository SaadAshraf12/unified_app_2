"""
Voice Bot WebSocket Server
Real-time voice conversation using Deepgram STT/TTS and OpenAI LLM.

Run this alongside Flask for WebSocket audio streaming:
    python -m agents.voice_bot_agent.server

Or via Celery worker process.
"""

import asyncio
import json
import logging
import os
import time
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
import websockets
from websockets.legacy.server import WebSocketServerProtocol, serve
from websockets.legacy.client import connect
from openai import AsyncOpenAI
import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
# Load environment variables
load_dotenv()
PORT = int(os.getenv("VOICE_BOT_PORT", os.getenv("PORT", 8000)))
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CLICKUP_API_KEY = os.getenv("CLICKUP_API_KEY")

if not DEEPGRAM_API_KEY:
    logger.warning("DEEPGRAM_API_KEY not set - voice bot will not work")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set - voice bot will not work")

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Configuration
TIMEOUT_SECONDS = 50
BOT_NAME = "alex"
SAMPLE_RATE = 48000
WAKE_WORDS = ["hello alex", "hey alex", "alex"]
DISMISSAL_PHRASES = ["that's all", "thanks alex", "goodbye", "bye", "see you", "stop"]

# ClickUp configuration
CLICKUP_SPACE_NAME = "AI Context"
CLICKUP_SUMMARY_DOC_NAME = "Daily Standup Summary By AI"
CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            current_row.append(min(previous_row[j + 1] + 1, current_row[j] + 1, previous_row[j] + (c1 != c2)))
        previous_row = current_row
    return previous_row[-1]


def fuzzy_match(text: str, target: str, threshold: float = 0.7) -> bool:
    text, target = text.lower().strip(), target.lower().strip()
    if target in text:
        return True
    words, target_words = text.split(), target.split()
    for i in range(len(words) - len(target_words) + 1):
        phrase = " ".join(words[i:i + len(target_words)])
        similarity = 1 - (levenshtein_distance(phrase, target) / max(len(phrase), len(target)))
        if similarity >= threshold:
            return True
    return False


# =============================================================================
# CLICKUP SUMMARY LOADER
# =============================================================================

class ClickUpSummaryLoader:
    """Loads pre-made summary from ClickUp Doc."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": api_key, "Content-Type": "application/json"}
        self.summary: str = ""
        self.loaded_at: Optional[datetime] = None
        self.source: str = ""
    
    async def load_summary(self) -> bool:
        """Load the pre-made summary from ClickUp Doc."""
        # Debug: Log API key format (first 10 chars only for security)
        key_preview = self.api_key[:10] if self.api_key else "NONE"
        logger.info(f"🔑 ClickUp API Key starts with: {key_preview}...")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get teams
                response = await client.get(f"{CLICKUP_BASE_URL}/team", headers=self.headers)
                
                # Debug: Log full response on error
                if response.status_code != 200:
                    logger.error(f"❌ ClickUp /team failed: {response.status_code}")
                    logger.error(f"   Response: {response.text[:200]}")
                    return False
                
                teams = response.json().get("teams", [])
                if not teams:
                    logger.warning("No teams found in ClickUp")
                    return False
                
                team_id = teams[0]["id"]
                
                # Get docs
                docs_url = f"https://api.clickup.com/api/v3/workspaces/{team_id}/docs"
                response = await client.get(docs_url, headers=self.headers)
                
                if response.status_code != 200:
                    return False
                
                docs = response.json().get("docs", [])
                target_doc = None
                for doc in docs:
                    if doc.get("name", "").lower() == CLICKUP_SUMMARY_DOC_NAME.lower():
                        target_doc = doc
                        break
                
                if not target_doc:
                    return False
                
                doc_id = target_doc["id"]
                
                # Get doc pages
                pages_url = f"https://api.clickup.com/api/v3/workspaces/{team_id}/docs/{doc_id}/pages"
                response = await client.get(pages_url, headers=self.headers)
                
                if response.status_code != 200:
                    return False
                
                pages_data = response.json()
                pages = pages_data if isinstance(pages_data, list) else pages_data.get("pages", [])
                if not pages:
                    return False
                
                page_id = pages[0]["id"]
                page_url = f"https://api.clickup.com/api/v3/workspaces/{team_id}/docs/{doc_id}/pages/{page_id}"
                response = await client.get(page_url, headers=self.headers)
                
                if response.status_code != 200:
                    return False
                
                page_data = response.json()
                content = page_data.get("content", "")
                
                if content and len(content) > 10:
                    self.summary = content
                    self.loaded_at = datetime.now()
                    self.source = f"ClickUp Doc: {CLICKUP_SUMMARY_DOC_NAME}"
                    logger.info(f"✅ Loaded summary from ClickUp ({len(content)} chars)")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Failed to load from ClickUp: {e}")
            return False
    
    def get_summary_for_context(self) -> str:
        if not self.summary:
            return "ClickUp project data not available."
        return f"=== ClickUp Project Summary ===\n\n{self.summary}\n\n=== End ==="


# =============================================================================
# MEETING MEMORY
# =============================================================================

@dataclass
class MeetingMemory:
    conversation_summary: str = ""
    recent_messages: List[Dict[str, str]] = field(default_factory=list)
    
    def add_bot_interaction(self, role: str, content: str):
        if content.strip():
            self.recent_messages.append({"role": role, "content": content.strip()})
    
    def get_context_for_llm(self) -> List[Dict[str, str]]:
        return [{"role": m["role"], "content": m["content"]} for m in self.recent_messages[-20:]]


# =============================================================================
# CONVERSATION STATE
# =============================================================================

@dataclass
class ConversationState:
    is_active: bool = False
    last_interaction_time: float = 0
    agent_is_speaking: bool = False
    recent_responses: List[str] = field(default_factory=list)
    interrupted: bool = False
    memory: MeetingMemory = field(default_factory=MeetingMemory)
    
    def activate(self):
        self.is_active = True
        self.last_interaction_time = time.time()
        self.interrupted = False
        logger.info(f"🟢 {BOT_NAME} activated")
    
    def deactivate(self):
        self.is_active = False
        logger.info(f"⚪ {BOT_NAME} deactivated")
    
    def reset_for_new_meeting(self):
        self.is_active = False
        self.interrupted = False
        self.recent_responses = []
        self.memory = MeetingMemory()
    
    def detect_wake_word(self, text: str) -> bool:
        for wake_word in WAKE_WORDS:
            if fuzzy_match(text.lower(), wake_word, threshold=0.75):
                logger.info(f"Wake word detected: '{wake_word}'")
                return True
        return False
    
    def detect_dismissal(self, text: str) -> bool:
        return any(phrase in text.lower() for phrase in DISMISSAL_PHRASES)
    
    def is_echo(self, transcript: str) -> bool:
        transcript_lower = transcript.lower().strip()
        for response in self.recent_responses[-5:]:
            if transcript_lower in response.lower() or response.lower() in transcript_lower:
                return True
        return False
    
    def interrupt(self):
        self.interrupted = True
        self.agent_is_speaking = False
        logger.info("🔇 Speech interrupted")


# =============================================================================
# DEEPGRAM CONNECTIONS
# =============================================================================

async def connect_to_deepgram_stt():
    """Connect to Deepgram STT WebSocket."""
    params = [
        "model=nova-2",
        "encoding=linear16",
        f"sample_rate={SAMPLE_RATE}",
        "channels=1",
        "punctuate=true",
        "smart_format=true",
        "interim_results=true",
        "utterance_end_ms=1000",
        "vad_events=true",
        "endpointing=300"
    ]
    url = "wss://api.deepgram.com/v1/listen?" + "&".join(params)
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    
    logger.info("🔗 Connecting to Deepgram STT...")
    ws = await connect(url, extra_headers=headers, ping_interval=20, ping_timeout=10)
    logger.info("✅ Connected to Deepgram STT")
    return ws


class DeepgramTTSStreamer:
    """Real-time TTS streaming using Deepgram WebSocket API."""
    
    def __init__(self, browser_ws: WebSocketServerProtocol):
        self.browser_ws = browser_ws
        self.tts_ws = None
        self.is_connected = False
        self.audio_receiver_task = None
        self.interrupted = False
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.first_audio_time = None
        self.start_time = None
    
    async def connect(self):
        """Connect to Deepgram TTS WebSocket."""
        url = f"wss://api.deepgram.com/v1/speak?model=aura-2-thalia-en&encoding=linear16&sample_rate={SAMPLE_RATE}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        
        logger.info("🔊 Connecting to Deepgram TTS...")
        
        self.tts_ws = await connect(
            url,
            extra_headers=headers,
            open_timeout=30,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=5
        )
        
        self.is_connected = True
        self.start_time = time.time()
        self.interrupted = False
        self.audio_receiver_task = asyncio.create_task(self._receive_and_forward_audio())
        
        logger.info("✅ Connected to Deepgram TTS")
    
    async def _receive_and_forward_audio(self):
        """Receive audio from Deepgram and forward to browser."""
        try:
            while self.is_connected and self.tts_ws:
                try:
                    message = await asyncio.wait_for(self.tts_ws.recv(), timeout=0.1)
                    
                    if self.interrupted:
                        continue
                    
                    if isinstance(message, bytes):
                        if self.first_audio_time is None:
                            self.first_audio_time = time.time()
                            latency = (self.first_audio_time - self.start_time) * 1000
                            logger.info(f"⚡ First audio chunk! Latency: {latency:.0f}ms")
                        
                        self.chunks_sent += 1
                        self.bytes_sent += len(message)
                        
                        if not self.browser_ws.closed:
                            await self.browser_ws.send(message)
                    else:
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type", "")
                            if msg_type == "Error":
                                logger.error(f"❌ TTS Error: {data}")
                        except:
                            pass
                
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"TTS receiver error: {e}")
    
    async def send_text(self, text: str):
        """Send text to Deepgram TTS."""
        if not self.is_connected or not self.tts_ws or not text.strip():
            return
        
        try:
            await self.tts_ws.send(json.dumps({"type": "Speak", "text": text}))
        except Exception as e:
            logger.error(f"Failed to send text to TTS: {e}")
    
    async def flush(self):
        """Send Flush to generate audio."""
        if not self.is_connected or not self.tts_ws:
            return
        try:
            await self.tts_ws.send(json.dumps({"type": "Flush"}))
        except Exception as e:
            logger.error(f"Failed to send flush: {e}")
    
    async def clear(self):
        """Send Clear to stop audio."""
        if not self.is_connected or not self.tts_ws:
            return
        self.interrupted = True
        try:
            await self.tts_ws.send(json.dumps({"type": "Clear"}))
        except Exception as e:
            logger.error(f"Failed to send clear: {e}")
    
    def reset_for_new_response(self):
        self.interrupted = False
        self.first_audio_time = None
        self.start_time = time.time()
        self.chunks_sent = 0
        self.bytes_sent = 0
    
    async def close(self):
        self.is_connected = False
        
        if self.audio_receiver_task:
            self.audio_receiver_task.cancel()
            try:
                await self.audio_receiver_task
            except asyncio.CancelledError:
                pass
        
        if self.tts_ws:
            try:
                await self.tts_ws.send(json.dumps({"type": "Close"}))
                await self.tts_ws.close()
            except:
                pass


# =============================================================================
# WEBSOCKET RELAY
# =============================================================================

class WebSocketRelay:
    """WebSocket relay with real-time streaming TTS."""
    
    def __init__(self, summary_loader: Optional[ClickUpSummaryLoader] = None):
        self.conversation_state = ConversationState()
        self.browser_ws: Optional[WebSocketServerProtocol] = None
        self.deepgram_stt_ws = None
        self.tts_streamer: Optional[DeepgramTTSStreamer] = None
        self.summary_loader = summary_loader
    
    async def send_state_update(self):
        if not self.browser_ws:
            return
        state = {
            "type": "alexState",
            "active": self.conversation_state.is_active,
            "speaking": self.conversation_state.agent_is_speaking,
        }
        try:
            await self.browser_ws.send(json.dumps(state))
        except:
            pass
    
    def _build_system_message(self) -> Dict[str, str]:
        clickup_context = ""
        if self.summary_loader and self.summary_loader.summary:
            clickup_context = f"\n\n{self.summary_loader.get_summary_for_context()}"
        
        return {
            "role": "system",
            "content": f"""You are {BOT_NAME}, a helpful AI assistant in a meeting.
{clickup_context}
Guidelines:
- Be concise and natural
- Keep responses brief (1-3 sentences)
- Don't use markdown formatting"""
        }
    
    async def stream_llm_to_tts(self):
        """Stream LLM response directly to TTS WebSocket."""
        self.conversation_state.agent_is_speaking = True
        await self.send_state_update()
        
        if not self.tts_streamer or not self.tts_streamer.is_connected:
            self.tts_streamer = DeepgramTTSStreamer(self.browser_ws)
            await self.tts_streamer.connect()
        
        self.tts_streamer.reset_for_new_response()
        full_response = ""
        
        try:
            system_message = self._build_system_message()
            context_messages = self.conversation_state.memory.get_context_for_llm()
            messages = [system_message] + context_messages
            
            logger.info("🤖 Streaming LLM → TTS...")
            
            stream = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=400,
                stream=True
            )
            
            async for chunk in stream:
                if self.conversation_state.interrupted:
                    await self.tts_streamer.clear()
                    break
                
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    await self.tts_streamer.send_text(token)
            
            if not self.conversation_state.interrupted:
                await self.tts_streamer.flush()
                await asyncio.sleep(0.5)
            
            if full_response and not self.conversation_state.interrupted:
                self.conversation_state.memory.add_bot_interaction("assistant", full_response)
                self.conversation_state.recent_responses.append(full_response)
            
        except Exception as e:
            logger.error(f"LLM→TTS error: {e}")
        finally:
            self.conversation_state.agent_is_speaking = False
            await self.send_state_update()
    
    async def speak_text(self, text: str):
        """Speak a simple text message."""
        if not self.tts_streamer or not self.tts_streamer.is_connected:
            self.tts_streamer = DeepgramTTSStreamer(self.browser_ws)
            await self.tts_streamer.connect()
        
        self.tts_streamer.reset_for_new_response()
        await self.tts_streamer.send_text(text)
        await self.tts_streamer.flush()
        await asyncio.sleep(1.0)
    
    async def handle_transcript(self, transcript_text: str, is_final: bool):
        """Handle transcribed text."""
        transcript_text = transcript_text.strip()
        if not transcript_text:
            return
        
        # Check for interruption
        if self.conversation_state.agent_is_speaking:
            if len(transcript_text.split()) >= 2 or self.conversation_state.detect_wake_word(transcript_text):
                logger.info(f"🔇 Interruption: {transcript_text[:50]}...")
                self.conversation_state.interrupt()
                
                if self.tts_streamer:
                    await self.tts_streamer.clear()
                
                await self.browser_ws.send(json.dumps({"type": "Interrupt", "reason": "user_speech"}))
                
                if not is_final:
                    return
        
        if not is_final:
            return
        
        if self.conversation_state.is_echo(transcript_text):
            return
        
        # Wake word detection
        if not self.conversation_state.is_active:
            if self.conversation_state.detect_wake_word(transcript_text):
                self.conversation_state.activate()
                await self.send_state_update()
                
                for wake_word in WAKE_WORDS:
                    transcript_text = re.sub(r'\b' + re.escape(wake_word) + r'\b', '', transcript_text, flags=re.IGNORECASE)
                transcript_text = transcript_text.strip() or "Hello"
            else:
                return
        
        # Dismissal
        if self.conversation_state.detect_dismissal(transcript_text):
            logger.info("🛑 Dismissal detected")
            self.conversation_state.interrupt()
            
            if self.tts_streamer:
                await self.tts_streamer.clear()
            
            await asyncio.sleep(0.1)
            self.conversation_state.interrupted = False
            await self.speak_text("Goodbye! I'll still be listening if you need me.")
            
            self.conversation_state.deactivate()
            await self.send_state_update()
            return
        
        self.conversation_state.last_interaction_time = time.time()
        self.conversation_state.memory.add_bot_interaction("user", transcript_text)
        logger.info(f"👤 User: {transcript_text}")
        
        asyncio.create_task(self.stream_llm_to_tts())
    
    async def relay_messages(self, browser_ws: WebSocketServerProtocol, deepgram_ws):
        """Relay messages between browser and Deepgram STT."""
        self.browser_ws = browser_ws
        self.deepgram_stt_ws = deepgram_ws
        
        async def browser_to_deepgram():
            try:
                async for message in browser_ws:
                    if isinstance(message, bytes):
                        await deepgram_ws.send(message)
                    else:
                        try:
                            data = json.loads(message)
                            if data.get("type") == "Interrupt":
                                self.conversation_state.interrupt()
                                if self.tts_streamer:
                                    await self.tts_streamer.clear()
                        except:
                            pass
            except websockets.exceptions.ConnectionClosed:
                pass
        
        async def deepgram_to_browser():
            try:
                async for message in deepgram_ws:
                    if isinstance(message, bytes):
                        continue
                    
                    try:
                        data = json.loads(message)
                        
                        if data.get("type") == "Results":
                            alternatives = data.get("channel", {}).get("alternatives", [])
                            is_final = data.get("is_final", False)
                            
                            if alternatives:
                                transcript = alternatives[0].get("transcript", "")
                                if transcript:
                                    await self.handle_transcript(transcript, is_final)
                        
                        await browser_ws.send(json.dumps(data))
                    except:
                        pass
            except websockets.exceptions.ConnectionClosed:
                pass
        
        await asyncio.gather(browser_to_deepgram(), deepgram_to_browser(), return_exceptions=True)
    
    async def handle_connection(self, browser_ws: WebSocketServerProtocol):
        """Handle browser connection."""
        logger.info("🌐 Browser connected")
        
        self.conversation_state.reset_for_new_meeting()
        
        try:
            if self.summary_loader:
                await self.summary_loader.load_summary()
            
            deepgram_ws = await connect_to_deepgram_stt()
            self.deepgram_stt_ws = deepgram_ws
            
            self.tts_streamer = DeepgramTTSStreamer(browser_ws)
            await self.tts_streamer.connect()
            
            self.browser_ws = browser_ws
            await self.send_state_update()
            
            logger.info("🚀 Voice bot ready")
            
            await self.relay_messages(browser_ws, deepgram_ws)
            
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.tts_streamer:
                await self.tts_streamer.close()
            
            logger.info("👋 Connection closed")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    summary_loader = None
    if CLICKUP_API_KEY:
        summary_loader = ClickUpSummaryLoader(CLICKUP_API_KEY)
        await summary_loader.load_summary()
    
    relay = WebSocketRelay(summary_loader)
    
    async with serve(relay.handle_connection, "0.0.0.0", PORT):
        logger.info(f"🚀 Voice Bot Server on ws://0.0.0.0:{PORT}")
        logger.info(f"📣 Wake words: {', '.join(WAKE_WORDS)}")
        logger.info(f"🔊 TTS: Deepgram WebSocket (aura-2-thalia-en)")
        logger.info(f"🎤 STT: Deepgram WebSocket (nova-2)")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutdown")
