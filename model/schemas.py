from typing import List, Literal, Optional, Dict
from pydantic import BaseModel, field_validator

from model.config import MAX_FUEL

# ═══════════════════════════════════════════════════════════════
#  共用型別
# ═══════════════════════════════════════════════════════════════

Waypoint = List[float]

# ═══════════════════════════════════════════════════════════════
#  核心實體模型 (Entities)
# ═══════════════════════════════════════════════════════════════

class Unit(BaseModel):
    id:               str
    type:             str
    faction:          str
    lat:              float
    lng:              float
    hp:               int
    ammo:             int
    attack:           int             = 0
    domain:           str             = "land"
    max_range_km:     float           = 1.0
    speed_km_h:       float           = 5.0
    target_lat:       Optional[float] = None
    target_lng:       Optional[float] = None
    waypoints:        List[Waypoint]  = []
    locked_target_id: Optional[str]   = None
    stance:           str             = "hold"     # "hold" | "free"
    combat_cooldown:  int             = 0
    engaged_target:   Optional[str]   = None
    chase_target_id:  Optional[str]   = None       # 追擊目標：移動靠近後自動開火
    
    # ── 燃油系統 ──
    is_airport:       bool            = False      # 機場旗標
    fuel:             int             = MAX_FUEL   # 當前燃油
    returning:        bool            = False      # 是否正在返航
    refuel_notified:  bool            = False      # 補滿通知防重複旗標


class BattleState(BaseModel):
    units: List[Unit]
    tick:  int = 0


class UnitTypeModel(BaseModel):
    name:                str
    domain:              Literal["land", "air", "sea"]
    hp:                  int
    speed_km_h:          float
    attack:              int
    max_range_km:        float
    ammo_cost:           int   = 1
    can_hit:             List[Literal["land", "air", "sea"]]
    bonuses:             Dict[str, float] = {}
    fuel_burn_per_tick:  float = 0.0
    refuel_range_km:     float = 0.0
    refuel_per_tick:     int   = 0
    icon:                str   = "infantry"   


# ═══════════════════════════════════════════════════════════════
#  事件紀錄模型 (Events)
# ═══════════════════════════════════════════════════════════════

class CombatEvent(BaseModel):
    tick:        int
    src_id:      str
    src_faction: str
    src_type:    str
    tgt_id:      str
    tgt_faction: str
    tgt_type:    str
    damage:      int
    tgt_hp:      int
    tgt_max_hp:  int
    destroyed:   bool
    src_lat:     float
    src_lng:     float
    tgt_lat:     float
    tgt_lng:     float
    is_counter:  bool = False


class FuelEvent(BaseModel):
    tick:      int
    unit_id:   str
    faction:   str
    unit_type: str
    fuel:      int
    event:     str    # "warn" | "auto_return" | "refueled" | "crashed"
    lat:       float
    lng:       float


# ═══════════════════════════════════════════════════════════════
#  API 請求模型 (Requests)
# ═══════════════════════════════════════════════════════════════

class DeployRequest(BaseModel):
    faction: Literal["國軍", "共軍"]
    type:    str
    lat:     float
    lng:     float

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v):
        if not (-90 <= v <= 90):
            raise ValueError("緯度超出範圍")
        return round(v, 6)

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v):
        if not (-180 <= v <= 180):
            raise ValueError("經度超出範圍")
        return round(v, 6)


class MoveRequest(BaseModel):
    unit_id:    str
    target_lat: float
    target_lng: float

    @field_validator("target_lat")
    @classmethod
    def check_lat(cls, v):
        if not (-90 <= v <= 90):
            raise ValueError("緯度超出範圍")
        return round(v, 6)

    @field_validator("target_lng")
    @classmethod
    def check_lng(cls, v):
        if not (-180 <= v <= 180):
            raise ValueError("經度超出範圍")
        return round(v, 6)


class StanceRequest(BaseModel):
    unit_id: str
    stance:  Literal["hold", "free"]


class ReturnRequest(BaseModel):
    unit_id: str


class LockTargetRequest(BaseModel):
    unit_id:   str
    target_id: Optional[str] = None


class ActionRequest(BaseModel):
    source_id:   str
    target_id:   str
    action_type: Literal["attack", "supply"]


class EngageRequest(BaseModel):
    """玩家手動指定追擊目標：移動靠近後自動持續開火，直到待命指令。"""
    unit_id:   str
    target_id: str


# ═══════════════════════════════════════════════════════════════
#  API 回應模型 (Responses)
# ═══════════════════════════════════════════════════════════════

class ActionResponse(BaseModel):
    status:      str
    message:     str
    damage:      Optional[int]  = None
    target_hp:   Optional[int]  = None
    destroyed:   Optional[bool] = None
    ammo_given:  Optional[int]  = None
    target_ammo: Optional[int]  = None