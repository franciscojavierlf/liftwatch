from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from liftwatch.ski_area import SkiArea
from liftwatch.fetcher.facility import LiftFacility
from liftwatch.fetcher.weather import ResortWeather, WeatherPoint

JST = timezone(timedelta(hours=9))


def _format_timestamp_jst(iso_utc: Optional[str]) -> str:
    if not iso_utc:
        return "unknown"

    s = str(iso_utc).strip()
    if not s:
        return "unknown"

    try:
        # Normalize trailing Z -> +00:00 for fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"

        dt = datetime.fromisoformat(s)

        # If missing tzinfo, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt_jst = dt.astimezone(JST)
        return dt_jst.strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        # If it fails, return original to make debugging obvious
        return str(iso_utc)

# ---------- Generic cleaning ----------

def _normalize_text(value: object) -> str:
    return str(value or "").strip()

def _normalize_upper(value: object) -> str:
    return _normalize_text(value).upper()


# ---------- Powder logic ----------

POWDER_KEYWORDS = ("パウダー", "新雪", "深雪")

def has_powder_signal(point: WeatherPoint | None) -> bool:
    if not point:
        return False

    if point.snow_diff_cm is not None and point.snow_diff_cm > 0:
        return True

    snow_state = _normalize_text(getattr(point, "snow_state", None))
    return any(word in snow_state for word in POWDER_KEYWORDS)


# ---------- Weather formatting ----------

def format_weather_point_compact(point: WeatherPoint | None) -> str:
    """
    One-line compact weather representation.
    Example:
      "-2°C • ❄️ 280cm (Δ+5cm) • 圧雪(固) • ☁️ 曇"
    """
    if not point:
        return "—"

    temperature = "—" if point.temperature_c is None else f"{point.temperature_c}°C"
    snow = "—" if point.snow_cm is None else f"{point.snow_cm}cm"

    delta = ""
    if point.snow_diff_cm is not None:
        sign = "+" if point.snow_diff_cm > 0 else ""
        delta = f" (Δ{sign}{point.snow_diff_cm}cm)"

    snow_state = _normalize_text(getattr(point, "snow_state", None))
    weather = _normalize_text(getattr(point, "weather", None))

    parts: list[str] = [f"{temperature} • ❄️ {snow}{delta}"]
    if snow_state:
        parts.append(snow_state)
    if weather:
        parts.append(f"☁️ {weather}")

    return " • ".join(parts)


def fmt_weather(area: SkiArea, resort_weather: ResortWeather) -> str:
    return "\n".join([
        f"**{area.label} — Weather • ✅ UPDATED**",
        f"🏔️ Peak: {format_weather_point_compact(resort_weather.peak)}",
        f"🏡 Base: {format_weather_point_compact(resort_weather.base)}",
        f"🕒 {_format_timestamp_jst(resort_weather.last_updated)}",
    ])


# ---------- Lift formatting ----------

_SUSPENDED_STATUSES = {"OPERATION_TEMPORARILY_SUSPENDED", "SUSPENDED"}


def is_operating(lift: LiftFacility) -> bool:
    return _normalize_upper(getattr(lift, "status", None)) == "OPERATING"


def fmt_lift_mass_suspension(area: SkiArea, lifts: List[LiftFacility], suspended_count: int) -> str:
    pct = int(suspended_count / len(lifts) * 100)
    suspended = [l for l in lifts if l.status.strip().upper() in _SUSPENDED_STATUSES]
    lines = [
        f"**{area.label} — ⛔ Wind Hold**",
        f"{suspended_count}/{len(lifts)} lifts suspended ({pct}%) — likely wind hold.",
        "",
    ]
    for lift in suspended:
        lines.append(f"- ⛔ {_normalize_text(lift.name)}")
    updated = max((l.update_date for l in lifts if l.update_date), default=None)
    lines.append(f"\n🕒 {_format_timestamp_jst(updated)}")
    return "\n".join(lines)


def fmt_lift_recovery(area: SkiArea, lifts: List[LiftFacility]) -> str:
    operating_count = sum(1 for l in lifts if is_operating(l))
    released_count = sum(
        1 for l in lifts
        if _normalize_upper(getattr(l, "status", None)) not in _SUSPENDED_STATUSES
    )
    lines = [
        f"**{area.label} — ✅ Wind Hold Lifted**",
        f"{released_count}/{len(lifts)} lifts released from wind hold, {operating_count} now operating.",
    ]
    updated = max((l.update_date for l in lifts if l.update_date), default=None)
    lines.append(f"🕒 {_format_timestamp_jst(updated)}")
    return "\n".join(lines)


# ---------- Commands output ----------

def powder_summary(snapshot) -> str:
    matches: list[tuple[SkiArea, WeatherPoint, str]] = []

    for area in SkiArea:
        resort_weather: ResortWeather | None = snapshot.weather_by_area.get(area)
        if not resort_weather:
            continue

        preferred_point = resort_weather.peak or resort_weather.base
        if not preferred_point:
            continue

        if has_powder_signal(preferred_point):
            reasons: list[str] = []
            if preferred_point.snow_diff_cm is not None and preferred_point.snow_diff_cm > 0:
                reasons.append(f"+{preferred_point.snow_diff_cm}cm fresh")
            snow_state = _normalize_text(getattr(preferred_point, "snow_state", None))
            if snow_state:
                reasons.append(snow_state)

            matches.append((area, preferred_point, " · ".join(reasons) if reasons else "powder signal"))

    if not matches:
        return (
            "🏔️ **Niseko Powder Report**\n"
            "\n"
            "No fresh snow detected across Niseko United right now.\n"
            "Check back later — conditions can change fast!"
        )

    lines = [
        "🏔️ **Niseko Powder Report**",
        "",
    ]
    for area, point, why in matches:
        compact = format_weather_point_compact(point)
        lines.append(f"**{area.label}** — {why}")
        lines.append(f"  {compact}")
        lines.append("")

    timestamp = None
    for _, point, _ in matches:
        ts = getattr(point, "update_date", None)
        if ts:
            timestamp = ts
            break
    lines.append(f"_Updated {_format_timestamp_jst(timestamp)}_")

    return "\n".join(lines)


def summary_message(snapshot) -> str:
    lines: list[str] = ["⛷️ **Niseko snapshot:**"]

    for area in SkiArea:
        resort_weather: ResortWeather | None = snapshot.weather_by_area.get(area)
        lifts: list[LiftFacility] = snapshot.lifts_by_area.get(area, [])

        peak_text = format_weather_point_compact(resort_weather.peak if resort_weather else None)
        base_text = format_weather_point_compact(resort_weather.base if resort_weather else None)

        operating_count = sum(1 for lift in lifts if is_operating(lift))
        total_count = len(lifts)

        weather_updated = resort_weather.last_updated if resort_weather else None
        lifts_updated = max((lf.update_date for lf in lifts if lf.update_date), default=None)
        newest_update = weather_updated or lifts_updated

        lines.append(
            "\n"
            f"**{area.label}** • 🕒 {_format_timestamp_jst(newest_update)}\n"
            f"- Lifts: ✅ {operating_count}/{total_count}\n"
            f"- Peak: {peak_text}\n"
            f"- Base: {base_text}"
        )

    return "\n".join(lines)
