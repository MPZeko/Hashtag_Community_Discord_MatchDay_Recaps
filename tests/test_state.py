from datetime import date
from unittest.mock import Mock, patch

import pytest
import requests

from hashtag_bot.discord_client import DiscordError, payload_for, post_embed
from hashtag_bot.models import Match
from hashtag_bot.state import atomic_write_state, known_score, load_state, record_match


def match(score: str = "1-0") -> Match:
    home_score, away_score = map(int, score.split("-"))
    return Match(
        "k",
        "men",
        "Hashtag United Men",
        date.today(),
        "H",
        "Opp",
        "League",
        score,
        True,
        "Hashtag United",
        "Opp",
        home_score,
        away_score,
        None,
    )


def test_state_atomic_and_duplicates(tmp_path):
    state_path = tmp_path / "state.json"
    data = {"version": 1, "initialized": False, "matches": {}, "tables": {}}
    atomic_write_state(state_path, data)
    assert load_state(state_path)["version"] == 1
    stored_match = match()
    record_match(data, stored_match, "123")
    assert known_score(data, stored_match) == "1-0"
    corrected = match("2-0")
    assert known_score(data, corrected) != corrected.score


def test_discord_payload_wait_and_sanitized_exception():
    url = "https://discord.com/api/webhooks/123/SECRETtoken"
    ok_response = Mock(status_code=200)
    ok_response.json.return_value = {"id": "42"}
    with patch("requests.post", return_value=ok_response) as mocked_post:
        assert post_embed(url, {"title": "x"}) == "42"
    _, kwargs = mocked_post.call_args
    assert kwargs["params"] == {"wait": "true"}
    assert payload_for({"title": "x"})["allowed_mentions"] == {"parse": []}

    bad_response = Mock(status_code=401)
    with (
        patch("requests.post", return_value=bad_response),
        pytest.raises(DiscordError) as exc_info,
    ):
        post_embed(url, {"title": "x"})
    assert "SECRETtoken" not in str(exc_info.value)
    assert "401" in str(exc_info.value)


def test_discord_request_exception_does_not_expose_webhook_token():
    url = "https://discord.com/api/webhooks/123/SECRETtoken"
    with (
        patch("requests.post", side_effect=requests.RequestException("boom")),
        pytest.raises(DiscordError) as exc_info,
    ):
        post_embed(url, {"title": "x"})
    assert "SECRETtoken" not in str(exc_info.value)
