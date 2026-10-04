from model.schemas import Unit
from model.state_manager import _state, unit_types
from model.math_utils import haversine_km
from model.config import ARRIVE_THRESH


# 追擊接近判定：距目標射程的 80% 以內視為「已到位，可開火」
CHASE_ENGAGE_PCT = 0.8

def move_unit_one_tick(unit: Unit, dt: float) -> None:
    """
    沿 waypoints 依速度推進。
    陸地單位：OSRM 真實道路路線（呼叫方負責設定 waypoints）。
    空軍/海軍：直線兩點。
    機場：不移動。
    """
    if unit.is_airport:
        return

    # 相容舊存檔：有目的地但無 waypoints 時補直線
    if not unit.waypoints:
        if unit.target_lat is not None and unit.target_lng is not None:
            unit.waypoints = [[unit.lat, unit.lng],
                              [unit.target_lat, unit.target_lng]]
        else:
            return

    budget_km = unit.speed_km_h * dt / 3600.0

    while budget_km > 0 and len(unit.waypoints) >= 2:
        cur  = unit.waypoints[0]
        nxt  = unit.waypoints[1]
        dist = haversine_km(cur[0], cur[1], nxt[0], nxt[1])

        if dist <= ARRIVE_THRESH:
            unit.waypoints.pop(0)
            unit.lat = round(nxt[0], 6)
            unit.lng = round(nxt[1], 6)
            continue

        if budget_km >= dist:
            budget_km -= dist
            unit.waypoints.pop(0)
            unit.lat = round(nxt[0], 6)
            unit.lng = round(nxt[1], 6)
        else:
            fraction = budget_km / dist
            unit.lat = round(cur[0] + (nxt[0] - cur[0]) * fraction, 6)
            unit.lng = round(cur[1] + (nxt[1] - cur[1]) * fraction, 6)
            unit.waypoints[0] = [unit.lat, unit.lng]
            budget_km = 0

    # 抵達終點
    if len(unit.waypoints) <= 1:
        if unit.waypoints:
            unit.lat = round(unit.waypoints[0][0], 6)
            unit.lng = round(unit.waypoints[0][1], 6)
        unit.waypoints  = []
        unit.target_lat = None
        unit.target_lng = None

def chase_tick() -> None:
    """
    追擊邏輯（每 Tick 呼叫）：
    對所有有 chase_target_id 的單位：
      1. 確認目標還存在
      2. 計算距離，若已在射程 80% 內 → 切換 stance=free 開始自動攻擊
      3. 若尚未到位 → 更新移動目的地為目標當前位置（目標移動時跟著追）
    收到 stance=hold 指令時，呼叫方應同時清除 chase_target_id。
    """
    for unit in list(_state.units):
        if not unit.chase_target_id:
            continue

        tgt = next((u for u in _state.units if u.id == unit.chase_target_id), None)

        # 目標已消失 → 清除追擊狀態
        if tgt is None:
            unit.chase_target_id = None
            unit.stance          = "hold"
            print(f"[CHASE] {unit.id} 追擊目標已消失，轉為待命")
            continue

        ut        = unit_types.get(unit.type, {})
        max_range = ut.get("max_range_km", unit.max_range_km)
        dist      = haversine_km(unit.lat, unit.lng, tgt.lat, tgt.lng)
        engage_range = max_range * CHASE_ENGAGE_PCT

        if dist <= engage_range:
            # 已到位：不需要繼續移動，讓 auto_combat_tick 接手開火
            if unit.stance != "free":
                unit.stance         = "free"
                unit.engaged_target = tgt.id
                print(f"[CHASE] {unit.id} 抵達射程，切換自由開火 → {tgt.id}")
            # 清除移動指令，停在原地開打
            unit.waypoints  = []
            unit.target_lat = None
            unit.target_lng = None
        else:
            # 尚未到位：持續追蹤目標位置（每 Tick 更新，跟著移動的目標跑）
            unit.target_lat = tgt.lat
            unit.target_lng = tgt.lng
            if not unit.waypoints:
                unit.waypoints = [[unit.lat, unit.lng], [tgt.lat, tgt.lng]]