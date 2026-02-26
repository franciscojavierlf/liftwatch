import os
import re
import json
import requests
import redis
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, Response, HTTPException
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = FastAPI()

DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

LAST_UPDATED_KEY = "liftwatch:last_updated"
NISEKO_STATUS_URL = "https://www.niseko.ne.jp/en/niseko-lift-status/"

# --- Your Niseko scraping / heuristics ---
NISEKO_STATUS_URL = "https://www.niseko.ne.jp/en/niseko-lift-status/"

# A pragmatic "powder-ish" lift list you can tune with the boys
POWDER_LIFTS_KEYWORDS = [
    "King", "Ace", "Gondola", "Hanazono", "Annupuri", "Village"
]

# --- Redis connection ---
r = redis.Redis.from_url(REDIS_URL)

def discord_post(content: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    resp.raise_for_status()


def extract_last_updated(html: str) -> str | None:
    """
    Try to find 'Last updated' text on the page.
    We'll refine if needed.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    m = re.search(r"(Last\s*updated[^.:\n]*[:\s]\s*[^|]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None

# --- Discord signature verification (required) ---
def verify_discord_request(raw_body: bytes, signature: str, timestamp: str) -> bool:
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + raw_body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False

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

# --- CRON ENDPOINT ---
@app.get("/api/cron")
def cron_check(request: Request):

    token = request.headers.get("X-Cron-Secret", "")
    if not CRON_SECRET or token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        resp = requests.get(NISEKO_STATUS_URL, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {e}")

    last_updated = extract_last_updated(resp.text)

    if not last_updated:
        last_updated = "Last updated: (not detected)"

    prev = r.get(LAST_UPDATED_KEY)
    prev = prev.decode() if prev else None

    # --- If changed → alert ---
    if prev != last_updated:
        r.set(LAST_UPDATED_KEY, last_updated)

        message = (
            "🚨 **Niseko lift status updated**\n"
            f"{last_updated}\n"
            f"{NISEKO_STATUS_URL}"
        )

        discord_post(message)

        return {
            "changed": True,
            "previous": prev,
            "current": last_updated
        }

    # --- No change ---
    return {
        "changed": False,
        "current": last_updated
    }

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