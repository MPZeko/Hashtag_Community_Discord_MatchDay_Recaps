from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from hashtag_bot.config import APP_TZ
from hashtag_bot.models import GoalEvent, Match, TableSnapshot

GOLD = 0xF1C232

def sanitize(s: str) -> str:
    return re.sub(r"@(?=everyone|here|[!&]?[0-9])", "@\u200b", s).replace("`", "'")[:1000]

def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

def classify(comp: str, table: TableSnapshot | None) -> str:
    c = comp.lower()
    if "friendly" in c: return "friendly"
    if any(x in c for x in ["cup","trophy","vase","shield"]): return "cup"
    if table and table.is_complete(): return "league"
    return "unknown"

def implications(match: Match, current: TableSnapshot | None, previous: TableSnapshot | None) -> str:
    kind = classify(match.competition, current)
    if kind == "friendly": return "Pre-season friendly — no league-table impact."
    if kind == "cup": return "Cup fixture — no league-table impact; the result affects competition progression."
    if kind == "league" and current and current.is_complete():
        cur = ordinal(current.position or 0)
        tail = f"with {current.points} points from {current.played} matches."
        if previous and previous.position and previous.position != current.position:
            return f"The Tags move from {ordinal(previous.position)} to {cur} and now have {tail}"
        if previous and previous.position == current.position:
            return f"The Tags remain {cur} {tail}"
        return f"The Tags are currently {cur} {tail}"
    return "No verified table implication is currently available from the source."

def scoreline(match: Match) -> str:
    return f"{match.home_team} {match.home_score}–{match.away_score} {match.away_team}"

def key_moments(match: Match, goals: list[GoalEvent]) -> str:
    if goals:
        lines = [f"{g.minute}' — {sanitize(g.scorer)}{f' ({sanitize(g.qualifier)})' if g.qualifier else ''}" for g in goals[:6]]
        if len(goals) > 6: lines.append(f"Plus {len(goals)-6} additional goals.")
        return "\n".join(lines)
    ts, os = match.team_score() or 0, match.opponent_score() or 0
    lines = ["Final score confirmed.", f"The Tags scored {ts} and conceded {os}."]
    if os == 0: lines.append("Clean sheet secured.")
    if abs(ts-os) == 1: lines.append("One-goal margin.")
    if ts + os >= 5: lines.append(f"{ts + os} goals in an open contest.")
    return "\n".join(lines[:5])

def next_fixture_text(fixtures: list[Match], completed: Match) -> str:
    candidates = [m for m in fixtures if not m.is_finished and m.date >= completed.date and m.key != completed.key]
    candidates.sort(key=lambda m: m.date)
    if not candidates: return "Next fixture not confirmed by the source"
    n = candidates[0]
    if not (n.opponent and n.competition and n.kickoff_or_score): return "Next fixture not confirmed by the source"
    when = datetime(n.date.year, n.date.month, n.date.day, tzinfo=ZoneInfo(APP_TZ)).strftime("%A, %-d %B %Y")
    return f"{n.home_away} vs {sanitize(n.opponent)} — {sanitize(n.competition)} — {when} at {sanitize(n.kickoff_or_score)}"

def talking_points(match: Match, next_text: str, table: TableSnapshot | None) -> str:
    ts, os = match.team_score() or 0, match.opponent_score() or 0
    if ts > os: qs = ["Who made the biggest difference?", "What was the strongest part of the performance?", "How can the Tags carry this momentum forward?"]
    elif ts == os: qs = ["Was the result a fair reflection of the game?", "What were the main positives?", "What needs improving before the next fixture?"]
    else: qs = ["What should the team take from the performance?", "Which area needs the most attention?", "Who strengthened their case despite the result?"]
    if os == 0: qs[1] = "How important was the clean sheet?"
    elif ts + os >= 5: qs[1] = "What did you make of such a high-scoring contest?"
    elif abs(ts-os) == 1: qs[1] = "Which detail decided the narrow result?"
    if table and table.position: qs[-1] = f"What does {ordinal(table.position)} place mean for the run ahead?"
    elif "not confirmed" not in next_text: qs[-1] = "What will matter most against the next opponent?"
    return "\n".join(f"• {q}" for q in qs[:3])

def build_embed(match: Match, goals: list[GoalEvent], fixtures: list[Match], current_table: TableSnapshot | None, previous_table: TableSnapshot | None, correction_old_score: str | None = None) -> dict:
    nxt = next_fixture_text(fixtures, match)
    title = "RESULT CORRECTION | #UPTHETAGS" if correction_old_score else "FULL TIME | #UPTHETAGS"
    desc = f"**{sanitize(scoreline(match))}**"
    if correction_old_score: desc += f"\nCorrected result: {correction_old_score} → {match.score}"
    embed = {"title": title, "description": desc, "color": GOLD, "fields": [
        {"name": "⚽ Key moments", "value": key_moments(match, goals), "inline": False},
        {"name": "📊 Competition implications", "value": implications(match, current_table, previous_table), "inline": False},
        {"name": "📅 Next fixture", "value": nxt, "inline": False},
        {"name": "💬 Community talking points", "value": talking_points(match, nxt, current_table), "inline": False},
    ], "footer": {"text": "Source: Football Web Pages • #UPTHETAGS"}}
    for f in embed["fields"]: f["value"] = sanitize(f["value"])[:1024]
    return embed
