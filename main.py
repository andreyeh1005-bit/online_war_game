import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from model.state_manager import load_state, save_state
from game_loop import game_loop
from routes import router

# ═══════════════════════════════════════════════════════════════
#  Lifespan：啟動時讀檔 + 建立 game_loop；關閉時存檔
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 啟動 ──────────────────────────────────────
    load_state()                                    # 從 state.json 還原戰場
    loop_task = asyncio.create_task(game_loop())    
    print("[SANDBOX] game_loop 已啟動（移動 + 燃油 + 戰鬥）")
    yield
    # ── 關閉 ──────────────────────────────────────
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    save_state()    # 伺服器正常關閉時存一次檔
    print("[SANDBOX] 已存檔並關閉")

# ═══════════════════════════════════════════════════════════════
#  FastAPI App
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title    = "兵推沙盒引擎",
    version  = "6.1.0",
    lifespan = lifespan,
)

# CORS：允許 file:// 開啟的前端（origin 為 null）
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],   # "*" allow all
    allow_credentials = False,   # 與 allow_origins=["*"] 不可並用 True
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── 掛載所有路由 ───────────────────────────────────
app.include_router(router)

''' 
── 規定不繳交前端，故將此段註解  ───────────────────────────────────
@app.get("/")
async def serve_index():
    return FileResponse("index.html")
─────────────────────────────────────────────────────────────────
'''

# ═══════════════════════════════════════════════════════════════
#  直接執行啟動
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
