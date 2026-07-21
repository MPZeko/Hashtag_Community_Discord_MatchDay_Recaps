from datetime import date
from unittest.mock import patch

from hashtag_bot import cli
from hashtag_bot.models import Match, TableSnapshot


def test_test_webhook_makes_no_source_request(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/token")
    with (
        patch("hashtag_bot.cli.create_source") as create_source,
        patch("hashtag_bot.cli.post_embed", return_value="1") as post_embed,
    ):
        assert cli.main(["test-webhook"]) == 0
    create_source.assert_not_called()
    post_embed.assert_called_once()


def test_manual_post_makes_no_source_request(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/token")
    with (
        patch("hashtag_bot.cli.create_source") as create_source,
        patch("hashtag_bot.cli.post_embed", return_value="1") as post_embed,
    ):
        assert cli.main([
            "manual-post",
            "--team", "men",
            "--home-team", "Hashtag United",
            "--away-team", "Opponent FC",
            "--home-score", "2",
            "--away-score", "1",
            "--competition", "Friendly",
            "--next-fixture", "Next fixture not confirmed by the source",
            "--key-moment", "Final score confirmed.",
            "--talking-point", "Who stood out?",
        ]) == 0
    create_source.assert_not_called()
    embed = post_embed.call_args.args[1]
    assert embed["title"] == "FULL TIME | #UPTHETAGS"
    assert "allowed_mentions" not in embed


def test_mens_source_failure_does_not_prevent_women(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    seen = []

    class Source:
        def fetch_team(self, team):
            seen.append(team.key)
            if team.key == "men":
                raise RuntimeError("men failed")
            match = Match(
                "women-key", team.key, team.display_name, date.today(), "H", "Opp", "League",
                "1-0", True, team.short_name, "Opp", 1, 0, None,
            )
            return [match], [match], TableSnapshot(None, None, None)

    monkeypatch.setattr(cli, "create_source", lambda: Source())
    assert cli.main(["check"]) == 0
    assert seen == ["men", "women"]
