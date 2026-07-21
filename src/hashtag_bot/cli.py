from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from hashtag_bot.config import STATE_PATH, TEAMS, get_webhook_url
from hashtag_bot.discord_client import DiscordError, post_embed
from hashtag_bot.fwp_source import SourceAccessDeniedError, SourceError, create_source
from hashtag_bot.models import Match, TableSnapshot, TeamConfig
from hashtag_bot.recap import GOLD, build_embed, sanitize
from hashtag_bot.state import (
    atomic_write_state,
    known_score,
    load_state,
    put_table,
    record_match,
    table_from_state,
)

log = logging.getLogger("hashtag_bot")


def selected_teams(value: str) -> Iterable[TeamConfig]:
    return TEAMS.values() if value == "all" else [TEAMS[value]]


def log_source_error(team: TeamConfig, exc: Exception) -> None:
    if isinstance(exc, SourceAccessDeniedError):
        log.error(
            "Football Web Pages denied automated HTML access from this runner. "
            "The official FWP API key is not configured."
        )
    log.exception("Source failure for %s: %s", team.key, exc)


def fetch_team(source, team: TeamConfig) -> tuple[list[Match], list[Match], TableSnapshot]:
    log.info("Checking %s", team.display_name)
    fixtures, completed, table = source.fetch_team(team)
    log.info("Parsed %s fixtures for %s; %s completed", len(fixtures), team.key, len(completed))
    return fixtures, completed, table


def initialize_state(source, state: dict) -> int:
    failures: list[str] = []
    for team in TEAMS.values():
        try:
            _, completed, table = fetch_team(source, team)
        except Exception as exc:
            failures.append(team.key)
            log_source_error(team, exc)
            continue
        for match in completed:
            state.setdefault("matches", {})[match.key] = {
                "score": match.score,
                "posted_at": None,
                "discord_message_id": None,
                "initialized_at": datetime.now(UTC).isoformat(),
            }
        put_table(state, team.key, table)
    log.info("Source summary: %s failure(s): %s", len(failures), ", ".join(failures) or "none")
    if len(failures) == len(TEAMS):
        return 1
    state["initialized"] = True
    atomic_write_state(STATE_PATH, state)
    log.info("Bot initialized; historical results recorded without posting")
    log.info("State changed: true")
    return 0


def check() -> int:
    source = create_source()
    state = load_state(STATE_PATH)
    if not state.get("initialized"):
        return initialize_state(source, state)

    webhook = get_webhook_url(True)
    failures: list[str] = []
    posts = 0
    for team in TEAMS.values():
        try:
            fixtures, completed, table = fetch_team(source, team)
        except Exception as exc:
            failures.append(team.key)
            log_source_error(team, exc)
            continue
        previous_table = table_from_state(state.get("tables", {}).get(team.key))
        fresh = [
            match
            for match in completed
            if match.date >= date.today() - timedelta(days=7)
            and known_score(state, match) != match.score
        ]
        log.info("%s new or corrected result(s) for %s", len(fresh), team.key)
        for match in sorted(fresh, key=lambda item: item.date):
            old_score = known_score(state, match)
            goals = source.fetch_goals(match.detail_url)
            message_id = post_embed(webhook, build_embed(match, goals, fixtures, table, previous_table, old_score))
            log.info("Discord message posted for %s: %s", match.key, message_id)
            record_match(state, match, message_id)
            put_table(state, team.key, table)
            atomic_write_state(STATE_PATH, state)
            posts += 1
    log.info("Source summary: %s failure(s): %s", len(failures), ", ".join(failures) or "none")
    if len(failures) == len(TEAMS):
        return 1
    if not posts:
        log.info("No new result found; Discord not contacted")
    log.info("State changed: %s", bool(posts))
    return 0


def dry_run() -> int:
    source = create_source()
    embeds = []
    failures: list[str] = []
    for team in TEAMS.values():
        try:
            fixtures, completed, table = fetch_team(source, team)
        except Exception as exc:
            failures.append(team.key)
            log_source_error(team, exc)
            continue
        for match in completed[-2:]:
            embeds.append(build_embed(match, [], fixtures, table, None))
    log.info("Source summary: %s failure(s): %s", len(failures), ", ".join(failures) or "none")
    if len(failures) == len(TEAMS):
        return 1
    print(json.dumps(embeds, indent=2, ensure_ascii=False))
    return 0


