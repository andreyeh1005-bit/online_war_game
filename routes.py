import uuid

from fastapi import APIRouter, HTTPException

from engine import find_nearest_airport
from osrm import fetch_osrm_waypoints
from combat import calc_damage

from model.config import MAX_AMMO, MAX_FUEL, SUPPLY_TYPES, SUPPLY_RANGE_KM, SUPPLY_AMOUNT
from model.math_utils import haversine_km
from model.schemas import(
    Unit, BattleState, ActionResponse, CombatEvent,
    UnitTypeModel, DeployRequest, MoveRequest,
    StanceRequest, ReturnRequest, LockTargetRequest, ActionRequest, EngageRequest
)

from model.state_manager import( 
    _state, _combat_log, _fuel_log, unit_types, save_state, save_unit_types,
    is_airport_type, is_road_unit
)

router = APIRouter()

# ═══════════════════════════════════════════════════════════════
#  兵種設定
# ═══════════════════════════════════════════════════════════════

@router.get("/api/units")
async def get_unit_types():
    return unit_types


@router.post("/api/units")
async def upsert_unit_type(data: UnitTypeModel):
    unit_types[data.name] = (
        data.model_dump() if hasattr(data, "model_dump") else data.dict()
    )
    save_unit_types(unit_types)
    return {"ok": True, "name": data.name}


@router.delete("/api/units/{name}")
async def delete_unit_type(name: str):
    if name not in unit_types:
        raise HTTPException(404, detail=f"找不到兵種：{name}")
    del unit_types[name]
    save_unit_types(unit_types)
    return {"ok": True, "deleted": name}

# ═══════════════════════════════════════════════════════════════
#  戰場狀態
# ═══════════════════════════════════════════════════════════════

@router.get("/api/state", response_model=BattleState)
async def get_state():
    return _state


@router.get("/api/combat-log")
async def get_combat_log(since_tick: int = 0):
    events = [e for e in _combat_log if e.tick > since_tick]
    return {"events": events, "current_tick": _state.tick}


@router.get("/api/fuel-log")
async def get_fuel_log(since_tick: int = 0):
    events = [e for e in _fuel_log if e.tick > since_tick]
    return {"events": events, "current_tick": _state.tick}

# ═══════════════════════════════════════════════════════════════
#  部署部隊
# ═══════════════════════════════════════════════════════════════

@router.post("/api/deploy")
async def deploy(req: DeployRequest):
    utype = unit_types.get(req.type)
    if not utype:
        raise HTTPException(400, detail=f"未知兵種：{req.type}")

    new_id    = f"{req.faction[0]}-{req.type[0]}-{uuid.uuid4().hex[:6].upper()}"
    is_ap     = is_airport_type(req.type)

    new_unit = Unit(
        id           = new_id,
        type         = req.type,
        faction      = req.faction,
        lat          = req.lat,
        lng          = req.lng,
        hp           = utype["hp"],
        ammo         = MAX_AMMO,
        attack       = utype["attack"],
        domain       = utype["domain"],
        max_range_km = utype["max_range_km"],
        speed_km_h   = utype.get("speed_km_h", 5.0),
        is_airport   = is_ap,
        fuel         = MAX_FUEL,
    )
    _state.units.append(new_unit)
    save_state()

    label = "機場" if is_ap else req.type
    return {"ok": True, "id": new_id, "is_airport": is_ap,
            "msg": f"{req.faction} {label} 已部署"}

# ═══════════════════════════════════════════════════════════════
#  移動
# ═══════════════════════════════════════════════════════════════

@router.post("/api/move")
async def move_unit(req: MoveRequest):
    unit = next((u for u in _state.units if u.id == req.unit_id), None)
    if not unit:
        raise HTTPException(404, detail=f"找不到單位：{req.unit_id}")
    if unit.is_airport:
        raise HTTPException(400, detail="機場無法移動")

    unit.target_lat = req.target_lat
    unit.target_lng = req.target_lng
    unit.returning  = False   # 手動移動取消返航旗標

    if is_road_unit(unit.domain):
        wps = await fetch_osrm_waypoints(
            unit.lat, unit.lng, req.target_lat, req.target_lng)
        print(f"[OSRM] {unit.id} 取得 {len(wps)} 個路線點")
    else:
        wps = [[unit.lat, unit.lng], [req.target_lat, req.target_lng]]

    unit.waypoints = wps
    return {"ok": True, "unit_id": unit.id, "waypoints": wps,
            "msg": f"[{unit.id}] 開始移動，共 {len(wps)} 點"}

# ═══════════════════════════════════════════════════════════════
#  手動返航
# ═══════════════════════════════════════════════════════════════

