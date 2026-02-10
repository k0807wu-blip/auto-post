"""Facebook Access Token 管理模組。

提供短期 User Token → 長期 User Token → 永不過期 Page Token 的自動轉換。
支援偵測 token 類型（User / Page），自動選擇正確的轉換路徑。
"""

import logging

import requests

logger = logging.getLogger("token_manager")

GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


def _detect_token_type(token: str, app_id: str, app_secret: str) -> dict:
    """偵測 token 類型和關聯資訊。

    Returns:
        dict with keys: type ("USER" or "PAGE"), is_valid, expires_at, profile_id
    """
    url = f"{GRAPH_API_BASE}/debug_token"
    params = {
        "input_token": token,
        "access_token": f"{app_id}|{app_secret}",
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Token 偵測失敗：{err.get('message', data)}")

    info = data.get("data", {})
    return {
        "type": info.get("type", "UNKNOWN"),
        "is_valid": info.get("is_valid", False),
        "expires_at": info.get("expires_at", 0),
        "profile_id": info.get("profile_id", ""),
        "user_id": info.get("user_id", ""),
        "scopes": info.get("scopes", []),
    }


def exchange_for_long_lived_token(
    app_id: str, app_secret: str, short_lived_token: str
) -> str:
    """將短期 Token 換成長期 Token（~60 天）。

    對 User Token 和 Page Token 都有效。

    Returns:
        長期 Token 字串
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
            f"換取長期 Token 失敗：{err.get('message', data)}"
        )

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"回應中找不到 access_token：{data}")

    logger.info("成功換取長期 Token")
    return token


def get_page_token_via_user(user_token: str, page_id: str) -> str:
    """用 User Token 呼叫 GET /me/accounts 取得 Page Token。"""
    url = f"{GRAPH_API_BASE}/me/accounts"
    params = {"access_token": user_token}

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

    for page in pages:
        if page.get("id") == page_id:
            token = page.get("access_token")
            if not token:
                raise RuntimeError(f"粉絲專頁 {page_id} 的回傳中缺少 access_token")
            logger.info(f"成功取得粉絲專頁「{page.get('name')}」的 Page Token")
            return token

    available = ", ".join(f"{p.get('name')}({p.get('id')})" for p in pages)
    raise RuntimeError(
        f"找不到 Page ID '{page_id}'。可用的粉絲專頁：{available}"
    )


def get_page_token_via_page(page_token: str, page_id: str) -> str:
    """用 Page Token 呼叫 GET /{page-id}?fields=access_token 取得 Page Token。

    當輸入的是 Page Token 時（無法呼叫 /me/accounts），改用此方法。
    """
    url = f"{GRAPH_API_BASE}/{page_id}"
    params = {
        "fields": "access_token,name",
        "access_token": page_token,
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise RuntimeError(
            f"取得 Page Token 失敗：{err.get('message', data)}"
        )

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"回應中找不到 access_token：{data}")

    name = data.get("name", page_id)
    logger.info(f"成功取得粉絲專頁「{name}」的 Page Token")
    return token


def renew_page_token(
    app_id: str, app_secret: str, short_lived_token: str, page_id: str
) -> str:
    """一鍵完成：自動偵測 token 類型並取得永久 Page Token。

    流程：
    1. 偵測輸入的 token 類型（User / Page）
    2. 換成長期 Token
    3. 取得永久 Page Token（根據類型走不同路徑）

    Returns:
        永不過期的 Page Token 字串
    """
    # 步驟 1: 偵測 token 類型
    print("步驟 1/3：偵測 Token 類型...")
    try:
        token_info = _detect_token_type(short_lived_token, app_id, app_secret)
        token_type = token_info["type"]
        print(f"  偵測結果：{token_type} Token")

        if not token_info["is_valid"]:
            raise RuntimeError("此 Token 已失效，請重新產生。")
    except Exception as e:
        # 偵測失敗時假設為 User Token，繼續嘗試
        print(f"  ⚠️ 偵測失敗（{e}），將以 User Token 方式嘗試...")
        token_type = "USER"

    # 步驟 2: 換成長期 Token
    print("步驟 2/3：將短期 Token 換成長期 Token...")
    long_lived = exchange_for_long_lived_token(
        app_id, app_secret, short_lived_token
    )
    print("  ✅ 長期 Token 取得成功")

    # 步驟 3: 取得永久 Page Token（根據類型選路徑）
    print("步驟 3/3：取得永久 Page Token...")

    if token_type == "PAGE":
        # Page Token → 用 /{page-id}?fields=access_token
        page_token = get_page_token_via_page(long_lived, page_id)
    else:
        # User Token → 用 /me/accounts
        try:
            page_token = get_page_token_via_user(long_lived, page_id)
        except RuntimeError:
            # 如果 /me/accounts 失敗，退回用 /{page-id} 嘗試
            print("  ⚠️ /me/accounts 失敗，改用 /{page-id} 方式嘗試...")
            page_token = get_page_token_via_page(long_lived, page_id)

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
