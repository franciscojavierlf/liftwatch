from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Iterable, List, Optional, Sequence

from liftwatch.ski_area import SkiArea
from liftwatch.fetcher.facility import LiftFacility
from liftwatch.fetcher.weather import ResortWeather, WeatherPoint

JST = timezone(timedelta(hours=9))

STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "OPERATING": ("✅", "Operating"),
    "OPERATING_SLOWED": ("🐢", "Operating (slow)"),
    "STANDBY": ("⏳", "Standby"),
    "OPERATION_TEMPORARILY_SUSPENDED": ("⛔", "Temporarily suspended"),
    "SUSPENDED": ("❌", "Suspended"),
    "SUSPENDED_CLOSED": ("❌", "Closed"),
    "CLOSED": ("❌", "Closed"),
}

def _format_lift_status(raw_status: object) -> str:
    status = str(raw_status or "").strip().upper()

    icon, text = STATUS_DISPLAY.get(
        status,
        ("⚠️", status.replace("_", " ").title())  # fallback
    )

    return f"{icon} {text}"

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
      "-2°C • ❄️ 280cm (Δ+5cm) • 圧雪(固) • 全面可能 • 💨 SE2-5 • ☁️ 曇"
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
    course_state = _normalize_text(getattr(point, "cource_state", None))
    wind = _normalize_text(getattr(point, "wind", None))
    weather = _normalize_text(getattr(point, "weather", None))

    parts: list[str] = [f"{temperature} • ❄️ {snow}{delta}"]
    if snow_state:
        parts.append(snow_state)
    if course_state:
        parts.append(course_state)
    if wind:
        parts.append(f"💨 {wind}")
    if weather:
        parts.append(f"☁️ {weather}")

    return " • ".join(parts)


def fmt_weather(area: SkiArea, resort_weather: ResortWeather) -> str:
    return "\n".join([
        f"**{area.label} — Weather • ✅ UPDATED**",
        f"🕒 {_format_timestamp_jst(resort_weather.last_updated)}",
        f"🏔️ Peak: {format_weather_point_compact(resort_weather.peak)}",
        f"🏡 Base: {format_weather_point_compact(resort_weather.base)}",
    ])


# ---------- Lift formatting ----------

def lift_status_icon(status: object) -> str:
    s = _normalize_upper(status)
    if s == "OPERATING":
        return "✅"
    if "SUSPEND" in s:
        return "⛔"
    if "STANDBY" in s:
        return "⏳"
    if "SLOW" in s:
        return "🐢"
    return "⚠️"

def is_operating(lift: LiftFacility) -> bool:
    return _normalize_upper(getattr(lift, "status", None)) == "OPERATING"

def lift_time_window(lift: LiftFacility) -> str:
    start = _normalize_text(getattr(lift, "start_time", None))
    end = _normalize_text(getattr(lift, "end_time", None))
    if start and end:
        return f" ({start}-{end})"
    return ""

def fmt_lifts(area: SkiArea, lifts: List[LiftFacility], updated: str | None) -> str:
    total_lifts = len(lifts)
    operating_count = sum(1 for lift in lifts if is_operating(lift))

    non_operating = [
        lift for lift in lifts
        if _normalize_upper(getattr(lift, "status", None)) not in ("", "OPERATING")
    ]

    lines: list[str] = [
        f"**{area.label} — Lifts • ✅ UPDATED**",
        f"🕒 {_format_timestamp_jst(updated)} • ✅ {operating_count}/{total_lifts} operating",
    ]

    if non_operating:
        lines.append("")
        lines.append("**Issues:**")
        for lift in non_operating[:10]:
            name = _normalize_text(getattr(lift, "name", None)) or "(unnamed)"
            status = _normalize_text(getattr(lift, "status", None)) or "UNKNOWN"
            pretty_status = _format_lift_status(status)
            icon = lift_status_icon(status)
            lines.append(f"- {icon} {name}{lift_time_window(lift)} — `{pretty_status}`")

        if len(non_operating) > 10:
            lines.append(f"...and {len(non_operating) - 10} more")

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
                reasons.append(f"Δ+{preferred_point.snow_diff_cm}cm")
            snow_state = _normalize_text(getattr(preferred_point, "snow_state", None))
            if snow_state:
                reasons.append(snow_state)

            matches.append((area, preferred_point, " / ".join(reasons) if reasons else "powder signal"))

    if not matches:
        return "😢 No clear powder signal right now (no positive snow delta and snow_state doesn’t mention パウダー/新雪/深雪)."

    lines = ["🏂 **Powder-ish right now:**"]
    for area, point, why in matches:
        lines.append(f"- **{area.label}** — {why} — {format_weather_point_compact(point)}")
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