@router.post("/api/return")
async def manual_return(req: ReturnRequest):
    """玩家主動下令返航，自動找最近己方機場。"""
    unit = next((u for u in _state.units if u.id == req.unit_id), None)
    if not unit:
        raise HTTPException(404, detail=f"找不到單位：{req.unit_id}")
    if unit.domain != "air" or unit.is_airport:
        raise HTTPException(400, detail="只有飛機才能返航")

    airport = find_nearest_airport(unit)
    if not airport:
        raise HTTPException(400, detail="找不到己方機場，請先部署機場")

    unit.returning  = True
    unit.target_lat = airport.lat
    unit.target_lng = airport.lng
    unit.waypoints  = [[unit.lat, unit.lng], [airport.lat, airport.lng]]

    dist = haversine_km(unit.lat, unit.lng, airport.lat, airport.lng)
    return {
        "ok":         True,
        "unit_id":    unit.id,
        "airport_id": airport.id,
        "dist_km":    round(dist, 2),
        "msg":        f"[{unit.id}] 返航至 [{airport.id}]，距離 {dist:.2f} km",
    }

# ═══════════════════════════════════════════════════════════════
#  追擊指令（移動靠近 + 持續開火）
# ═══════════════════════════════════════════════════════════════

@router.post("/api/engage")
async def engage_target(req: EngageRequest):
    """
    玩家指定己方單位追擊敵方目標：
    1. 向 OSRM 查詢路線（陸地單位）或設直線（空/海）
    2. 設定 chase_target_id，game_loop 的 chase_tick 每秒更新追擊進度
    3. 進入射程後自動切換 stance=free 持續開火
    4. 直到玩家下達 stance=hold 指令才停止
    """
    src = next((u for u in _state.units if u.id == req.unit_id), None)
    tgt = next((u for u in _state.units if u.id == req.target_id), None)

    if not src:
        raise HTTPException(404, detail=f"找不到單位：{req.unit_id}")
    if not tgt:
        raise HTTPException(404, detail=f"找不到目標：{req.target_id}")
    if src.faction == tgt.faction:
        raise HTTPException(400, detail="不能追擊己方單位")
    if src.is_airport:
        raise HTTPException(400, detail="機場無法移動")

    # 設定追擊目標
    src.chase_target_id = tgt.id
    src.engaged_target  = tgt.id
    src.stance          = "hold"    # 先待命，到位後 chase_tick 自動切換 free

    # 查詢路線並開始移動
    src.target_lat = tgt.lat
    src.target_lng = tgt.lng

    if is_road_unit(src.domain):
        wps = await fetch_osrm_waypoints(src.lat, src.lng, tgt.lat, tgt.lng)
        print(f"[ENGAGE] {src.id} 追擊 {tgt.id}，OSRM {len(wps)} 點")
    else:
        wps = [[src.lat, src.lng], [tgt.lat, tgt.lng]]

    src.waypoints = wps

    dist = haversine_km(src.lat, src.lng, tgt.lat, tgt.lng)
    return {
        "ok":       True,
        "unit_id":  src.id,
        "target_id":tgt.id,
        "dist_km":  round(dist, 2),
        "waypoints":wps,
        "msg":      f"[{src.id}] 開始追擊 [{tgt.id}]，距離 {dist:.2f} km",
    }

# ═══════════════════════════════════════════════════════════════
#  交戰規則（ROE）
# ═══════════════════════════════════════════════════════════════

@router.post("/api/stance")
async def set_stance(req: StanceRequest):
    unit = next((u for u in _state.units if u.id == req.unit_id), None)
    if not unit:
        raise HTTPException(404, detail=f"找不到單位：{req.unit_id}")
    unit.stance = req.stance
    # 下達待命指令時，同時清除追擊狀態
    if req.stance == "hold":
        unit.chase_target_id = None
        unit.waypoints       = []
        unit.target_lat      = None
        unit.target_lng      = None
    label = "自由開火 🔴" if req.stance == "free" else "待命 🟢"
    print(f"[ROE] {unit.id} → {label}")
    return {"ok": True, "unit_id": unit.id, "stance": req.stance}

# ═══════════════════════════════════════════════════════════════
#  鎖定目標（方案 B 預留）
# ═══════════════════════════════════════════════════════════════

@router.post("/api/lock")
async def lock_target(req: LockTargetRequest):
    unit = next((u for u in _state.units if u.id == req.unit_id), None)
    if not unit:
        raise HTTPException(404, detail=f"找不到單位：{req.unit_id}")
    if req.target_id:
        tgt = next((u for u in _state.units if u.id == req.target_id), None)
        if not tgt:
            raise HTTPException(404, detail=f"找不到目標：{req.target_id}")
        if tgt.faction == unit.faction:
            raise HTTPException(400, detail="不能鎖定己方單位")
    unit.locked_target_id = req.target_id
    msg = f"鎖定 [{req.target_id}]" if req.target_id else "解除鎖定"
    return {"ok": True, "unit_id": unit.id, "msg": msg}

# ═══════════════════════════════════════════════════════════════
#  手動攻擊 / 補給
# ═══════════════════════════════════════════════════════════════

