from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from hashtag_bot.models import Match, TableSnapshot

DEFAULT = {"version": 1, "initialized": False, "matches": {}, "tables": {}}

def load_state(path: Path) -> dict:
    if not path.exists(): return DEFAULT.copy()
    with path.open(encoding="utf-8") as f: return json.load(f)

def atomic_write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def table_from_state(raw: dict | None) -> TableSnapshot | None:
    if not raw: return None
    return TableSnapshot(raw.get("position"), raw.get("played"), raw.get("points"))

def put_table(state: dict, team_key: str, table: TableSnapshot) -> None:
    state.setdefault("tables", {})[team_key] = {"position": table.position, "played": table.played, "points": table.points}

def record_match(state: dict, match: Match, message_id: str | None = None) -> None:
    state.setdefault("matches", {})[match.key] = {"score": match.score, "posted_at": datetime.now(UTC).isoformat(), "discord_message_id": message_id}

def known_score(state: dict, match: Match) -> str | None:
    item = state.get("matches", {}).get(match.key)
    return item.get("score") if item else None
