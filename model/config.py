from pathlib import Path
from typing import Any, Dict

# ═══════════════════════════════════════════════════════════════
#  檔案路徑與外部 API
# ═══════════════════════════════════════════════════════════════

UNITS_FILE = Path("units.json")
STATE_FILE = Path("state.json")

OSRM_URL = (
    "https://router.project-osrm.org/route/v1/driving/"
    "{lng1},{lat1};{lng2},{lat2}"
    "?overview=full&geometries=geojson"
)

# ═══════════════════════════════════════════════════════════════
#  系統與戰鬥機制常數
# ═══════════════════════════════════════════════════════════════

TICK_INTERVAL         = 1.0     # 伺服器每 Tick 間隔 (秒)
SAVE_EVERY_N_TICKS    = 10      # 每 N 個 Tick 執行一次自動存檔
ARRIVE_THRESH         = 0.010   # 判定抵達目標的距離閾值 (km)

COMBAT_LOG_MAX        = 200     # 交戰紀錄最大保留筆數
FUEL_LOG_MAX          = 100     # 燃油事件最大保留筆數
COMBAT_COOLDOWN_TICKS = 5       # 攻擊後的冷卻時間 (ticks)

# ── 後勤與補給 ──────────────────────────────────────────
SUPPLY_TYPES          = {"補給兵", "後勤"}
SUPPLY_RANGE_KM       = 0.5     # 補給判定範圍 (km)
SUPPLY_AMOUNT         = 10      # 每次補給給予的彈藥量
MAX_AMMO              = 30      # 單位最大彈藥攜帶量

# ── 燃油相關 (Fallback 預設值，實際依 units.json 覆蓋) ───
MAX_FUEL              = 100
FUEL_BURN_PER_TICK    = 1
FUEL_WARN_PCT         = 30      # 剩餘燃油警告閾值 (%)
FUEL_AUTO_RETURN_PCT  = 20      # 自動返航閾值 (%)
REFUEL_RANGE_KM       = 0.5
REFUEL_PER_TICK       = 5


# ═══════════════════════════════════════════════════════════════
#  預設兵種設定 (首次啟動或 units.json 遺失時使用)
# ═══════════════════════════════════════════════════════════════

DEFAULT_UNIT_TYPES: Dict[str, Any] = {
    "步兵": {
        "name": "步兵", "domain": "land", "hp": 100, "speed_km_h": 5,
        "attack": 15, "max_range_km": 0.8, "ammo_cost": 1,
        "can_hit": ["land"], "bonuses": {},
        "fuel_burn_per_tick": 0, "refuel_range_km": 0, "refuel_per_tick": 0,
        "icon": "infantry",
    },
    "坦克": {
        "name": "坦克", "domain": "land", "hp": 300, "speed_km_h": 50,
        "attack": 60, "max_range_km": 2.0, "ammo_cost": 1,
        "can_hit": ["land", "sea"], "bonuses": {"步兵": 2.0},
        "fuel_burn_per_tick": 0, "refuel_range_km": 0, "refuel_per_tick": 0,
        "icon": "tank",
    },
    "轟炸機": {
        "name": "轟炸機", "domain": "air", "hp": 150, "speed_km_h": 800,
        "attack": 120, "max_range_km": 30.0, "ammo_cost": 2,
        "can_hit": ["land", "sea", "air"], "bonuses": {"坦克": 1.5, "驅逐艦": 1.8},
        "fuel_burn_per_tick": 1, "refuel_range_km": 0, "refuel_per_tick": 0,
        "icon": "plane",
    },
    "驅逐艦": {
        "name": "驅逐艦", "domain": "sea", "hp": 500, "speed_km_h": 60,
        "attack": 80, "max_range_km": 15.0, "ammo_cost": 2,
        "can_hit": ["sea", "land"], "bonuses": {},
        "fuel_burn_per_tick": 0, "refuel_range_km": 0, "refuel_per_tick": 0,
        "icon": "ship",
    },
    "機場": {
        "name": "機場", "domain": "air", "hp": 800, "speed_km_h": 0,
        "attack": 0, "max_range_km": 0, "ammo_cost": 0,
        "can_hit": [], "bonuses": {},
        "fuel_burn_per_tick": 0, "refuel_range_km": 0.5, "refuel_per_tick": 5,
        "icon": "flag",
    },
}