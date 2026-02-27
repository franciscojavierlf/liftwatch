from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal, Dict, List, Any

import httpx  # you’re using this but it wasn’t imported in your snippet
from ski_area import SkiArea

_YUKIYAMA_WEATHER_URL = "https://web-api.yukiyama.biz/web-api/latest-weather/backward"

PointName = Literal["Peak", "Base"]

_BASE_NAMES = {"base", "bottom", "mountain base", "ベース", "山麓", "麓"}
_PEAK_NAMES = {"peak", "top", "mountain peak", "山頂", "山頂付近", "頂上"}

@dataclass(frozen=True)
class WeatherPoint:
    name: PointName
    temperature_c: Optional[int]
    snow_cm: Optional[int]
    snow_diff_cm: Optional[int]
    wind: Optional[str]
    weather: Optional[str]

    snow_state: Optional[str]      # NEW: 圧雪(固), パウダー, 新雪, etc
    cource_state: Optional[str]    # NEW: 全面可能, 一部可能, etc
    comment: Optional[str]         # NEW: if they start using it

    update_date: Optional[str]     # ISO string from API

@dataclass(frozen=True)
class ResortWeather:
    ski_area: SkiArea
    base: Optional[WeatherPoint]
    peak: Optional[WeatherPoint]
    last_updated: Optional[str]  # max(updateDate)

def _clean_str(s: object) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return None if s in ("", "---", "-", "None") else s

def _clean_int(x: object) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None

def _normalize_point_name(raw: str) -> str | None:
    s = (raw or "").strip().lower()
    if s in _BASE_NAMES:
        return "Base"
    if s in _PEAK_NAMES:
        return "Peak"
    return None

async def fetch_latest_weather_async(
    client: httpx.AsyncClient,
    *,
    ski_area: SkiArea,
    lang: str = "eng",
) -> ResortWeather:
    params = {"lang": lang, "skiareaId": str(int(ski_area))}
    r = await client.get(_YUKIYAMA_WEATHER_URL, params=params)
    r.raise_for_status()
    data: Dict[str, Any] = r.json()
    results: List[dict] = data.get("results", []) or []

    base = peak = None
    last_updated: Optional[str] = None

    for item in results:
        raw_name = (item.get("name") or "").strip()
        name = _normalize_point_name(raw_name)
        if name not in ("Base", "Peak"):
            continue

        wp = WeatherPoint(
            name=name,  # type: ignore[arg-type]
            temperature_c=_clean_int(item.get("temperature")),
            snow_cm=_clean_int(item.get("snow_accumulation")),
            snow_diff_cm=_clean_int(item.get("snow_accumulation_difference")),
            wind=_clean_str(item.get("wind_speed")),
            weather=_clean_str(item.get("weather")),

            snow_state=_clean_str(item.get("snow_state")),        # NEW
            cource_state=_clean_str(item.get("cource_state")),    # NEW
            comment=_clean_str(item.get("comment")),              # NEW

            update_date=_clean_str(item.get("updateDate")),
        )

        if wp.update_date and (last_updated is None or wp.update_date > last_updated):
            last_updated = wp.update_date

        if name == "Base":
            base = wp
        else:
            peak = wp

    return ResortWeather(ski_area=ski_area, base=base, peak=peak, last_updated=last_updated)