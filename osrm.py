import httpx
from typing import List

from model.config import OSRM_URL
from model.schemas import Waypoint

async def fetch_osrm_waypoints(
    from_lat: float, from_lng: float,
    to_lat:   float, to_lng:   float,
) -> List[Waypoint]:
    """
    向公開 OSRM 查詢駕車路線，回傳 [[lat, lng], ...] 的 waypoints。
    失敗時 fallback 為直線兩點。
    """
    url = OSRM_URL.format(
        lng1=from_lng, lat1=from_lat,
        lng2=to_lng,   lat2=to_lat,
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            coords = data["routes"][0]["geometry"]["coordinates"]
            return [[c[1], c[0]] for c in coords]
    except Exception as e:
        print(f"[OSRM] 查詢失敗（{e}），改用直線")
    return [[from_lat, from_lng], [to_lat, to_lng]]