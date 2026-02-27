from typing import List, Optional
from ski_area import SkiArea
from fetcher.facility import LiftFacility
from fetcher.weather import ResortWeather, WeatherPoint

POWDER_WORDS = ("パウダー", "新雪", "深雪")

def _is_powder(wp: WeatherPoint | None) -> bool:
    if not wp:
        return False
    if wp.snow_diff_cm is not None and wp.snow_diff_cm > 0:
        return True
    s = wp.snow_state or ""
    return any(word in s for word in POWDER_WORDS)

def _weather_point_str(wp: WeatherPoint | None) -> str:
    if not wp:
        return "—"
    parts = []
    if wp.temperature_c is not None:
        parts.append(f"{wp.temperature_c}°C")
    if wp.snow_cm is not None:
        parts.append(f"{wp.snow_cm}cm")
    if wp.snow_state:
        parts.append(wp.snow_state)
    if wp.cource_state:
        parts.append(wp.cource_state)
    if wp.wind:
        parts.append(f"wind {wp.wind}")
    if wp.weather:
        parts.append(wp.weather)
    return " | ".join(parts) if parts else "—"

def powder_summary(snap) -> str:
    """
    Uses weather snapshot to show where 'powder' is indicated.
    """
    matches = []
    for area in SkiArea:
        w: ResortWeather | None = snap.weather_by_area.get(area)
        if not w:
            continue
        # prefer peak
        wp = w.peak or w.base
        if _is_powder(wp):
            reason = []
            if wp and wp.snow_diff_cm and wp.snow_diff_cm > 0:
                reason.append(f"+{wp.snow_diff_cm}cm fresh")
            if wp and wp.snow_state:
                reason.append(wp.snow_state)
            matches.append((area, wp, ", ".join(reason) if reason else "powder signal"))

    if not matches:
        return "😢 No clear powder signal right now (no fresh snow delta and snow_state doesn’t mention パウダー/新雪/深雪)."

    lines = ["🏂 **Powder-ish right now:**"]
    for area, wp, why in matches:
        lines.append(f"- **{area.name}** — {why} — {_weather_point_str(wp)}")
    return "\n".join(lines)

def fmt_lifts(area: SkiArea, lifts: List[LiftFacility], *, updated: Optional[str]) -> str:
    ops = [l for l in lifts if l.status.upper() == "OPERATING"]
    suspended = [l for l in lifts if "SUSPEND" in l.status.upper()]
    standby = [l for l in lifts if "STANDBY" in l.status.upper()]

    # Show only “not operating” lines (signal > noise)
    not_ok = [l for l in lifts if l.status.upper() != "OPERATING"]

    lines = [
        f"**{area.emoji} {area.label} — Lift update**",
        f"Updated: `{updated or 'unknown'}`",
        f"Operating: **{len(ops)}** / {len(lifts)}",
    ]
    if not_ok:
        lines.append("")
        lines.append("**Not operating:**")
        for l in not_ok[:12]:
            window = ""
            if l.start_time and l.end_time:
                window = f" ({l.start_time}-{l.end_time})"
            lines.append(f"- {l.name}: `{l.status}`{window}")
        if len(not_ok) > 12:
            lines.append(f"...and {len(not_ok)-12} more")
    return "\n".join(lines)

def summary_message(snap) -> str:
    """
    One compact overview across all resorts.
    """
    lines = ["⛷️ **Niseko snapshot:**"]
    for area in SkiArea:
        w: ResortWeather | None = snap.weather_by_area.get(area)
        lifts: list[LiftFacility] = snap.lifts_by_area.get(area, [])

        peak = _weather_point_str(w.peak if w else None)
        base = _weather_point_str(w.base if w else None)

        operating = sum(1 for lf in lifts if lf.status == "OPERATING")
        total = len(lifts)

        updated = (w.last_updated if w else None) or (max((lf.update_date for lf in lifts if lf.update_date), default=None))
        lines.append(
            f"\n**{area.name}** (updated {updated or '—'})\n"
            f"- Lifts: {operating}/{total} operating\n"
            f"- Peak: {peak}\n"
            f"- Base: {base}"
        )
    return "\n".join(lines)
