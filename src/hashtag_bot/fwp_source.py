from __future__ import annotations

import logging
import os
import re
from datetime import date
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from hashtag_bot.config import TIMEOUT, USER_AGENT
from hashtag_bot.models import GoalEvent, Match, TableSnapshot, TeamConfig

log = logging.getLogger("hashtag_bot")

MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}


class SourceError(RuntimeError):
    pass


class SourceAccessDeniedError(SourceError):
    def __init__(self, url: str) -> None:
        super().__init__(
            "Football Web Pages denied automated HTML access from this runner. "
            "The official FWP API key is not configured. "
            f"Source URL: {url}. HTTP 403"
        )


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_text(session: requests.Session, url: str) -> str:
    try:
        response = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SourceError(f"Failed to fetch source URL {url}: {exc.__class__.__name__}") from exc
    if response.status_code == 403:
        raise SourceAccessDeniedError(url)
    if not response.ok:
        raise SourceError(f"Failed to fetch source URL {url}: HTTP {response.status_code}")
    return response.text


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def clean_text(node: Tag | str) -> str:
    text = node.get_text(" ", strip=True) if isinstance(node, Tag) else str(node)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def match_key(team_key: str, d: date, ha: str, opponent: str, comp: str) -> str:
    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    return "|".join([team_key, d.isoformat(), ha.upper(), slug(opponent), slug(comp)])


def season_years(soup: BeautifulSoup) -> tuple[int, int]:
    match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", soup.get_text(" "))
    if not match:
        today = date.today()
        return (
            today.year if today.month >= 7 else today.year - 1,
            today.year + 1 if today.month >= 7 else today.year,
        )
    return int(match.group(1)), int(match.group(2))


def parse_date(text: str, years: tuple[int, int]) -> date:
    parts = re.findall(r"\b(\d{1,2}|[A-Za-z]+)\b", text)
    day = next(int(part) for part in parts if part.isdigit())
    month_token = next(part.lower() for part in parts if part.lower() in MONTHS)
    month = MONTHS[month_token]
    return date(years[0] if month >= 7 else years[1], month, day)


def _fixture_table(soup: BeautifulSoup) -> tuple[Tag, dict[str, int]]:
    required = {"date", "ha", "opponent", "competition", "koscore"}
    aliases = {"h/a": "ha", "ha": "ha", "ko/score": "koscore", "ko score": "koscore", "kickoff/score": "koscore", "ko": "koscore", "score": "koscore"}
    for table in soup.find_all("table"):
        cells = table.find_all("th") or (table.find("tr") or Tag(name="tr")).find_all(["td", "th"])
        headers = [aliases.get(clean_text(cell).lower(), norm(clean_text(cell))) for cell in cells]
        if required.issubset(set(headers)):
            return table, {header: index for index, header in enumerate(headers)}
    raise SourceError("No fixtures table found with Date, H/A, Opponent, Competition and KO/Score headers")


def parse_fixtures(html: str, team: TeamConfig) -> list[Match]:
    soup = BeautifulSoup(html, "lxml")
    years = season_years(soup)
    table, indexes = _fixture_table(soup)
    rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
    fixtures: list[Match] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(indexes.values()):
            continue
        date_text = clean_text(cells[indexes["date"]])
        home_away = clean_text(cells[indexes["ha"]])[:1].upper()
        opponent = clean_text(cells[indexes["opponent"]])
        competition = clean_text(cells[indexes["competition"]])
        ko_score = clean_text(cells[indexes["koscore"]])
        try:
            fixture_date = parse_date(date_text, years)
        except (StopIteration, ValueError):
            continue
        score_match = re.fullmatch(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*", ko_score)
        home_score = int(score_match.group(1)) if score_match else None
        away_score = int(score_match.group(2)) if score_match else None
        home_team = team.short_name if home_away == "H" else opponent
        away_team = opponent if home_away == "H" else team.short_name
        link = row.find("a", href=True)
        fixtures.append(Match(match_key(team.key, fixture_date, home_away, opponent, competition), team.key, team.display_name, fixture_date, home_away, opponent, competition, ko_score, score_match is not None, home_team, away_team, home_score, away_score, urljoin(team.fixtures_url, link["href"]) if link else None))
    return fixtures


def parse_goal_events(html: str) -> list[GoalEvent]:
    soup = BeautifulSoup(html, "lxml")
    text = clean_text(soup.find("main") or soup.body or soup)
    pattern = re.compile(r"([A-Za-z][A-Za-z .'-]*?|Unknown)\s*\((\d{1,3}(?:\+\d{1,2})?)'\s*([^)]*?)\)")
    events = []
    for scorer, minute, qualifier in pattern.findall(text):
        base, _, added = minute.partition("+")
        events.append(GoalEvent(minute, int(base) * 100 + (int(added) if added else 0), "Goal" if scorer.strip().lower() == "unknown" else scorer.strip(), qualifier.strip() or None))
    return sorted(events, key=lambda event: event.minute_sort_value)


def parse_table(html: str, team: TeamConfig) -> TableSnapshot:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        heads = [norm(clean_text(header)) for header in table.find_all("th")]
        if not {"p", "w", "d", "l", "pts"}.issubset(heads):
            continue
        played_index = heads.index("p")
        points_index = heads.index("pts")
        for position, row in enumerate(table.find_all("tr")[1:], 1):
            cells = row.find_all(["td", "th"])
            row_text = clean_text(row).lower()
            if team.short_name.lower() not in row_text and team.display_name.lower() not in row_text:
                continue
            values = [clean_text(cell) for cell in cells]
            position_numbers = [int(value) for value in re.findall(r"\b\d+\b", values[0] if values else "")]
            try:
                played = int(re.search(r"\d+", values[played_index]).group())  # type: ignore[union-attr]
                points = int(re.search(r"\d+", values[points_index]).group())  # type: ignore[union-attr]
            except (IndexError, AttributeError, ValueError):
                return TableSnapshot(None, None, None)
            return TableSnapshot(position_numbers[0] if position_numbers else position, played, points)
    return TableSnapshot(None, None, None)


class FwpHtmlSource:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or make_session()
        if not os.getenv("FWP_API_KEY"):
            log.warning("FWP_API_KEY is not configured; using public HTML source, which may reject cloud runners")

    def fetch_team(self, team: TeamConfig) -> tuple[list[Match], list[Match], TableSnapshot]:
        fixtures = parse_fixtures(fetch_text(self.session, team.fixtures_url), team)
        table = parse_table(fetch_text(self.session, team.overview_url), team)
        return fixtures, [match for match in fixtures if match.is_finished], table

    def fetch_goals(self, detail_url: str | None) -> list[GoalEvent]:
        return parse_goal_events(fetch_text(self.session, detail_url)) if detail_url else []


class FwpApiSource(FwpHtmlSource):
    """Placeholder for the official FWP API, enabled only when endpoint configuration exists."""

    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        super().__init__(session)
        self.api_key = api_key
        self.base_url = os.getenv("FWP_API_BASE_URL")

    def fetch_team(self, team: TeamConfig) -> tuple[list[Match], list[Match], TableSnapshot]:
        if not self.base_url:
            raise SourceError("FWP_API_KEY is configured, but FWP_API_BASE_URL for the official API is not configured")
        return super().fetch_team(team)


def create_source() -> FwpHtmlSource:
    api_key = os.getenv("FWP_API_KEY")
    if api_key:
        return FwpApiSource(api_key)
    return FwpHtmlSource()
