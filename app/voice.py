"""
Voice note transcription module using ElevenLabs (Shahana's P1 Task).
Bounded download/transcription outside any DB transaction.
"""
import logging
import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Hard limits to prevent memory exhaustion and hangs
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5 MB max
TELEGRAM_TIMEOUT_S = 10.0
ELEVENLABS_TIMEOUT_S = 20.0


async def download_and_transcribe(file_id: str) -> str:
    """
    Downloads a voice note from Telegram (OGG OPUS) and transcribes it
    using ElevenLabs STT API (scribe_v1).
    
    Raises RuntimeError on any failure (download error, file too large, transcription error).
    The caller (model_agent) must catch this and ask the user to type instead.
    """
    if not settings.telegram_bot_token:
        raise RuntimeError("Missing telegram_bot_token")
    if not settings.elevenlabs_api_key or settings.elevenlabs_api_key == "your_elevenlabs_api_key_here":
        raise RuntimeError("Missing elevenlabs_api_key")

    telegram_bot_token = settings.telegram_bot_token
    
    # 1. Get file path from Telegram
    get_file_url = f"https://api.telegram.org/bot{telegram_bot_token}/getFile"
    async with httpx.AsyncClient(timeout=TELEGRAM_TIMEOUT_S) as client:
        resp = await client.get(get_file_url, params={"file_id": file_id})
        
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram getFile failed: {resp.status_code} {resp.text}")
            
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getFile not ok: {data}")
            
        file_path = data["result"]["file_path"]
        file_size = data["result"].get("file_size", 0)
        
        if file_size > MAX_AUDIO_BYTES:
            raise RuntimeError(f"Voice note too large: {file_size} bytes (max {MAX_AUDIO_BYTES})")
            
        # 2. Download the actual audio bytes
        download_url = f"https://api.telegram.org/file/bot{telegram_bot_token}/{file_path}"
        audio_resp = await client.get(download_url)
        
        if audio_resp.status_code != 200:
            raise RuntimeError(f"Telegram file download failed: {audio_resp.status_code}")
            
        audio_bytes = audio_resp.content
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise RuntimeError("Voice note exceeded size limit during download")

    log.info("Downloaded %d bytes from Telegram (file_id=%s)", len(audio_bytes), file_id)

    # 3. Transcribe via ElevenLabs STT
    elevenlabs_url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    
    # Send as audio/ogg since Telegram voice notes are OGG OPUS
    files = {"file": ("voice_note.ogg", audio_bytes, "audio/ogg")}
    form_data = {"model_id": "scribe_v1"}
    
    log.info("Sending voice note to ElevenLabs (file_id=%s)", file_id)
    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_S) as client:
        stt_resp = await client.post(
            elevenlabs_url, 
            headers=headers, 
            files=files, 
            data=form_data
        )
        
        if stt_resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs STT failed: {stt_resp.status_code} {stt_resp.text}")
            
        stt_data = stt_resp.json()
        transcript = stt_data.get("text", "").strip()
        
        if not transcript:
            raise RuntimeError("ElevenLabs returned empty transcript")
            
        log.info("Transcription successful (file_id=%s): %r", file_id, transcript)
        return transcript
