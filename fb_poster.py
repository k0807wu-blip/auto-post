import requests


GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


def publish_text_post(page_id: str, access_token: str, message: str) -> dict:
    """在 Facebook 粉絲專頁發佈純文字貼文。

    Args:
        page_id: 粉絲專頁 ID
        access_token: Page Access Token
        message: 貼文內容

    Returns:
        Facebook API 回應 (包含 id 欄位表示成功)

    Raises:
        requests.HTTPError: API 回傳非 2xx 狀態碼
    """
    url = f"{GRAPH_API_BASE}/{page_id}/feed"
    params = {
        "message": message,
        "access_token": access_token,
    }

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def publish_link_post(page_id: str, access_token: str, message: str, link: str) -> dict:
    """在 Facebook 粉絲專頁發佈帶連結的貼文。"""
    url = f"{GRAPH_API_BASE}/{page_id}/feed"
    params = {
        "message": message,
        "link": link,
        "access_token": access_token,
    }

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def publish_photo_post(page_id: str, access_token: str, message: str, image_url: str) -> dict:
    """在 Facebook 粉絲專頁發佈帶圖片的貼文。"""
    url = f"{GRAPH_API_BASE}/{page_id}/photos"
    params = {
        "message": message,
        "url": image_url,
        "access_token": access_token,
    }

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_page_info(page_id: str, access_token: str) -> dict:
    """取得粉絲專頁基本資訊（用於驗證 token 是否有效）。"""
    url = f"{GRAPH_API_BASE}/{page_id}"
    params = {
        "fields": "id,name,fan_count",
        "access_token": access_token,
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
