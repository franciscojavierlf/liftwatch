import os
import requests
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def discord_post(content: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    resp.raise_for_status()

def verify_discord_request(raw_body: bytes, signature: str, timestamp: str) -> bool:
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