def test_webhook() -> int:
    webhook = get_webhook_url(True)
    post_embed(
        webhook,
        {
            "title": "Hashtag United Match Bot Connected",
            "description": "The Discord webhook is configured correctly. #UPTHETAGS",
            "color": GOLD,
            "footer": {"text": "Source: Football Web Pages • #UPTHETAGS"},
        },
    )
    log.info("Webhook test message posted")
    return 0


def post_latest(team_value: str) -> int:
    webhook = get_webhook_url(True)
    source = create_source()
    state = load_state(STATE_PATH)
    failures: list[str] = []
    count = 0
    for team in selected_teams(team_value):
        try:
            fixtures, completed, table = fetch_team(source, team)
        except Exception as exc:
            failures.append(team.key)
            log_source_error(team, exc)
            continue
        if not completed:
            continue
        match = sorted(completed, key=lambda item: item.date)[-1]
        goals = source.fetch_goals(match.detail_url)
        previous_table = table_from_state(state.get("tables", {}).get(team.key))
        message_id = post_embed(webhook, build_embed(match, goals, fixtures, table, previous_table))
        record_match(state, match, message_id)
        put_table(state, team.key, table)
        count += 1
    log.info("Source summary: %s failure(s): %s", len(failures), ", ".join(failures) or "none")
    if count:
        atomic_write_state(STATE_PATH, state)
        return 0
    return 1 if failures else 0


def manual_embed(args: argparse.Namespace) -> dict:
    home_score = int(args.home_score)
    away_score = int(args.away_score)
    if home_score < 0 or away_score < 0:
        raise ValueError("Scores must be zero or positive integers")
    key_moments = args.key_moment or ["Final score confirmed."]
    talking_points = args.talking_point or []
    if not talking_points:
        talking_points = ["What stood out most from this verified result?"]
    return {
        "title": "FULL TIME | #UPTHETAGS",
        "description": f"**{sanitize(args.home_team)} {home_score}–{away_score} {sanitize(args.away_team)}**",
        "color": GOLD,
        "fields": [
            {"name": "⚽ Key moments", "value": "\n".join(sanitize(item) for item in key_moments), "inline": False},
            {"name": "📊 Competition implications", "value": f"Manual verified recap for {sanitize(args.competition)}. No unverified table implication is claimed.", "inline": False},
            {"name": "📅 Next fixture", "value": sanitize(args.next_fixture), "inline": False},
            {"name": "💬 Community talking points", "value": "\n".join(f"• {sanitize(item)}" for item in talking_points), "inline": False},
        ],
        "footer": {"text": "Source: Manually verified result • #UPTHETAGS"},
    }


def manual_post(args: argparse.Namespace) -> int:
    webhook = get_webhook_url(True)
    message_id = post_embed(webhook, manual_embed(args))
    log.info("Manual Discord recap posted for %s: %s", args.team, message_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("check")
    subparsers.add_parser("dry-run")
    subparsers.add_parser("test-webhook")
    post_latest_parser = subparsers.add_parser("post-latest")
    post_latest_parser.add_argument("--team", choices=["all", "men", "women"], default="all")
    manual = subparsers.add_parser("manual-post")
    manual.add_argument("--team", choices=["men", "women"], required=True)
    manual.add_argument("--home-team", required=True)
    manual.add_argument("--away-team", required=True)
    manual.add_argument("--home-score", type=int, required=True)
    manual.add_argument("--away-score", type=int, required=True)
    manual.add_argument("--competition", required=True)
    manual.add_argument("--next-fixture", required=True)
    manual.add_argument("--key-moment", action="append", default=[])
    manual.add_argument("--talking-point", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            return check()
        if args.cmd == "dry-run":
            return dry_run()
        if args.cmd == "test-webhook":
            return test_webhook()
        if args.cmd == "post-latest":
            return post_latest(args.team)
        return manual_post(args)
    except SourceError as exc:
        log.exception("Failure while fetching Football Web Pages or parsing fixtures: %s", exc)
        return 1
    except DiscordError as exc:
        log.exception("Failure while posting to Discord: %s", exc)
        return 1
    except OSError as exc:
        log.exception("Failure while saving local state: %s", exc)
        return 1
    except Exception as exc:
        log.exception("Unexpected bot failure: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
