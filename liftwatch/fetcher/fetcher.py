from __future__ import annotations

import asyncio
import httpx
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from liftwatch.ski_area import SkiArea
from liftwatch.fetcher.facility import LiftFacility, fetch_latest_facility_async
from liftwatch.fetcher.weather import ResortWeather, fetch_latest_weather_async

@dataclass(frozen=True)
class Snapshot:
    lifts_by_area: Dict[SkiArea, List[LiftFacility]]
    weather_by_area: Dict[SkiArea, ResortWeather]

async def _fetch_one_area(
    client: httpx.AsyncClient,
    ski_area: SkiArea,
) -> Tuple[SkiArea, List[LiftFacility], Optional[str], ResortWeather, Optional[str]]:

    # run lifts + weather for this area concurrently
    lifts_task = fetch_latest_facility_async(client, ski_area=ski_area, facility_type="lift", lang="eng")
    weather_task = fetch_latest_weather_async(client, ski_area=ski_area, lang="eng")
    lifts, weather = await asyncio.gather(lifts_task, weather_task)

    return ski_area, lifts, weather

async def fetch_snapshot_async() -> Snapshot:
    timeout = httpx.Timeout(20.0, connect=10.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)

    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers={"User-Agent": "liftwatch/1.0"}) as client:
        tasks = [_fetch_one_area(client, area) for area in SkiArea]
        results = await asyncio.gather(*tasks)

    lifts_by_area: Dict[SkiArea, List[LiftFacility]] = {}
    weather_by_area: Dict[SkiArea, ResortWeather] = {}

    for area, lifts, weather in results:
        lifts_by_area[area] = lifts
        weather_by_area[area] = weather

    return Snapshot(
        lifts_by_area=lifts_by_area,
        weather_by_area=weather_by_area,
    )

async def fetch_weather_snapshot_async() -> Snapshot:
    timeout = httpx.Timeout(20.0, connect=10.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers={"User-Agent":"liftwatch/1.0"}) as client:
        tasks = [fetch_latest_weather_async(client, ski_area=a, lang="eng") for a in SkiArea]
        res = await asyncio.gather(*tasks)

    by = {a: w for a, w in zip(SkiArea, res)}
    return Snapshot(weather_by_area=by, lifts_by_area={})
