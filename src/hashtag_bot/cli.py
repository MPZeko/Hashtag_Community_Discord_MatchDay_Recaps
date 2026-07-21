from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from hashtag_bot.config import STATE_PATH, TEAMS, get_webhook_url
from hashtag_bot.discord_client import DiscordError, post_embed
from hashtag_bot.fwp_source import (
    SourceError,
    fetch_text,
    make_session,
    parse_fixtures,
    parse_goal_events,
    parse_table,
)
from hashtag_bot.models import Match, TableSnapshot, TeamConfig
from hashtag_bot.recap import build_embed
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


def fetch_team(session, team: TeamConfig) -> tuple[list[Match], list[Match], TableSnapshot]:
    log.info("Checking %s", team.display_name)
    fixtures = parse_fixtures(fetch_text(session, team.fixtures_url), team)
    completed = [match for match in fixtures if match.is_finished]
    log.info(
        "Parsed %s fixtures for %s; %s completed",
        len(fixtures),
        team.key,
        len(completed),
    )
    table = parse_table(fetch_text(session, team.overview_url), team)
    return fixtures, completed, table


def initialize_state(session, state: dict) -> tuple[int, bool]:
    failures = 0
    for team in TEAMS.values():
        try:
            _, completed, table = fetch_team(session, team)
        except Exception as exc:
            failures += 1
            log.exception("Source failure for %s: %s", team.key, exc)
            continue
        for match in completed:
            state.setdefault("matches", {})[match.key] = {
                "score": match.score,
                "posted_at": None,
                "discord_message_id": None,
                "initialized_at": datetime.now(UTC).isoformat(),
            }
        put_table(state, team.key, table)
    if failures == len(TEAMS):
        return 1, False
    state["initialized"] = True
    atomic_write_state(STATE_PATH, state)
    log.info("Bot initialized; historical results recorded without posting")
    log.info("State changed: true")
    return 0, True


def check() -> int:
    session = make_session()
    state = load_state(STATE_PATH)
    if not state.get("initialized"):
        return initialize_state(session, state)[0]

    webhook = get_webhook_url(True)
    failures = 0
    posts = 0
    for team in TEAMS.values():
        try:
            fixtures, completed, table = fetch_team(session, team)
        except Exception as exc:
            failures += 1
            log.exception("Source failure for %s: %s", team.key, exc)
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
            goals = parse_goal_events(fetch_text(session, match.detail_url)) if match.detail_url else []
            embed = build_embed(match, goals, fixtures, table, previous_table, old_score)
            message_id = post_embed(webhook, embed)
            log.info("Discord message posted for %s: %s", match.key, message_id)
            record_match(state, match, message_id)
            put_table(state, team.key, table)
            atomic_write_state(STATE_PATH, state)
            posts += 1
    if failures == len(TEAMS):
        return 1
    if not posts:
        log.info("No new result found; Discord not contacted")
    log.info("State changed: %s", bool(posts))
    return 0


def dry_run() -> int:
    session = make_session()
    embeds = []
    for team in TEAMS.values():
        fixtures, completed, table = fetch_team(session, team)
        for match in completed[-2:]:
            embeds.append(build_embed(match, [], fixtures, table, None))
    print(json.dumps(embeds, indent=2, ensure_ascii=False))
    return 0


def test_webhook() -> int:
    webhook = get_webhook_url(True)
    post_embed(
        webhook,
        {
            "title": "Hashtag United Match Bot Connected",
            "description": "The Discord webhook is configured correctly. #UPTHETAGS",
            "color": 0xF1C232,
            "footer": {"text": "Source: Football Web Pages • #UPTHETAGS"},
        },
    )
    log.info("Webhook test message posted")
    return 0


def post_latest(team_value: str) -> int:
    webhook = get_webhook_url(True)
    session = make_session()
    state = load_state(STATE_PATH)
    count = 0
    for team in selected_teams(team_value):
        fixtures, completed, table = fetch_team(session, team)
        if not completed:
            continue
        match = sorted(completed, key=lambda item: item.date)[-1]
        goals = parse_goal_events(fetch_text(session, match.detail_url)) if match.detail_url else []
        previous_table = table_from_state(state.get("tables", {}).get(team.key))
        message_id = post_embed(webhook, build_embed(match, goals, fixtures, table, previous_table))
        record_match(state, match, message_id)
        put_table(state, team.key, table)
        count += 1
    if count:
        atomic_write_state(STATE_PATH, state)
    return 0 if count else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("check")
    subparsers.add_parser("dry-run")
    subparsers.add_parser("test-webhook")
    post_latest_parser = subparsers.add_parser("post-latest")
    post_latest_parser.add_argument("--team", choices=["all", "men", "women"], default="all")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            return check()
        if args.cmd == "dry-run":
            return dry_run()
        if args.cmd == "test-webhook":
            return test_webhook()
        return post_latest(args.team)
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
