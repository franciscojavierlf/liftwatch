from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal, List, Dict, Any

from liftwatch.ski_area import SkiArea

_YUKIYAMA_FACILITY_URL = "https://web-api.yukiyama.biz/web-api/latest-facility/backward"

FacilityType = Literal["lift"]

@dataclass(frozen=True)
class LiftFacility:
    ski_area: SkiArea
    facility_id: int
    object_id: Optional[str]
    name: str
    status: str                # e.g. OPERATING, STANDBY, SUSPENDED/CLOSED, etc.
    start_time: Optional[str]  # "8:30"
    end_time: Optional[str]    # "15:45"
    comment: Optional[str]     # often contains "8:30～15:45"
    groomed: Optional[str]
    update_date: Optional[str]

def _clean_str(x: object) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return None if s in ("", "---", "-", "None") else s

async def fetch_latest_facility_async(
    client: httpx.AsyncClient,
    *,
    ski_area: SkiArea,
    facility_type: FacilityType = "lift",
    lang: str = "eng",
) -> List[LiftFacility]:
    params = {"lang": lang, "skiareaId": str(ski_area), "facilityType": facility_type}
    r = await client.get(_YUKIYAMA_FACILITY_URL, params=params)
    r.raise_for_status()
    data: Dict[str, Any] = r.json()
    results: List[dict] = data.get("results", []) or []

    out: List[LiftFacility] = []
    for item in results:
        out.append(
            LiftFacility(
                ski_area=ski_area,
                facility_id=int(item.get("id")),
                object_id=_clean_str(item.get("object_id")),
                name=str(item.get("name") or "").strip(),
                status=str(item.get("status") or "").strip(),
                start_time=_clean_str(item.get("start_time")),
                end_time=_clean_str(item.get("end_time")),
                comment=_clean_str(item.get("comment")),
                groomed=_clean_str(item.get("groomed")),
                update_date=_clean_str(item.get("updateDate")),
            )
        )
    return out