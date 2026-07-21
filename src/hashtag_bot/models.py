from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TeamConfig:
    key: str
    display_name: str
    short_name: str
    fixtures_url: str
    overview_url: str


@dataclass(frozen=True)
class Match:
    key: str
    team_key: str
    team_display_name: str
    date: date
    home_away: str
    opponent: str
    competition: str
    kickoff_or_score: str
    is_finished: bool
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    detail_url: str | None

    @property
    def score(self) -> str:
        if self.home_score is None or self.away_score is None:
            return ""
        return f"{self.home_score}-{self.away_score}"

    def team_score(self) -> int | None:
        if self.home_score is None or self.away_score is None:
            return None
        return self.home_score if self.home_away.upper() == "H" else self.away_score

    def opponent_score(self) -> int | None:
        if self.home_score is None or self.away_score is None:
            return None
        return self.away_score if self.home_away.upper() == "H" else self.home_score


@dataclass(frozen=True)
class TableSnapshot:
    position: int | None
    played: int | None
    points: int | None

    def is_complete(self) -> bool:
        return self.position is not None and self.played is not None and self.points is not None


@dataclass(frozen=True)
class GoalEvent:
    minute: str
    minute_sort_value: int
    scorer: str
    qualifier: str | None
