from typing import List, Optional

from model.config import COMBAT_COOLDOWN_TICKS
from model.state_manager import unit_types, _state, _combat_log
from model.schemas import Unit, CombatEvent
from model.math_utils import haversine_km

def calc_damage(attacker: Unit, target: Unit) -> int:
    """計算攻擊傷害（含距離衰減 + 兵種相剋加成）。"""
    ut        = unit_types.get(attacker.type, {})
    base      = ut.get("attack", attacker.attack)
    max_range = ut.get("max_range_km", attacker.max_range_km)
    dist      = haversine_km(attacker.lat, attacker.lng, target.lat, target.lng)
    decay     = max(0.5, 1.0 - (dist / max_range) * 0.5) if max_range > 0 else 1.0
    bonus     = ut.get("bonuses", {}).get(target.type, 1.0)
    return max(1, int(base * decay * bonus))

def can_attack(attacker: Unit, target: Unit) -> bool:
    """
    檢查是否滿足自動攻擊條件：
      1. 不同陣營
      2. 攻擊方不是機場（機場不主動攻擊）
      3. 射程內
      4. 目標領域在 can_hit 清單（機場視為陸地領域）
      5. 彈藥充足
    """
    if attacker.faction == target.faction:
        return False
    if attacker.is_airport:   # 機場不主動攻擊
        return False

    ut         = unit_types.get(attacker.type, {})
    max_range  = ut.get("max_range_km", attacker.max_range_km)
    can_hit    = ut.get("can_hit", [attacker.domain])
    ammo_cost  = ut.get("ammo_cost", 1)

    tgt_domain = "land" if target.is_airport else unit_types.get(target.type, {}).get("domain", target.domain)

    if haversine_km(attacker.lat, attacker.lng, target.lat, target.lng) > max_range:
        return False
    if tgt_domain not in can_hit:
        return False
    if attacker.ammo < ammo_cost:
        return False
    return True

def apply_attack(
    src: Unit,
    tgt: Unit,
    is_counter: bool = False,
) -> Optional[CombatEvent]:
    """執行一次攻擊，更新雙方狀態並回傳 CombatEvent。"""
    ut        = unit_types.get(src.type, {})
    ammo_cost = ut.get("ammo_cost", 1)

    damage    = calc_damage(src, tgt)
    src.ammo -= ammo_cost
    src.combat_cooldown = COMBAT_COOLDOWN_TICKS
    src.engaged_target  = tgt.id
    tgt.hp   -= damage
    destroyed  = tgt.hp <= 0
    if destroyed:
        tgt.hp = 0

    tgt_max_hp = unit_types.get(tgt.type, {}).get("hp", 100)
    label = "反擊" if is_counter else "自動攻擊"
    print(
        f"[COMBAT] {label} {src.faction}{src.type}[{src.id[-6:]}]"
        f" → {tgt.faction}{tgt.type}[{tgt.id[-6:]}]"
        f"  傷害={damage}  HP={tgt.hp}/{tgt_max_hp}{'  💀' if destroyed else ''}"
    )

    return CombatEvent(
        tick        = _state.tick,
        src_id      = src.id,   src_faction = src.faction, src_type = src.type,
        tgt_id      = tgt.id,   tgt_faction = tgt.faction, tgt_type = tgt.type,
        damage      = damage,   tgt_hp      = tgt.hp,      tgt_max_hp = tgt_max_hp,
        destroyed   = destroyed,
        src_lat     = src.lat,  src_lng     = src.lng,
        tgt_lat     = tgt.lat,  tgt_lng     = tgt.lng,
        is_counter  = is_counter,
    )

def auto_combat_tick() -> None:
    """
    自動戰鬥流程：
      Step 1：所有單位冷卻遞減
      Step 2：stance=free 且冷卻=0 的單位主動攻擊最近敵人
      Step 3：被攻擊單位不論 stance 都嘗試回擊
      Step 4：統一移除陣亡單位
      Step 5：寫入事件佇列
    """
    events:    List[CombatEvent] = []
    to_remove: set               = set()
    alive = list(_state.units)

    # Step 1：冷卻遞減
    for unit in alive:
        if unit.combat_cooldown > 0:
            unit.combat_cooldown -= 1

    # Step 2：主動攻擊
    for src in alive:
        if src.stance != "free" or src.combat_cooldown > 0 or src.id in to_remove:
            continue
        if src.is_airport:
            continue

        best_tgt  = None
        best_dist = float("inf")

        if src.engaged_target:
            prev = next((u for u in alive
                         if u.id == src.engaged_target
                         and u.id not in to_remove), None)
            if prev and can_attack(src, prev):
                best_tgt  = prev
                best_dist = haversine_km(src.lat, src.lng, prev.lat, prev.lng)

        if best_tgt is None:
            for tgt in alive:
                if tgt.id in to_remove or not can_attack(src, tgt):
                    continue
                d = haversine_km(src.lat, src.lng, tgt.lat, tgt.lng)
                if d < best_dist:
                    best_dist = d
                    best_tgt  = tgt

        if best_tgt is None:
            src.engaged_target = None
            continue

        ev = apply_attack(src, best_tgt, is_counter=False)
        if ev:
            events.append(ev)
            if best_tgt.hp <= 0:
                to_remove.add(best_tgt.id)

    # Step 3：回擊
    attacked_map: dict = {}
    for ev in events:
        if ev.tgt_id not in attacked_map:
            attacked_map[ev.tgt_id] = ev.src_id

    for tgt_id, attacker_id in attacked_map.items():
        tgt = next((u for u in alive if u.id == tgt_id), None)
        if tgt is None or tgt.id in to_remove or tgt.combat_cooldown > 0:
            continue

        best_src  = None
        best_dist = float("inf")

        attacker = next((u for u in alive
                         if u.id == attacker_id and u.id not in to_remove), None)
        if attacker and can_attack(tgt, attacker):
            best_src  = attacker
            best_dist = haversine_km(tgt.lat, tgt.lng, attacker.lat, attacker.lng)

        if best_src is None:
            for src in alive:
                if src.id in to_remove or not can_attack(tgt, src):
                    continue
                d = haversine_km(tgt.lat, tgt.lng, src.lat, src.lng)
                if d < best_dist:
                    best_dist = d
                    best_src  = src

        if best_src is None:
            continue

        ev = apply_attack(tgt, best_src, is_counter=True)
        if ev:
            events.append(ev)
            if best_src.hp <= 0:
                to_remove.add(best_src.id)

    # Step 4：移除陣亡單位
    if to_remove:
        _state.units = [u for u in _state.units if u.id not in to_remove]

    # Step 5：寫入事件佇列
    for ev in events:
        _combat_log.append(ev)