import httpx


class Telegram:
    def __init__(self, settings): self.s = settings
    def send(self, text):
        if not self.s.telegram_bot_token or not self.s.telegram_chat_id: return {"sent": False, "reason": "not configured"}
        url=f"https://api.telegram.org/bot{self.s.telegram_bot_token}/sendMessage"
        for _ in range(self.s.telegram_retries):
            try:
                r=httpx.post(url,data={"chat_id":self.s.telegram_chat_id,"text":text},timeout=20)
                if r.is_success: return {"sent": True}
            except httpx.HTTPError: pass
        return {"sent": False, "reason": "delivery failed"}
