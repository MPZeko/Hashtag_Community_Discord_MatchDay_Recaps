from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

from hashtag_bot.config import STATE_PATH, TEAMS, get_webhook_url
from hashtag_bot.discord_client import post_embed
from hashtag_bot.fwp_source import (
    fetch_text,
    make_session,
    parse_fixtures,
    parse_goal_events,
    parse_table,
)
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

def _teams(value: str): return TEAMS.values() if value == "all" else [TEAMS[value]]

def _fetch_team(session, team):
    log.info("Checking %s", team.display_name)
    fixtures = parse_fixtures(fetch_text(session, team.fixtures_url), team)
    completed = [m for m in fixtures if m.is_finished]
    log.info("Parsed %s fixtures for %s; %s completed", len(fixtures), team.key, len(completed))
    table = parse_table(fetch_text(session, team.overview_url), team)
    return fixtures, completed, table

def check() -> int:
    webhook = get_webhook_url(True); session = make_session(); state = load_state(STATE_PATH); failures = posts = 0
    if not state.get("initialized"):
        for team in TEAMS.values():
            try:
                _, completed, table = _fetch_team(session, team)
                for m in completed: record_match(state, m, None)
                put_table(state, team.key, table)
            except Exception as exc: failures += 1; log.exception("Source failure for %s: %s", team.key, exc)
        if failures == len(TEAMS): return 1
        state["initialized"] = True; atomic_write_state(STATE_PATH, state); log.info("Bot initialized; historical results recorded without posting")
        return 0
    for team in TEAMS.values():
        try: fixtures, completed, table = _fetch_team(session, team)
        except Exception as exc: failures += 1; log.exception("Source failure for %s: %s", team.key, exc); continue
        prev_table = table_from_state(state.get("tables", {}).get(team.key))
        fresh = [m for m in completed if m.date >= date.today() - timedelta(days=7) and known_score(state, m) != m.score]
        log.info("%s new or corrected result(s) for %s", len(fresh), team.key)
        for m in sorted(fresh, key=lambda x: x.date):
            old = known_score(state, m)
            goals = parse_goal_events(fetch_text(session, m.detail_url)) if m.detail_url else []
            msg_id = post_embed(webhook, build_embed(m, goals, fixtures, table, prev_table, old))
            log.info("Discord message posted for %s: %s", m.key, msg_id)
            record_match(state, m, msg_id); put_table(state, team.key, table)
            atomic_write_state(STATE_PATH, state); posts += 1
    if failures == len(TEAMS): return 1
    if not posts: log.info("No new result found; Discord not contacted")
    log.info("State changed: %s", bool(posts))
    return 0

def dry_run() -> int:
    session = make_session(); embeds = []
    for team in TEAMS.values():
        fixtures, completed, table = _fetch_team(session, team)
        for m in completed[-2:]: embeds.append(build_embed(m, [], fixtures, table, None))
    print(json.dumps(embeds, indent=2, ensure_ascii=False)); return 0

def test_webhook() -> int:
    webhook = get_webhook_url(True)
    post_embed(webhook, {"title":"Hashtag United Match Bot Connected","description":"The Discord webhook is configured correctly. #UPTHETAGS","color":0xF1C232,"footer":{"text":"Source: Football Web Pages • #UPTHETAGS"}})
    log.info("Webhook test message posted"); return 0

def post_latest(team_value: str) -> int:
    webhook = get_webhook_url(True); session = make_session(); state = load_state(STATE_PATH); count = 0
    for team in _teams(team_value):
        fixtures, completed, table = _fetch_team(session, team)
        if not completed: continue
        m = sorted(completed, key=lambda x: x.date)[-1]
        goals = parse_goal_events(fetch_text(session, m.detail_url)) if m.detail_url else []
        msg_id = post_embed(webhook, build_embed(m, goals, fixtures, table, table_from_state(state.get("tables", {}).get(team.key))))
        record_match(state, m, msg_id); put_table(state, team.key, table); count += 1
    if count: atomic_write_state(STATE_PATH, state)
    return 0 if count else 1

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check"); sub.add_parser("dry-run"); sub.add_parser("test-webhook")
    pl = sub.add_parser("post-latest"); pl.add_argument("--team", choices=["all","men","women"], default="all")
    args = p.parse_args(argv)
    try:
        return {"check": check, "dry-run": dry_run, "test-webhook": test_webhook}.get(args.cmd, lambda: post_latest(args.team))()
    except Exception as exc:
        log.error("%s", exc); return 1

if __name__ == "__main__": sys.exit(main())
