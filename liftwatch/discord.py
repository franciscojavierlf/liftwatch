import os
import requests
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from typing import List, Optional
from fastapi import Response

from ski_area import SkiArea
from fetcher.facility import LiftFacility
from fetcher.weather import ResortWeather

DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def discord_post(content: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    resp.raise_for_status()

# --- Discord signature verification (required) ---
def verify_discord_request(raw_body: bytes, signature: str, timestamp: str) -> bool:

    if not DISCORD_PUBLIC_KEY:
        return Response("Server misconfigured: DISCORD_PUBLIC_KEY missing", status_code=500)
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + raw_body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
