"""PostgreSQL 資料庫模組。

提供排程貼文的 CRUD 操作，取代原本的 JSON 檔案儲存。
連線字串從環境變數 DATABASE_URL 讀取。
"""

import os
import uuid
from datetime import datetime

import psycopg2
import psycopg2.extras


def _get_conn():
    """取得資料庫連線。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("錯誤：環境變數 DATABASE_URL 未設定。")
    return psycopg2.connect(database_url)


def init_db():
    """初始化資料庫：建立 posts 和 config 資料表（如果不存在）。"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id              VARCHAR(8) PRIMARY KEY,
                    message         TEXT NOT NULL,
                    scheduled_time  TIMESTAMP NOT NULL,
                    status          VARCHAR(10) DEFAULT 'pending',
                    created_at      TIMESTAMP DEFAULT NOW(),
                    sent_at         TIMESTAMP,
                    fb_post_id      VARCHAR(100),
                    error           TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key             VARCHAR(50) PRIMARY KEY,
                    value           TEXT NOT NULL,
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
            """)
        conn.commit()
    finally:
        conn.close()


def add_post(message: str, scheduled_time_str: str) -> dict:
    """新增一筆排程貼文。

    Args:
        message: 貼文內容
        scheduled_time_str: 排程時間，格式 "YYYY/MM/DD HH:MM" 或 "YYYY-MM-DD HH:MM"

    Returns:
        新建立的排程貼文 dict

    Raises:
        ValueError: 時間格式錯誤或時間已過
    """
    normalized = scheduled_time_str.replace("/", "-")
    try:
        scheduled_dt = datetime.strptime(normalized, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(
            f"時間格式錯誤：'{scheduled_time_str}'。請使用 YYYY/MM/DD HH:MM 格式。"
        )

    if scheduled_dt <= datetime.now():
        raise ValueError("排程時間必須是未來的時間。")

    post_id = uuid.uuid4().hex[:8]
    now = datetime.now()

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO posts (id, message, scheduled_time, status, created_at)
                VALUES (%s, %s, %s, 'pending', %s)
                """,
                (post_id, message, scheduled_dt, now),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "id": post_id,
        "message": message,
        "scheduled_time": scheduled_dt.isoformat(),
        "status": "pending",
        "created_at": now.isoformat(),
        "sent_at": None,
        "fb_post_id": None,
        "error": None,
    }


def list_posts(status_filter: str = None) -> list:
    """列出排程貼文，可依狀態篩選，按排程時間排序。"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status_filter:
                cur.execute(
                    "SELECT * FROM posts WHERE status = %s ORDER BY scheduled_time",
                    (status_filter,),
                )
            else:
                cur.execute("SELECT * FROM posts ORDER BY scheduled_time")
            rows = cur.fetchall()
    finally:
        conn.close()

    # 將 datetime 欄位轉為 ISO 字串（與原本 JSON 格式相容）
    posts = []
    for row in rows:
        post = dict(row)
        for key in ("scheduled_time", "created_at", "sent_at"):
            if post[key] is not None:
                post[key] = post[key].isoformat()
        posts.append(post)
    return posts


def get_post(post_id: str) -> dict | None:
    """根據 ID 取得單一貼文，找不到回傳 None。"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    post = dict(row)
    for key in ("scheduled_time", "created_at", "sent_at"):
        if post[key] is not None:
            post[key] = post[key].isoformat()
    return post


def remove_post(post_id: str) -> dict:
    """移除一筆待發送的排程貼文。

    Raises:
        ValueError: 找不到貼文或貼文非待發送狀態
    """
    post = get_post(post_id)
    if post is None:
        raise ValueError(f"找不到 ID 為 '{post_id}' 的排程貼文。")
    if post["status"] != "pending":
        raise ValueError(
            f"只能移除待發送的貼文。此貼文狀態為：{post['status']}"
        )

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM posts WHERE id = %s", (post_id,))
        conn.commit()
    finally:
        conn.close()

    return post


def update_post_status(
    post_id: str,
    status: str,
    sent_at: str = None,
    fb_post_id: str = None,
    error: str = None,
) -> None:
    """更新貼文狀態（發送成功或失敗時呼叫）。"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE posts
                SET status = %s, sent_at = %s, fb_post_id = %s, error = %s
                WHERE id = %s
                """,
                (status, sent_at, fb_post_id, error, post_id),
            )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
#  Config（Token 動態儲存）
# ═══════════════════════════════════════════════════════════

def save_config(key: str, value: str) -> None:
    """儲存設定值（用 UPSERT，存在則更新）。"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO config (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, value),
            )
        conn.commit()
    finally:
        conn.close()


def get_config(key: str) -> str | None:
    """讀取設定值，找不到回傳 None。"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM config WHERE key = %s", (key,))
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def get_active_access_token() -> str | None:
    """取得目前有效的 Page Access Token。

    優先從資料庫讀取（動態更新的永久 token），
    若資料庫沒有則退回環境變數 FB_ACCESS_TOKEN。
    """
    db_token = get_config("fb_page_access_token")
    if db_token:
        return db_token
    return os.getenv("FB_ACCESS_TOKEN")
