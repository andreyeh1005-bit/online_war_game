import asyncio

from model.config import TICK_INTERVAL, SAVE_EVERY_N_TICKS
from model.state_manager import _state, save_state

# 匯入剛才拆分出去的各個子系統邏輯
from movement import move_unit_one_tick, chase_tick
from engine import fuel_tick
from combat import auto_combat_tick

async def game_loop() -> None:
    """
    每 TICK_INTERVAL 秒執行一次：
      1. 推進所有單位的移動
      2. 執行追擊目標鎖定與 Stance 切換
      3. 處理燃油消耗 / 補油 / 墜毀
      4. 執行自動戰鬥
      5. 定期自動存檔
    """
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        _state.tick += 1

        # 1. 移動物理推進
        for unit in list(_state.units):
            move_unit_one_tick(unit, TICK_INTERVAL)

        # 2. 追擊邏輯檢測
        chase_tick()

        # 3. 燃油狀態狀態機
        fuel_tick()

        # 4. 自動戰鬥與反擊結算
        auto_combat_tick()

        # 5. 定期自動存檔
        if _state.tick % SAVE_EVERY_N_TICKS == 0:
            save_state()