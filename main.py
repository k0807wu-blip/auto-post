import os
import sys

from dotenv import load_dotenv

from fb_poster import get_page_info, publish_text_post, publish_link_post
from db import add_post, list_posts, remove_post, init_db, save_config, get_active_access_token
from scheduler import start_daemon, stop_daemon, daemon_status
from token_manager import renew_page_token, debug_token

load_dotenv()

PAGE_ID = os.getenv("FB_PAGE_ID")
ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")

DATABASE_URL = os.getenv("DATABASE_URL")


def check_config():
    """檢查必要的環境變數是否已設定。"""
    if not PAGE_ID or not ACCESS_TOKEN:
        print("錯誤：請先在 .env 檔案中設定 FB_PAGE_ID 和 FB_ACCESS_TOKEN")
        print("可參考 .env.example")
        sys.exit(1)
    if not DATABASE_URL:
        print("錯誤：請在 .env 檔案中設定 DATABASE_URL")
        print("範例：DATABASE_URL=postgresql://使用者:密碼@localhost:5432/auto_post")
        sys.exit(1)


# ── 即時發文指令 ──────────────────────────────────────────

def cmd_verify():
    """驗證 token 和 page ID 是否有效。"""
    print("正在驗證 Facebook API 連線...")
    try:
        info = get_page_info(PAGE_ID, ACCESS_TOKEN)
        print(f"連線成功！")
        print(f"  粉絲專頁名稱: {info.get('name')}")
        print(f"  粉絲專頁 ID:  {info.get('id')}")
        print(f"  粉絲數:       {info.get('fan_count')}")
    except Exception as e:
        print(f"連線失敗: {e}")
        sys.exit(1)


def cmd_post():
    """互動式發文。"""
    print("--- Facebook 粉絲專頁發文 ---")
    message = input("請輸入貼文內容: ").strip()
    if not message:
        print("貼文內容不可為空。")
        return

    link = input("附加連結 (可選，按 Enter 跳過): ").strip()

    try:
        if link:
            result = publish_link_post(PAGE_ID, ACCESS_TOKEN, message, link)
        else:
            result = publish_text_post(PAGE_ID, ACCESS_TOKEN, message)

        post_id = result.get("id")
        print(f"發文成功！貼文 ID: {post_id}")
    except Exception as e:
        print(f"發文失敗: {e}")


def cmd_quick_post(message: str):
    """快速發文（從命令列引數直接發文）。"""
    try:
        result = publish_text_post(PAGE_ID, ACCESS_TOKEN, message)
        post_id = result.get("id")
        print(f"發文成功！貼文 ID: {post_id}")
    except Exception as e:
        print(f"發文失敗: {e}")


# ── 排程指令 ──────────────────────────────────────────────

def cmd_schedule_add():
    """新增排程貼文。"""
    if len(sys.argv) < 4:
        print('用法: python main.py add "YYYY/MM/DD HH:MM" "貼文內容"')
        print('範例: python main.py add "2025/02/15 14:30" "Hello world!"')
        sys.exit(1)

    time_str = sys.argv[2]
    message = sys.argv[3]

    try:
        post = add_post(message, time_str)
        print(f"已新增排程貼文！")
        print(f"  ID:       {post['id']}")
        print(f"  排程時間: {post['scheduled_time'].replace('T', ' ')}")
        print(f"  貼文內容: {post['message'][:50]}")
        status = daemon_status()
        if not status["running"]:
            print("\n提醒：排程器尚未啟動。請執行 python main.py start 以啟動排程器。")
    except ValueError as e:
        print(f"錯誤：{e}")
        sys.exit(1)


def cmd_schedule_list():
    """列出排程貼文。"""
    status_filter = sys.argv[2] if len(sys.argv) > 2 else None

    if status_filter and status_filter not in ("pending", "sent", "failed"):
        print("篩選條件必須是: pending, sent, 或 failed")
        sys.exit(1)

    posts = list_posts(status_filter=status_filter)

    if not posts:
        if status_filter:
            print(f"沒有狀態為 '{status_filter}' 的排程貼文。")
        else:
            print("排程列表為空。")
        return

    status_labels = {
        "pending": "⏳ 待發送",
        "sent": "✅ 已發送",
        "failed": "❌ 失敗",
    }

    print(f"{'ID':<10} {'狀態':<12} {'排程時間':<20} {'貼文內容'}")
    print("-" * 72)
    for post in posts:
        status_text = status_labels.get(post["status"], post["status"])
        time_display = post["scheduled_time"].replace("T", " ")
        message_preview = post["message"][:30]
        if len(post["message"]) > 30:
            message_preview += "..."
        print(f"{post['id']:<10} {status_text:<10} {time_display:<20} {message_preview}")


def cmd_schedule_remove():
    """移除排程貼文。"""
    if len(sys.argv) < 3:
        print("用法: python main.py remove <貼文ID>")
        print("請先使用 python main.py list 查看貼文 ID。")
        sys.exit(1)

    post_id = sys.argv[2]
    try:
        removed = remove_post(post_id)
        print(f"已移除排程貼文：{removed['id']}")
        print(f"  排程時間: {removed['scheduled_time'].replace('T', ' ')}")
        print(f"  貼文內容: {removed['message'][:50]}")
    except ValueError as e:
        print(f"錯誤：{e}")
        sys.exit(1)


