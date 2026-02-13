"""Facebook 自動發文排程模組。

提供背景常駐排程器的啟動與停止。
資料儲存於 PostgreSQL，使用 APScheduler 進行定時觸發。
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

# 排程時間以台灣時區解讀（與 UI 選擇的本地時間一致）
TZ_TAIPEI = ZoneInfo("Asia/Taipei")

from db import get_post, list_posts, update_post_status, init_db, get_active_access_token
from fb_poster import publish_text_post

# ── 路徑常數 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / "scheduler.pid"

# ── 日誌設定 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


# ═══════════════════════════════════════════════════════════
#  排程執行
# ═══════════════════════════════════════════════════════════

def _execute_post(post_id: str, page_id: str, access_token: str) -> None:
    """APScheduler 觸發時的回呼函式：發文並更新狀態。

    access_token 參數作為備用，優先從資料庫讀取最新的動態 token。
    """
    post = get_post(post_id)

    if post is None:
        logger.warning(f"排程貼文 {post_id} 已不存在，跳過。")
        return

    if post["status"] != "pending":
        logger.info(f"排程貼文 {post_id} 狀態為 {post['status']}，跳過。")
        return

    # 每次發文前從 DB 讀取最新 token（永久 Page Token），退回環境變數
    current_token = get_active_access_token() or access_token
    logger.info(f"正在發送排程貼文 {post_id}：{post['message'][:30]}...")

    try:
        result = publish_text_post(page_id, current_token, post["message"])
        fb_post_id = result.get("id")
        update_post_status(
            post_id,
            status="sent",
            sent_at=datetime.now().isoformat(),
            fb_post_id=fb_post_id,
        )
        logger.info(f"貼文 {post_id} 發送成功！FB ID: {fb_post_id}")
    except Exception as e:
        update_post_status(
            post_id,
            status="failed",
            error=str(e),
        )
        logger.error(f"貼文 {post_id} 發送失敗：{e}")


def _register_pending_posts(
    scheduler: BackgroundScheduler, page_id: str, access_token: str
) -> int:
    """將所有 pending 貼文註冊到 APScheduler，回傳新註冊數量。"""
    pending = list_posts(status_filter="pending")
    count = 0
    for post in pending:
        job_id = f"post_{post['id']}"

        # 已註冊過的跳過
        if scheduler.get_job(job_id):
            continue

        scheduled_dt = datetime.fromisoformat(post["scheduled_time"])
        now_tw = datetime.now(TZ_TAIPEI)
        now_naive_tw = now_tw.replace(tzinfo=None)

        if scheduled_dt <= now_naive_tw:
            # 已過時的貼文，立即執行
            logger.warning(
                f"排程貼文 {post['id']} 已過時 ({post['scheduled_time']})，立即執行。"
            )
            scheduler.add_job(
                _execute_post,
                "date",
                run_date=now_tw,
                args=[post["id"], page_id, access_token],
                id=job_id,
            )
        else:
            scheduler.add_job(
                _execute_post,
                "date",
                run_date=scheduled_dt,
                args=[post["id"], page_id, access_token],
                id=job_id,
            )

        count += 1
        logger.info(
            f"已註冊排程：{post['id']} -> {post['scheduled_time']} "
            f"({post['message'][:20]}...)"
        )
    return count


def _sync_new_posts(
    scheduler: BackgroundScheduler, page_id: str, access_token: str
) -> None:
    """定時同步：從資料庫讀取並註冊新的 pending 貼文。"""
    count = _register_pending_posts(scheduler, page_id, access_token)
    if count > 0:
        logger.info(f"同步完成：新增 {count} 個排程任務。")


# ═══════════════════════════════════════════════════════════
#  背景常駐排程器
# ═══════════════════════════════════════════════════════════

def start_background_scheduler(page_id: str, access_token: str) -> BackgroundScheduler:
    """啟動背景排程器（非阻塞），回傳 scheduler 實例。

    供 Web 應用（uvicorn）在啟動時呼叫，讓排程器跑在同一行程中。
    """
    init_db()

    scheduler = BackgroundScheduler(timezone=TZ_TAIPEI)
    scheduler.start()

    logger.info(f"背景排程器已啟動 (PID: {os.getpid()})")

    # 註冊所有 pending 貼文
    count = _register_pending_posts(scheduler, page_id, access_token)
    logger.info(f"已載入 {count} 個待發送排程。")

    # 每 60 秒同步新增的排程
    scheduler.add_job(
        _sync_new_posts,
        "interval",
        seconds=60,
        args=[scheduler, page_id, access_token],
        id="__sync_new_posts__",
    )

    return scheduler


def start_daemon(page_id: str, access_token: str) -> None:
    """啟動背景排程器（前景執行，Ctrl+C 或 SIGTERM 停止）。"""
    # 檢查是否已在執行中
    if PID_FILE.exists():
        old_pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(old_pid, 0)
            print(f"排程器已在執行中 (PID: {old_pid})。")
            print("如需重啟，請先執行: python main.py stop")
            return
        except OSError:
            # 舊行程已死，清理過期 PID 檔
            PID_FILE.unlink()

    scheduler = start_background_scheduler(page_id, access_token)

    # 寫入 PID 檔
    PID_FILE.write_text(str(os.getpid()))

    # 優雅關閉
    def shutdown(signum, frame):
        logger.info("收到停止信號，正在關閉排程器...")
        scheduler.shutdown(wait=False)
        if PID_FILE.exists():
            PID_FILE.unlink()
        logger.info("排程器已停止。")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print("排程器正在執行中。按 Ctrl+C 停止，或從另一個終端執行: python main.py stop")

    # 主執行緒保持存活
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass


def stop_daemon() -> None:
    """停止背景排程器。"""
    if not PID_FILE.exists():
        print("排程器目前沒有在執行中。")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已送出停止信號給排程器 (PID: {pid})。")
        # 等待 PID 檔被清除
        for _ in range(10):
            time.sleep(0.5)
            if not PID_FILE.exists():
                print("排程器已成功停止。")
                return
        print("排程器可能仍在關閉中，請稍候確認。")
    except ProcessLookupError:
        print(f"排程器行程 (PID: {pid}) 已不存在，清理 PID 檔案。")
        PID_FILE.unlink()
    except PermissionError:
        print(f"權限不足，無法停止排程器行程 (PID: {pid})。")


def daemon_status() -> dict:
    """檢查排程器是否在執行中。回傳 {'running': bool, 'pid': int|None}。"""
    if not PID_FILE.exists():
        return {"running": False, "pid": None}
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)
        return {"running": True, "pid": pid}
    except OSError:
        PID_FILE.unlink()
        return {"running": False, "pid": None}
