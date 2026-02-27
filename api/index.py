from __future__ import annotations

import json
import os
import secrets
from typing import Optional

import redis
from fastapi import FastAPI, Request, Response, HTTPException

from liftwatch.fetcher.fetcher import fetch_snapshot_async
from liftwatch.ski_area import SkiArea
from liftwatch.discord import discord_post, verify_discord_request
from liftwatch.fetcher.weather import WeatherPoint, ResortWeather
from liftwatch.fetcher.facility import LiftFacility
from liftwatch.formatter import powder_summary, summary_message, fmt_lifts, fmt_weather

app = FastAPI()

REDIS_URL = os.environ.get("REDIS_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# --- Redis connection ---
r = redis.Redis.from_url(REDIS_URL) if REDIS_URL else None

def _require_bearer_auth(request: Request) -> None:
    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth.split(" ", 1)[1].strip()

    if not CRON_SECRET:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")

    if not secrets.compare_digest(token, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Invalid token")

def _b2s(x: object) -> Optional[str]:
    """Redis returns bytes; normalize to str."""
    if x is None:
        return None
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", errors="ignore")
    return str(x)


def _is_newer(new: Optional[str], old: Optional[str]) -> bool:
    if not new:
        return False
    if not old:
        return True
    return new > old  # ISO timestamps compare lexicographically OK

@app.get("/api/health")
def health():
    return {"ok": True, "service": "liftwatch"}

# --- CRON ENDPOINT ---
@app.get("/api/cron")
async def cron_check(request: Request):
    _require_bearer_auth(request)

    snap = await fetch_snapshot_async()

    if r is None:
        raise HTTPException(status_code=500, detail="REDIS_URL not configured")

    results: dict[str, dict[str, bool]] = {}

    for area in SkiArea:
        area_id = str(int(area))
        results[area_id] = {"lifts": False, "weather": False}

        # --- LIFTS ---
        lifts: list[LiftFacility] = snap.lifts_by_area.get(area, [])
        lifts_updated = max((lift.update_date for lift in lifts if lift.update_date), default=None)

        key_l = f"lw:last_posted:lifts:{int(area)}"
        last_posted_l = _b2s(r.get(key_l))

        if lifts_updated and _is_newer(lifts_updated, last_posted_l):
            msg = fmt_lifts(area, lifts, lifts_updated)
            discord_post(msg)
            r.set(key_l, lifts_updated)
            results[area_id]["lifts"] = True

        # --- WEATHER ---
        w: ResortWeather | None = snap.weather_by_area.get(area)
        weather_updated = w.last_updated if w else None

        key_w = f"lw:last_posted:weather:{int(area)}"
        last_posted_w = _b2s(r.get(key_w))

        if weather_updated and _is_newer(weather_updated, last_posted_w):
            msg = fmt_weather(area, w)
            discord_post(msg)
            r.set(key_w, weather_updated)
            results[area_id]["weather"] = True

    return {"ok": True, "updated": results}

# --- Discord interactions endpoint ---
@app.post("/api/interactions")
async def interactions(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not verify_discord_request(raw_body, signature, timestamp):
        return Response("invalid request signature", status_code=401)

    payload = json.loads(raw_body.decode("utf-8"))

    # Discord "PING" verification
    if payload.get("type") == 1:
        return {"type": 1}

    # Application command
    if payload.get("type") == 2:
        name = (payload.get("data") or {}).get("name")

        snap = await fetch_snapshot_async()

        if name == "powder":
            msg = powder_summary(snap)
            return {"type": 4, "data": {"content": msg}}

        if name == "summary":
            return {"type": 4, "data": {"content": summary_message(snap)}}

        if name == "status":
            return {"type": 4, "data": {"content": "✅ liftwatch is alive. Try `/summary` or `/powder`."}}

        # Future: add options like /weather area:HANAZONO
        return {"type": 4, "data": {"content": f"Unknown command: {name}"}}

    return {"type": 4, "data": {"content": "Unhandled interaction type."}}