@router.post("/api/action", response_model=ActionResponse)
async def do_action(req: ActionRequest):
    src = next((u for u in _state.units if u.id == req.source_id), None)
    tgt = next((u for u in _state.units if u.id == req.target_id), None)

    if not src:
        return ActionResponse(status="error", message=f"找不到來源：{req.source_id}")
    if not tgt:
        return ActionResponse(status="error", message=f"找不到目標：{req.target_id}")

    dist_km = haversine_km(src.lat, src.lng, tgt.lat, tgt.lng)
    utype   = unit_types.get(src.type, {})

    # ── 攻擊 ──────────────────────────────────────
    if req.action_type == "attack":
        if src.faction == tgt.faction:
            return ActionResponse(status="error", message="不能攻擊己方單位")

        ammo_cost  = utype.get("ammo_cost", 1)
        max_range  = utype.get("max_range_km", src.max_range_km)
        can_hit    = utype.get("can_hit", ["land"])
        tgt_domain = unit_types.get(tgt.type, {}).get("domain", tgt.domain)

        # 機場可以被手動攻擊（繞過 can_hit 檢查）
        if not tgt.is_airport and tgt_domain not in can_hit:
            return ActionResponse(status="error",
                message=f"{src.type} 無法攻擊 {tgt_domain} 領域目標")
        if src.ammo < ammo_cost:
            return ActionResponse(status="error",
                message=f"彈藥不足（需 {ammo_cost}，剩 {src.ammo}）")
        if dist_km > max_range:
            return ActionResponse(status="error",
                message=f"距離太遠（{dist_km:.2f} km，射程 {max_range} km）")

        damage    = calc_damage(src, tgt)
        src.ammo -= ammo_cost
        tgt.hp   -= damage
        destroyed  = tgt.hp <= 0
        if destroyed:
            tgt.hp       = 0
            _state.units = [u for u in _state.units if u.id != tgt.id]

        # 手動攻擊也寫入戰鬥日誌，歷史戰報看得到
        _combat_log.append(CombatEvent(
            tick        = _state.tick,
            src_id      = src.id,   src_faction = src.faction, src_type = src.type,
            tgt_id      = tgt.id,   tgt_faction = tgt.faction, tgt_type = tgt.type,
            damage      = damage,   tgt_hp      = 0 if destroyed else tgt.hp,
            tgt_max_hp  = unit_types.get(tgt.type, {}).get("hp", 100),
            destroyed   = destroyed,
            src_lat     = src.lat,  src_lng     = src.lng,
            tgt_lat     = tgt.lat,  tgt_lng     = tgt.lng,
            is_counter  = False,
        ))

        save_state()
        return ActionResponse(
            status  = "ok",
            message = f"攻擊！造成 {damage} 傷害" + ("（已摧毀）" if destroyed else ""),
            damage=damage, target_hp=0 if destroyed else tgt.hp, destroyed=destroyed,
        )

    # ── 補給 ──────────────────────────────────────
    if req.action_type == "supply":
        if src.type not in SUPPLY_TYPES:
            return ActionResponse(status="error", message=f"{src.type} 不是補給兵")
        if src.faction != tgt.faction:
            return ActionResponse(status="error", message="只能補給己方")
        if dist_km > SUPPLY_RANGE_KM:
            return ActionResponse(status="error",
                message=f"距離太遠（{dist_km:.2f} km，射程 {SUPPLY_RANGE_KM} km）")

        before   = tgt.ammo
        tgt.ammo = min(MAX_AMMO, tgt.ammo + SUPPLY_AMOUNT)
        save_state()
        return ActionResponse(
            status    = "ok",
            message   = f"補給 +{tgt.ammo - before} 彈藥",
            ammo_given  = tgt.ammo - before,
            target_ammo = tgt.ammo,
        )

    return ActionResponse(status="error", message=f"未知行動：{req.action_type}")

#新增刪除功能
@router.delete("/api/battle/unit/{unit_id}")
async def remove_unit(unit_id: str):
    """直接從戰場移除指定單位（不論 HP）。"""
    before = len(_state.units)
    _state.units = [u for u in _state.units if u.id != unit_id]
    if len(_state.units) == before:
        raise HTTPException(404, detail=f"找不到單位：{unit_id}")
    save_state()
    return {"ok": True, "removed": unit_id}

# ═══════════════════════════════════════════════════════════════
#  存檔 / 重置
# ═══════════════════════════════════════════════════════════════

@router.post("/api/save")
async def manual_save():
    save_state()
    return {"ok": True, "msg": f"已存檔，共 {len(_state.units)} 個單位"}


@router.post("/api/reset")
async def reset_state():
    _state.units = []
    _state.tick  = 0
    _combat_log.clear()
    _fuel_log.clear()
    save_state()
    return {"ok": True, "msg": "戰場已重置"}
