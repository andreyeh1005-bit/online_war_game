import json
from collections import deque
from typing import Any, Deque, Dict

# 引入設定與防護網
from model.config import (
    UNITS_FILE, STATE_FILE, DEFAULT_UNIT_TYPES, 
    COMBAT_LOG_MAX, FUEL_LOG_MAX
)
from model.schemas import BattleState, CombatEvent, FuelEvent

# ═══════════════════════════════════════════════════════════════
#  兵種設定管理 (唯讀快取與檔案同步)
# ═══════════════════════════════════════════════════════════════

def is_road_unit(domain: str) -> bool:

    return domain == "land"

def load_unit_types() -> Dict[str, Any]:
    """從 units.json 載入兵種設定，若無則寫入預設值。"""
    if not UNITS_FILE.exists():
        save_unit_types(DEFAULT_UNIT_TYPES)
        return dict(DEFAULT_UNIT_TYPES)
    with UNITS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_unit_types(data: Dict[str, Any]) -> None:
    """將兵種設定保存至 units.json。"""
    with UNITS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 全域兵種設定快取（啟動時載入，供其他模組唯讀查詢）
unit_types: Dict[str, Any] = load_unit_types()


def is_airport_type(type_name: str) -> bool:
    """判斷指定兵種是否為機場 (speed == 0 且 domain == air)。"""
    ut = unit_types.get(type_name, {})
    return ut.get("domain") == "air" and ut.get("speed_km_h", 1) == 0

# ═══════════════════════════════════════════════════════════════
#  戰場狀態與日誌管理 (Singleton)
# ═══════════════════════════════════════════════════════════════

# 在記憶體中維護的遊戲世界狀態
_state:      BattleState         = BattleState(units=[], tick=0)
_combat_log: Deque[CombatEvent]  = deque(maxlen=COMBAT_LOG_MAX)
_fuel_log:   Deque[FuelEvent]    = deque(maxlen=FUEL_LOG_MAX)


def save_state() -> None:
    """將當前戰場狀態序列化並寫入 state.json。"""
    with STATE_FILE.open("w", encoding="utf-8") as f:
        try:
            data = _state.model_dump()
        except AttributeError:
            data = _state.dict() # 兼容 Pydantic v1
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> None:
    """伺服器啟動時從 state.json 還原戰場；失敗則從空白開始。"""
    global _state
    if not STATE_FILE.exists():
        print("[SANDBOX] 沒有 state.json，從空白戰場開始")
        return
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        _state = BattleState(**raw)
        print(f"[SANDBOX] 還原 {len(_state.units)} 個單位（tick={_state.tick}）")
    except Exception as e:
        print(f"[SANDBOX] 讀取失敗（{e}），從空白開始")
        _state = BattleState(units=[], tick=0)