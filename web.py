"""Web UI 與 API 入口。提供排程貼文管理、AI 產文、Token 管理。

啟動時自動帶起背景排程器，不需額外執行 main.py start。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import init_db, add_post, list_posts, remove_post, save_config, get_active_access_token
from ai_writer import generate_article
from scheduler import start_background_scheduler
from token_manager import renew_page_token, debug_token

load_dotenv()

app = FastAPI(title="Facebook 自動發文排程")

STATIC_DIR = Path(__file__).resolve().parent / "static"

PAGE_ID = os.getenv("FB_PAGE_ID", "")
ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")
FB_APP_ID = os.getenv("FB_APP_ID", "")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")


class AddPostBody(BaseModel):
    message: str
    scheduled_time: str  # "YYYY-MM-DDTHH:MM" 或 "YYYY-MM-DD HH:MM"
    link: str | None = None


class GenerateBody(BaseModel):
    topic: str


class RenewTokenBody(BaseModel):
    short_token: str


@app.on_event("startup")
def startup():
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("請設定環境變數 DATABASE_URL")
    init_db()
    # 自動啟動背景排程器
    if PAGE_ID and ACCESS_TOKEN:
        start_background_scheduler(PAGE_ID, ACCESS_TOKEN)


# ── 排程 API ──────────────────────────────────────────────

@app.get("/api/posts")
def api_list_posts(status: str | None = None):
    if status and status not in ("pending", "sent", "failed"):
        raise HTTPException(status_code=400, detail="status 必須為 pending, sent 或 failed")
    return list_posts(status_filter=status)


@app.post("/api/posts")
def api_add_post(body: AddPostBody):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="貼文內容不可為空")
    time_str = body.scheduled_time.replace("T", " ")[:16]
    try:
        post = add_post(body.message.strip(), time_str)
        return post
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/posts/{post_id}")
def api_remove_post(post_id: str):
    try:
        return remove_post(post_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── AI 產文 API ──────────────────────────────────────────

@app.post("/api/generate")
def api_generate(body: GenerateBody):
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="主題不可為空")
    try:
        article = generate_article(body.topic.strip())
        return {"article": article}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Token 管理 API ───────────────────────────────────────

@app.get("/api/token/status")
def api_token_status():
    """檢查目前 Token 的狀態。"""
    if not FB_APP_ID or not FB_APP_SECRET:
        return {"error": "未設定 FB_APP_ID / FB_APP_SECRET"}

    token = get_active_access_token()
    if not token:
        return {"has_token": False, "source": None}

    source = "database" if token != ACCESS_TOKEN else "env"
    result = {"has_token": True, "source": source, "token_preview": token[:20] + "..."}

    try:
        info = debug_token(token, FB_APP_ID, FB_APP_SECRET)
        result["is_valid"] = info.get("is_valid", False)
        result["expires_at"] = info.get("expires_at", 0)
        result["type"] = info.get("type", "")
        result["scopes"] = info.get("scopes", [])
    except Exception as e:
        result["check_error"] = str(e)

    return result


@app.post("/api/token/renew")
def api_renew_token(body: RenewTokenBody):
    """用短期 Token 換取永久 Page Token 並存入資料庫。"""
    if not FB_APP_ID or not FB_APP_SECRET:
        raise HTTPException(status_code=400, detail="未設定 FB_APP_ID / FB_APP_SECRET")
    if not body.short_token.strip():
        raise HTTPException(status_code=400, detail="Token 不可為空")

    try:
        page_token = renew_page_token(
            app_id=FB_APP_ID,
            app_secret=FB_APP_SECRET,
            short_lived_token=body.short_token.strip(),
            page_id=PAGE_ID,
        )
        save_config("fb_page_access_token", page_token)
        return {"success": True, "token_preview": page_token[:20] + "..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 靜態檔案 ─────────────────────────────────────────────

@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