def cmd_renew_token():
    """用短期 User Token 換取永久 Page Token 並存入資料庫。"""
    if not FB_APP_ID or not FB_APP_SECRET:
        print("錯誤：請在 .env 中設定 FB_APP_ID 和 FB_APP_SECRET")
        print("可在 https://developers.facebook.com 的 App 設定 > 基本資料 中找到")
        sys.exit(1)

    print("=== Facebook Token 更新工具 ===")
    print()
    print("請先到 Graph API Explorer 取得一組新的短期 User Token：")
    print("https://developers.facebook.com/tools/explorer/?method=GET&path=me%2Faccounts&version=v24.0")
    print()
    print("步驟：")
    print("  1. 按「Generate Access Token」並完成授權")
    print("  2. 複製上方的 Access Token")
    print("  3. 貼到下方")
    print()
    short_token = input("請貼上短期 User Token: ").strip()
    if not short_token:
        print("錯誤：Token 不可為空。")
        sys.exit(1)

    try:
        page_token = renew_page_token(
            app_id=FB_APP_ID,
            app_secret=FB_APP_SECRET,
            short_lived_token=short_token,
            page_id=PAGE_ID,
        )

        # 存入資料庫
        save_config("fb_page_access_token", page_token)
        print()
        print("✅ 永久 Page Token 已儲存到資料庫！")
        print("   之後排程器發文會自動使用這個 token，不再需要手動更新。")
        print()
        print(f"   Token 前 20 字元：{page_token[:20]}...")
    except Exception as e:
        print(f"\n❌ 失敗：{e}")
        sys.exit(1)


def cmd_check_token():
    """檢查目前使用的 token 狀態。"""
    if not FB_APP_ID or not FB_APP_SECRET:
        print("錯誤：請在 .env 中設定 FB_APP_ID 和 FB_APP_SECRET 才能檢查 token")
        sys.exit(1)

    token = get_active_access_token()
    if not token:
        print("❌ 找不到任何 Access Token（資料庫和環境變數都沒有）。")
        print("   請執行 python main.py renew-token 來設定。")
        sys.exit(1)

    source = "資料庫（永久 Token）" if token != ACCESS_TOKEN else "環境變數 FB_ACCESS_TOKEN"
    print(f"目前使用的 Token 來源：{source}")
    print(f"Token 前 20 字元：{token[:20]}...")
    print()

    try:
        info = debug_token(token, FB_APP_ID, FB_APP_SECRET)
        is_valid = info.get("is_valid", False)
        expires = info.get("expires_at", 0)
        app_name = info.get("application", "")
        token_type = info.get("type", "")

        if is_valid:
            print(f"✅ Token 有效")
        else:
            print(f"❌ Token 已失效")

        print(f"   類型：{token_type}")
        print(f"   App：{app_name}")

        if expires == 0:
            print(f"   到期：永不過期")
        else:
            from datetime import datetime
            exp_dt = datetime.fromtimestamp(expires)
            print(f"   到期：{exp_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        scopes = info.get("scopes", [])
        if scopes:
            print(f"   權限：{', '.join(scopes)}")
    except Exception as e:
        print(f"⚠️  無法檢查 token 詳細資訊：{e}")
        print("   但 token 可能仍然有效，可嘗試 python main.py verify 測試。")


def cmd_start():
    """啟動排程器。"""
    print("正在啟動排程器...")
    start_daemon(PAGE_ID, ACCESS_TOKEN)


def cmd_stop():
    """停止排程器。"""
    stop_daemon()


def cmd_status():
    """查看排程器狀態。"""
    info = daemon_status()
    if info["running"]:
        print(f"排程器執行中 (PID: {info['pid']})")
        pending = list_posts(status_filter="pending")
        print(f"待發送的貼文: {len(pending)} 則")
    else:
        print("排程器未在執行中。")


# ── 主程式 ────────────────────────────────────────────────

def main():
    check_config()
    init_db()

    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py verify                     - 驗證 API 連線")
        print("  python main.py post                       - 互動式發文")
        print('  python main.py quick "內容"               - 快速發文')
        print()
        print("  排程功能:")
        print('  python main.py add "時間" "內容"          - 新增排程貼文')
        print("  python main.py list [pending|sent|failed] - 列出排程貼文")
        print("  python main.py remove <ID>                - 移除排程貼文")
        print("  python main.py start                      - 啟動排程器")
        print("  python main.py stop                       - 停止排程器")
        print("  python main.py status                     - 查看排程器狀態")
        print()
        print("  Token 管理:")
        print("  python main.py renew-token                - 更新永久 Page Token")
        print("  python main.py check-token                - 檢查 Token 狀態")
        sys.exit(0)

    command = sys.argv[1]

    if command == "verify":
        cmd_verify()
    elif command == "post":
        cmd_post()
    elif command == "quick":
        if len(sys.argv) < 3:
            print('用法: python main.py quick "你的貼文內容"')
            sys.exit(1)
        cmd_quick_post(sys.argv[2])
    elif command == "add":
        cmd_schedule_add()
    elif command == "list":
        cmd_schedule_list()
    elif command == "remove":
        cmd_schedule_remove()
    elif command == "start":
        cmd_start()
    elif command == "stop":
        cmd_stop()
    elif command == "status":
        cmd_status()
    elif command == "renew-token":
        cmd_renew_token()
    elif command == "check-token":
        cmd_check_token()
    else:
        print(f"未知指令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
