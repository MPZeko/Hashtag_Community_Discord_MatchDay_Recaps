from __future__ import annotations

import os
import re
from pathlib import Path

from hashtag_bot.models import TeamConfig

APP_TZ = "Europe/Copenhagen"
USER_AGENT = "HashtagUnitedCommunityBot/1.0 (+Discord shareholder community)"
TIMEOUT: tuple[float, float] = (5.0, 20.0)
STATE_PATH = Path("data/state.json")

TEAMS = {
    "men": TeamConfig(
        key="men",
        display_name="Hashtag United Men",
        short_name="Hashtag United",
        fixtures_url="https://www.footballwebpages.co.uk/hashtag-united/fixtures-results",
        overview_url="https://www.footballwebpages.co.uk/hashtag-united",
    ),
    "women": TeamConfig(
        key="women",
        display_name="Hashtag United Women",
        short_name="Hashtag United Women",
        fixtures_url="https://www.footballwebpages.co.uk/hashtag-united-women/fixtures-results",
        overview_url="https://www.footballwebpages.co.uk/hashtag-united-women",
    ),
}

WEBHOOK_RE = re.compile(r"^https://(discord(?:app)?\.com)/api/webhooks/\d+/[A-Za-z0-9._~-]+$")


def get_webhook_url(required: bool) -> str | None:
    value = os.getenv("DISCORD_WEBHOOK_URL")
    if not value:
        if required:
            raise ValueError("DISCORD_WEBHOOK_URL is required but is not configured.")
        return None
    if not WEBHOOK_RE.match(value):
        raise ValueError("DISCORD_WEBHOOK_URL is not a valid Discord webhook URL.")
    return value
