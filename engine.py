from typing import List, Optional

from model.config import (
    MAX_FUEL, FUEL_BURN_PER_TICK, FUEL_WARN_PCT, FUEL_AUTO_RETURN_PCT,
    REFUEL_RANGE_KM, REFUEL_PER_TICK
)

from model.schemas import CombatEvent, FuelEvent, Unit

from model.math_utils import haversine_km

from model.state_manager import _state, _fuel_log, _combat_log, unit_types

def find_nearest_airport(unit: Unit) -> Optional[Unit]:
    """找最近的己方機場。"""
    airports = [u for u in _state.units
                if u.is_airport and u.faction == unit.faction]
    if not airports:
        return None
    return min(airports,
               key=lambda a: haversine_km(unit.lat, unit.lng, a.lat, a.lng))

def fuel_tick() -> None:
    """
    處理所有飛機燃油邏輯：
    1. 從兵種設定讀取 fuel_burn_per_tick（0 = 無燃油限制，跳過）
    2. 若在機場附近 → 從機場設定讀取 refuel_range_km / refuel_per_tick 補油
    3. 否則消耗燃油，低於警戒線 → 發 warn 事件
    4. 低於返航線且尚未返航 → 自動設定返航目的地
    5. 燃油 = 0 → 記錄墜毀，稍後移除
    """
    crashed: List[str] = []

    for unit in list(_state.units):
        if unit.domain != "air" or unit.is_airport:
            continue

        ut_plane  = unit_types.get(unit.type, {})
        burn_rate = ut_plane.get("fuel_burn_per_tick", FUEL_BURN_PER_TICK)

        if burn_rate <= 0:
            continue

        # ── 補油（在機場附近）────────────────────
        if unit.returning or unit.fuel < MAX_FUEL:
            airport = find_nearest_airport(unit)
            if airport:
                ut_ap        = unit_types.get(airport.type, {})
                refuel_range = ut_ap.get("refuel_range_km", REFUEL_RANGE_KM)
                refuel_rate  = ut_ap.get("refuel_per_tick",  REFUEL_PER_TICK)

                dist = haversine_km(unit.lat, unit.lng, airport.lat, airport.lng)
                if dist <= refuel_range:
                    unit.fuel      = min(MAX_FUEL, unit.fuel + refuel_rate)
                    unit.returning = False

                    if unit.fuel >= MAX_FUEL and not unit.refuel_notified:
                        unit.refuel_notified = True
                        _fuel_log.append(FuelEvent(
                            tick=_state.tick, unit_id=unit.id,
                            faction=unit.faction, unit_type=unit.type,
                            fuel=unit.fuel, event="refueled",
                            lat=unit.lat, lng=unit.lng,
                        ))
                        print(f"[FUEL] {unit.id} 補油完畢 fuel={unit.fuel}")
                    continue   

        # ── 消耗燃油 ─────────────────────────────
        unit.fuel            = max(0, round(unit.fuel - burn_rate))
        unit.refuel_notified = False   
        fuel_pct             = unit.fuel / MAX_FUEL * 100

        # ── 低油警告 ─────────────────────────────
        if fuel_pct <= FUEL_WARN_PCT and _state.tick % 10 == 0:
            _fuel_log.append(FuelEvent(
                tick=_state.tick, unit_id=unit.id,
                faction=unit.faction, unit_type=unit.type,
                fuel=unit.fuel, event="warn",
                lat=unit.lat, lng=unit.lng,
            ))

        # ── 自動返航 ─────────────────────────────
        if fuel_pct <= FUEL_AUTO_RETURN_PCT and not unit.returning:
            airport = find_nearest_airport(unit)
            if airport:
                unit.returning  = True
                unit.target_lat = airport.lat
                unit.target_lng = airport.lng
                unit.waypoints  = [[unit.lat, unit.lng],
                                   [airport.lat, airport.lng]]
                _fuel_log.append(FuelEvent(
                    tick=_state.tick, unit_id=unit.id,
                    faction=unit.faction, unit_type=unit.type,
                    fuel=unit.fuel, event="auto_return",
                    lat=unit.lat, lng=unit.lng,
                ))
                print(f"[FUEL] {unit.id} 低油量自動返航 fuel={unit.fuel}")
            else:
                print(f"[FUEL] {unit.id} 低油量但找不到己方機場！")

        # ── 燃油耗盡 → 墜毀 ─────────────────────
        if unit.fuel <= 0:
            _fuel_log.append(FuelEvent(
                tick=_state.tick, unit_id=unit.id,
                faction=unit.faction, unit_type=unit.type,
                fuel=0, event="crashed",
                lat=unit.lat, lng=unit.lng,
            ))
            _combat_log.append(CombatEvent(
                tick        = _state.tick,
                src_id      = unit.id,   src_faction = unit.faction, src_type = unit.type,
                tgt_id      = unit.id,   tgt_faction = unit.faction, tgt_type = unit.type,
                damage      = unit.hp,   tgt_hp      = 0,            tgt_max_hp = unit_types.get(unit.type, {}).get("hp", 100),
                destroyed   = True,
                src_lat     = unit.lat,  src_lng     = unit.lng,
                tgt_lat     = unit.lat,  tgt_lng     = unit.lng,
                is_counter  = False,
            ))
            crashed.append(unit.id)
            print(f"[FUEL] 💀 {unit.id} 燃油耗盡墜毀！")

    if crashed:
        _state.units = [u for u in _state.units if u.id not in crashed]