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
from liftwatch.formatter import powder_summary, summary_message, fmt_lift_changes, fmt_weather

app = FastAPI()

REDIS_URL = os.environ.get("REDIS_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# --- Redis connection ---
r = redis.Redis.from_url(REDIS_URL) if REDIS_URL else None

REDIS_KEY_PAUSED = "lw:cron_paused"
JST = timezone(timedelta(hours=9))
CRON_START_HOUR = 5    # 5:00 AM JST
CRON_END_HOUR = 20     # 8:00 PM JST
WEATHER_END_HOUR = 9   # 9:00 AM JST — weather alerts only posted 5–9 AM


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


# --- Lift change detection ---

_OPEN_STATUSES = {"OPERATING", "STANDBY", "OPERATING_SLOWED"}
_TEMP_CLOSED_STATUSES = {"OPERATION_TEMPORARILY_SUSPENDED", "SUSPENDED"}


def _status_group(status: str) -> str:
    s = status.strip().upper()
    if s in _OPEN_STATUSES:
        return "open"
    if s in _TEMP_CLOSED_STATUSES:
        return "temp_closed"
    return "day_closed"


LiftEntry = dict[str, object]  # {"status": str, "was_suspended": bool}


def _normalize_prev_state(raw: dict) -> dict[str, LiftEntry]:
    """Normalize Redis state to the current schema, handling the old str-only format."""
    result: dict[str, LiftEntry] = {}
    for fid, entry in raw.items():
        if isinstance(entry, str):
            result[fid] = {"status": entry, "was_suspended": False}
        else:
            result[fid] = entry
    return result


def _process_lift_changes(
    lifts: list[LiftFacility],
    prev: dict[str, LiftEntry],
) -> tuple[list[tuple[LiftFacility, str]], dict[str, LiftEntry]]:
    """Compute alert-worthy changes and the new state to persist.

    Alert-worthy transitions:
      - open → temp_closed  (unexpected mid-day suspension)
      - temp_closed → open  (lift recovered)
      - day_closed → open   when was_suspended=True (didn't recover before day-end)

    The was_suspended flag is set whenever a lift enters temp_closed and carried
    through a day_closed so we catch the next-morning re-open.
    """
    by_id = {str(lift.facility_id): lift for lift in lifts}
    changes: list[tuple[LiftFacility, str]] = []
    new_state: dict[str, LiftEntry] = {}

    for fid, lift in by_id.items():
        prev_entry = prev.get(fid, {})
        old_status: str | None = prev_entry.get("status")  # type: ignore[assignment]
        was_suspended: bool = bool(prev_entry.get("was_suspended", False))

        old_group = _status_group(old_status) if old_status else None
        new_group = _status_group(lift.status)

        # Maintain the was_suspended flag across state transitions
        if new_group == "open":
            new_was_suspended = False
        elif new_group == "temp_closed":
            new_was_suspended = True
        else:  # day_closed — carry the flag forward
            new_was_suspended = was_suspended or (old_group == "temp_closed")

        new_state[fid] = {"status": lift.status, "was_suspended": new_was_suspended}

        if old_status is None or old_status == lift.status:
            continue

        if (old_group == "open" and new_group == "temp_closed") or \
                (old_group == "temp_closed" and new_group == "open"):
            changes.append((lift, old_status))
        elif old_group == "day_closed" and new_group == "open" and was_suspended:
            changes.append((lift, old_status))

    return changes, new_state

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
        lifts: list[LiftFacility] = snap.lifts_by_area.get(area, [])

        key_l = f"lw:lift_state:{int(area)}"
        prev_raw = _b2s(r.get(key_l))
        prev_state = _normalize_prev_state(json.loads(prev_raw) if prev_raw else {})

        changes, new_state = _process_lift_changes(lifts, prev_state)
        if changes:
            lifts_updated = max((lift.update_date for lift in lifts if lift.update_date), default=None)
            msg = fmt_lift_changes(area, changes, lifts_updated)
            discord.post_facilities_channel(msg)
            results[area_id]["lifts"] = True

        # Always persist current state so future runs detect transitions correctly
        r.set(key_l, json.dumps(new_state))

        # --- WEATHER ---
        w: ResortWeather | None = snap.weather_by_area.get(area)
        weather_updated = w.last_updated if w else None

        key_w = f"lw:last_posted:weather:{int(area)}"
        last_posted_w = _b2s(r.get(key_w))

        if weather_updated and _is_newer(weather_updated, last_posted_w) and _is_within_weather_hours():
            msg = fmt_weather(area, w)
            discord.post_weather_channel(msg)
            r.set(key_w, weather_updated)
            results[area_id]["weather"] = True

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