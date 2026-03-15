from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis
from fastapi import FastAPI, Request, Response, HTTPException

from liftwatch.fetcher.fetcher import fetch_snapshot_async
from liftwatch.ski_area import SkiArea
import liftwatch.discord as discord
from liftwatch.fetcher.weather import ResortWeather
from liftwatch.fetcher.facility import LiftFacility
from liftwatch.formatter import powder_summary, summary_message, fmt_lift_mass_suspension, fmt_lift_recovery, fmt_weather

app = FastAPI()

REDIS_URL = os.environ.get("REDIS_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# --- Redis connection ---
r = redis.Redis.from_url(REDIS_URL) if REDIS_URL else None

REDIS_KEY_PAUSED = "lw:cron_paused"
JST = timezone(timedelta(hours=9))
CRON_START_HOUR = 5    # 5:00 AM JST
CRON_END_HOUR = 20     # 8:00 PM JST
WEATHER_END_HOUR = 12  # 12:00 PM JST — weather alerts only posted 5 AM–12 PM


def _is_paused() -> bool:
    if r is None:
        return False
    val = r.get(REDIS_KEY_PAUSED)
    return val is not None and val in (b"1", b"true")


def _set_paused(paused: bool) -> None:
    if r is None:
        raise HTTPException(status_code=500, detail="REDIS_URL not configured")
    if paused:
        r.set(REDIS_KEY_PAUSED, "1")
    else:
        r.delete(REDIS_KEY_PAUSED)


def _is_within_operating_hours() -> bool:
    now_jst = datetime.now(JST)
    return CRON_START_HOUR <= now_jst.hour < CRON_END_HOUR


def _is_within_weather_hours() -> bool:
    now_jst = datetime.now(JST)
    return CRON_START_HOUR <= now_jst.hour < WEATHER_END_HOUR


def _snow_sig(w: ResortWeather) -> tuple:
    """Return the fields we care about for change detection (snow delta + snow type)."""
    return (
        w.peak.snow_diff_cm if w.peak else None,
        w.peak.snow_state   if w.peak else None,
        w.base.snow_diff_cm if w.base else None,
        w.base.snow_state   if w.base else None,
    )

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
    return {"ok": True, "service": "liftwatch", "paused": _is_paused()}

# Needed for Uptime Robot
@app.head("/api/cron")
async def cron_check_head(request: Request):
    await cron_check(request)
    return Response(status_code=200)

# --- CRON ENDPOINT ---
@app.get("/api/cron")
async def cron_check(request: Request):
    _require_bearer_auth(request)

    if _is_paused():
        return {"ok": True, "skipped": True, "reason": "paused"}

    if not _is_within_operating_hours():
        now_jst = datetime.now(JST)
        return {"ok": True, "skipped": True, "reason": f"outside operating hours ({CRON_START_HOUR}:00-{CRON_END_HOUR}:00 JST), current: {now_jst.strftime('%H:%M')} JST"}

    snap = await fetch_snapshot_async()

    if r is None:
        raise HTTPException(status_code=500, detail="REDIS_URL not configured")

    results: dict[str, dict[str, bool]] = {}

    for area in SkiArea:
        area_id = str(int(area))
        results[area_id] = {"lifts": False, "weather": False}

        # --- LIFTS ---
        # Alert only when a majority (>50%) of lifts are temporarily suspended
        # (wind hold), and again when they recover.
        lifts: list[LiftFacility] = snap.lifts_by_area.get(area, [])

        if lifts:
            suspended_count = sum(
                1 for lift in lifts
                if lift.status.strip().upper() in {"OPERATION_TEMPORARILY_SUSPENDED", "SUSPENDED"}
            )
            majority_suspended = suspended_count / len(lifts) > 0.5

            key_la = f"lw:lift_alert_state:{int(area)}"
            raw_la = _b2s(r.get(key_la))
            alert_state: dict = json.loads(raw_la) if raw_la else {}

            today_jst = datetime.now(JST).strftime("%Y-%m-%d")
            if alert_state.get("date") != today_jst:
                alert_state = {"date": today_jst, "alerted_suspended": False}

            alerted = alert_state.get("alerted_suspended", False)
            lift_msg: str | None = None

            if majority_suspended and not alerted:
                lift_msg = fmt_lift_mass_suspension(area, lifts, suspended_count)
                alert_state["alerted_suspended"] = True
                results[area_id]["lifts"] = True
            elif not majority_suspended and alerted:
                lift_msg = fmt_lift_recovery(area, lifts)
                alert_state["alerted_suspended"] = False
                results[area_id]["lifts"] = True

            if lift_msg:
                discord.post_facilities_channel(lift_msg)

            r.set(key_la, json.dumps(alert_state))

        # --- WEATHER ---
        w: ResortWeather | None = snap.weather_by_area.get(area)

        if w and w.last_updated and _is_within_weather_hours():
            key_snap = f"lw:last_weather_snapshot:{int(area)}"
            raw_snap = _b2s(r.get(key_snap))
            stored: dict = json.loads(raw_snap) if raw_snap else {}

            if _is_newer(w.last_updated, stored.get("last_seen")):
                today_jst = datetime.now(JST).strftime("%Y-%m-%d")
                first_of_day = stored.get("posted_date") != today_jst
                snow_changed = _snow_sig(w) != (
                    stored.get("peak_snow_diff"),
                    stored.get("peak_snow_state"),
                    stored.get("base_snow_diff"),
                    stored.get("base_snow_state"),
                )

                if first_of_day or snow_changed:
                    msg = fmt_weather(area, w)
                    discord.post_weather_channel(msg)
                    stored.update({
                        "posted_date":    today_jst,
                        "peak_snow_diff": w.peak.snow_diff_cm if w.peak else None,
                        "peak_snow_state": w.peak.snow_state  if w.peak else None,
                        "base_snow_diff": w.base.snow_diff_cm if w.base else None,
                        "base_snow_state": w.base.snow_state  if w.base else None,
                    })
                    results[area_id]["weather"] = True

                stored["last_seen"] = w.last_updated
                r.set(key_snap, json.dumps(stored))

    return {"ok": True, "updated": results}

# --- Discord interactions endpoint ---
@app.post("/api/interactions")
async def interactions(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not discord.verify_request(raw_body, signature, timestamp):
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
            paused_label = "⏸️ paused" if _is_paused() else "▶️ running"
            return {"type": 4, "data": {"content": f"✅ liftwatch is alive ({paused_label}). Try `/summary` or `/powder`."}}

        if name == "pause":
            _set_paused(True)
            return {"type": 4, "data": {"content": "⏸️ Cron alerts are now **paused**. Use `/resume` to start them again."}}

        if name == "resume":
            _set_paused(False)
            return {"type": 4, "data": {"content": "▶️ Cron alerts are now **running**. Updates will be posted when conditions change."}}

        # Future: add options like /weather area:HANAZONO
        return {"type": 4, "data": {"content": f"Unknown command: {name}"}}

    return {"type": 4, "data": {"content": "Unhandled interaction type."}}