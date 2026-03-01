import os
import requests
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
DISCORD_FACILITIES_WEBHOOK_URL = os.environ.get("DISCORD_FACILITIES_WEBHOOK_URL", "")
DISCORD_WEATHER_WEBHOOK_URL = os.environ.get("DISCORD_WEATHER_WEBHOOK_URL", "")

def _discord_post(content: str, webhook_url: str) -> None:
    resp = requests.post(webhook_url, json={"content": content}, timeout=10)
    resp.raise_for_status()

def post_facilities_channel(content: str) -> None:
    if not DISCORD_FACILITIES_WEBHOOK_URL:
        raise ValueError("DISCORD_FACILITIES_WEBHOOK_URL is not set")
    _discord_post(content, DISCORD_FACILITIES_WEBHOOK_URL)

def post_weather_channel(content: str) -> None:
    if not DISCORD_WEATHER_WEBHOOK_URL:
        raise ValueError("DISCORD_WEATHER_WEBHOOK_URL is not set")
    _discord_post(content, DISCORD_WEATHER_WEBHOOK_URL)

def verify_request(raw_body: bytes, signature: str, timestamp: str) -> bool:
    if not DISCORD_PUBLIC_KEY:
        return False
    if not signature or not timestamp:
        return False
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode("utf-8") + raw_body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False