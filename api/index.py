import os
import json
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, Response
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = FastAPI()

DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")

# --- Discord signature verification (required) ---
def verify_discord_request(raw_body: bytes, signature: str, timestamp: str) -> bool:
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + raw_body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


# --- Your Niseko scraping / heuristics ---
NISEKO_STATUS_URL = "https://www.niseko.ne.jp/en/niseko-lift-status/"

# A pragmatic "powder-ish" lift list you can tune with the boys
POWDER_LIFTS_KEYWORDS = [
    "King", "Ace", "Gondola", "Hanazono", "Annupuri", "Village"
]

def fetch_lift_status_text() -> str:
    """
    MVP: fetch the official status page and return the visible text.
    We'll refine parsing later (tables -> structured data).
    """
    r = requests.get(NISEKO_STATUS_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    return text


def powder_summary() -> str:
    """
    Super MVP: look for 'Open' lines / keywords.
    You'll improve this once you inspect the HTML structure.
    """
    text = fetch_lift_status_text()

    # ultra-simple heuristic: if keyword appears near "Open", consider it open.
    hits = []
    lower = text.lower()

    for kw in POWDER_LIFTS_KEYWORDS:
        if kw.lower() in lower:
            hits.append(kw)

    if not hits:
        return "😢 I couldn’t detect anything powder-ish from the page text yet. Next step: parse the actual lift table."

    unique = sorted(set(hits))
    return (
        "🏂 **Powder-ish quick picks (heuristic):**\n"
        + " • " + "\n • ".join(unique[:12])
        + "\n\n(Next: I’ll parse the real lift table so this becomes accurate.)"
    )

@app.get("/api/health")
def health():
    return {"ok": True, "service": "liftwatch"}

# --- Discord interactions endpoint ---
@app.post("/api/interactions")
async def interactions(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not DISCORD_PUBLIC_KEY:
        return Response("Server misconfigured: DISCORD_PUBLIC_KEY missing", status_code=500)

    if not verify_discord_request(raw_body, signature, timestamp):
        return Response("invalid request signature", status_code=401)

    payload = json.loads(raw_body.decode("utf-8"))

    # Discord "PING" verification
    if payload.get("type") == 1:
        return {"type": 1}

    # Application command
    if payload.get("type") == 2:
        name = payload["data"]["name"]

        if name == "powder":
            msg = powder_summary()
            return {
                "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
                "data": {"content": msg}
            }

        if name == "status":
            return {
                "type": 4,
                "data": {"content": "✅ liftwatch is alive. Try `/powder`."}
            }

        return {"type": 4, "data": {"content": f"Unknown command: {name}"}}

    return {"type": 4, "data": {"content": "Unhandled interaction type."}}