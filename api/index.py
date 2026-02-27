from __future__ import annotations

import json
import os
from typing import Optional

import redis
from fastapi import FastAPI, Request, Response, HTTPException

from liftwatch.snapshot import fetch_snapshot_async
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


@app.get("/api/health")
def health():
    return {"ok": True, "service": "liftwatch"}


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

# --- CRON ENDPOINT ---
@app.get("/api/cron")
async def cron_check(request: Request):
    token = request.headers.get("X-Cron-Secret", "")
    if not CRON_SECRET or token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    snap = await fetch_snapshot_async()

    if r is None:
        raise HTTPException(status_code=500, detail="REDIS_URL not configured")

    print("redis ready")
    for area in SkiArea:
        # --- LIFTS ---
        lifts: list[LiftFacility] = snap.lifts_by_area.get(area, [])
        lifts_updated = max((lf.update_date for lf in lifts if lf.update_date), default=None)

        print(f"before redis in {area}")
        key_l = f"lw:last_posted:lifts:{int(area)}"
        last_posted_l = _b2s(r.get(key_l))
        print(last_posted_l)

        if lifts_updated and _is_newer(lifts_updated, last_posted_l):
            print("updating lifts")
            msg = fmt_lifts(area, lifts, updated=lifts_updated)
            print(msg)
            discord_post(msg)
            print("posted lifts")
            r.set(key_l, lifts_updated)
            print("saved key")

        print("now with weather")

        # --- WEATHER ---
        w: ResortWeather | None = snap.weather_by_area.get(area)
        weather_updated = w.last_updated if w else None

        key_w = f"lw:last_posted:weather:{int(area)}"
        last_posted_w = _b2s(r.get(key_w))

        if weather_updated and _is_newer(weather_updated, last_posted_w):
            msg = fmt_weather(area, w)
            discord_post(msg)
            r.set(key_w, weather_updated)
            print("posted weather")

    return {"ok": True}

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