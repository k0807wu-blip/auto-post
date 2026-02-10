"""Web UI 與 API 入口。提供排程貼文的新增、列表、刪除。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import init_db, add_post, list_posts, remove_post

load_dotenv()

app = FastAPI(title="Facebook 自動發文排程")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class AddPostBody(BaseModel):
    message: str
    scheduled_time: str  # "YYYY-MM-DDTHH:MM" 或 "YYYY-MM-DD HH:MM"
    link: str | None = None


@app.on_event("startup")
def startup():
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("請設定環境變數 DATABASE_URL")
    init_db()


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


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
