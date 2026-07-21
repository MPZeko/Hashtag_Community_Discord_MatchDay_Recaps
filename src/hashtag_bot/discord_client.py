from __future__ import annotations

import requests

from hashtag_bot.config import TIMEOUT, USER_AGENT


class DiscordError(RuntimeError):
    pass

def payload_for(embed: dict) -> dict:
    return {"username": "Hashtag United Match Centre", "allowed_mentions": {"parse": []}, "embeds": [embed]}

def post_embed(webhook_url: str, embed: dict) -> str | None:
    try:
        r = requests.post(webhook_url, params={"wait": "true"}, json=payload_for(embed), headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise DiscordError(f"Discord webhook request failed: {exc.__class__.__name__}") from exc
    if not 200 <= r.status_code < 300:
        raise DiscordError(f"Discord webhook returned HTTP {r.status_code}")
    try: return r.json().get("id")
    except ValueError: return None
