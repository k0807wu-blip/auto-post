"""Facebook Access Token 管理模組。

提供短期 User Token → 長期 User Token → 永不過期 Page Token 的自動轉換。
"""

import logging

import requests

logger = logging.getLogger("token_manager")

GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


def exchange_for_long_lived_user_token(
    app_id: str, app_secret: str, short_lived_token: str
) -> str:
    """將短期 User Token 換成長期 User Token（~60 天）。

    Returns:
        長期 User Token 字串
    """
    url = f"{GRAPH_API_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise RuntimeError(
            f"換取長期 User Token 失敗：{err.get('message', data)}"
        )

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"回應中找不到 access_token：{data}")

    logger.info("成功換取長期 User Token")
    return token


def get_permanent_page_token(
    long_lived_user_token: str, page_id: str
) -> str:
    """用長期 User Token 取得永不過期的 Page Token。

    呼叫 GET /me/accounts，從回傳的粉絲專頁列表中找到對應的 Page Token。

    Returns:
        永不過期的 Page Token 字串
    """
    url = f"{GRAPH_API_BASE}/me/accounts"
    params = {
        "access_token": long_lived_user_token,
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise RuntimeError(
            f"取得 Page Token 失敗：{err.get('message', data)}"
        )

    pages = data.get("data", [])
    if not pages:
        raise RuntimeError(
            "回傳的粉絲專頁列表為空。請確認你的 User Token 有 "
            "pages_show_list, pages_manage_posts 等權限。"
        )

    # 在列表中找到目標粉絲專頁
    for page in pages:
        if page.get("id") == page_id:
            token = page.get("access_token")
            if not token:
                raise RuntimeError(f"粉絲專頁 {page_id} 的回傳中缺少 access_token")
            logger.info(f"成功取得粉絲專頁「{page.get('name')}」的永久 Page Token")
            return token

    # 沒找到指定的 page_id，列出可用的
    available = ", ".join(f"{p.get('name')}({p.get('id')})" for p in pages)
    raise RuntimeError(
        f"找不到 Page ID '{page_id}'。可用的粉絲專頁：{available}"
    )


def renew_page_token(
    app_id: str, app_secret: str, short_lived_token: str, page_id: str
) -> str:
    """一鍵完成：短期 User Token → 長期 User Token → 永久 Page Token。

    Returns:
        永不過期的 Page Token 字串
    """
    print("步驟 1/2：將短期 User Token 換成長期 User Token...")
    long_lived = exchange_for_long_lived_user_token(
        app_id, app_secret, short_lived_token
    )
    print("  ✅ 長期 User Token 取得成功")

    print("步驟 2/2：用長期 User Token 取得永久 Page Token...")
    page_token = get_permanent_page_token(long_lived, page_id)
    print("  ✅ 永久 Page Token 取得成功")

    return page_token


def debug_token(access_token: str, app_id: str, app_secret: str) -> dict:
    """檢查 token 的有效性和過期時間。"""
    url = f"{GRAPH_API_BASE}/debug_token"
    params = {
        "input_token": access_token,
        "access_token": f"{app_id}|{app_secret}",
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Token 檢查失敗：{err.get('message', data)}")

    return data.get("data", {})
