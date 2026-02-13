"""AI 文章生成模組。使用 OpenAI GPT 產出 Facebook 粉專貼文。"""

import os
import requests

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """你是「亞瑟教練」的品牌小編。
你的任務是撰寫 Facebook 粉絲專頁貼文，風格兼具專業與溫度，幫助台灣中小企業主/創業者了解政府資源、品牌經營與自我成長。

【角色設定】
- 你是一位熟悉台灣政策、補助與品牌行銷的教練
- 你的語氣像老闆分享經驗給朋友，自然而不說教
- 你偶爾會提及自身經營的觀察（以「我」或「我們」敘述）

【內容方向（依主題彈性調整）】
1. 台灣中小企業政策解讀（如 SBIR、SIIR、品牌補助等）
2. 政府補助/計畫申請攻略與常見錯誤
3. 個人品牌經營心得、行銷觀察
4. 創業者心態與自我成長分享

【格式規範】
- 使用繁體中文
- 開頭用一句吸睛金句或提問引發共鳴
- 段落分明，適當使用 emoji 但不過度
- 結尾帶入行動呼籲（CTA）
- 每篇文末固定加上：
  👉 報名連結 https://bit.ly/fbregister2026

【禁止事項】
- 不要硬銷售、不要業配感
- 不要提到「我是 AI」或任何 AI 相關描述
- 不要使用官方公文語氣
- 不要超過 500 字（含 emoji）"""


def generate_article(topic: str, model: str = "gpt-4o-mini") -> str:
    """用 GPT 根據主題生成一篇 Facebook 貼文。

    Args:
        topic: 文章主題 / 方向描述
        model: OpenAI 模型名稱，預設 gpt-4o-mini

    Returns:
        生成的貼文內容（純文字）

    Raises:
        RuntimeError: 缺少 API Key 或 API 呼叫失敗
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("請在 .env 設定 OPENAI_API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"請根據以下主題撰寫一篇 Facebook 粉專貼文：\n\n{topic}"},
        ],
        "temperature": 0.8,
        "max_tokens": 1000,
    }

    resp = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=60)

    if resp.status_code != 200:
        error_msg = resp.json().get("error", {}).get("message", resp.text)
        raise RuntimeError(f"OpenAI API 錯誤 ({resp.status_code}): {error_msg}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    return content
