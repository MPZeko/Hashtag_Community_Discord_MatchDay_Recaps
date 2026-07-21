from __future__ import annotations

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

MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}

class SourceError(RuntimeError):
    pass

def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.6, status_forcelist=[429,500,502,503,504], allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT})
    return s

def fetch_text(session: requests.Session, url: str) -> str:
    try:
        r = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SourceError(f"Failed to fetch source URL {url}: {exc.__class__.__name__}") from exc
    if not r.ok:
        raise SourceError(f"Failed to fetch source URL {url}: HTTP {r.status_code}")
    return r.text

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
    m = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", soup.get_text(" "))
    if not m:
        today = date.today(); return (today.year if today.month >= 7 else today.year - 1, today.year + 1 if today.month >= 7 else today.year)
    return int(m.group(1)), int(m.group(2))

def parse_date(text: str, years: tuple[int, int]) -> date:
    parts = re.findall(r"\b(\d{1,2}|[A-Za-z]+)\b", text)
    day = next(int(p) for p in parts if p.isdigit())
    mon_token = next(p.lower() for p in parts if p.lower() in MONTHS)
    month = MONTHS[mon_token]
    year = years[0] if month >= 7 else years[1]
    return date(year, month, day)

def _fixture_table(soup: BeautifulSoup) -> tuple[Tag, dict[str, int]]:
    required = {"date", "ha", "opponent", "competition", "koscore"}
    aliases = {"h/a": "ha", "ha": "ha", "ko/score": "koscore", "ko score": "koscore", "ko": "koscore", "score": "koscore"}
    for table in soup.find_all("table"):
        cells = table.find_all("th") or (table.find("tr") or Tag(name="tr")).find_all(["td", "th"])
        headers = []
        for c in cells:
            raw = clean_text(c).lower()
            headers.append(aliases.get(raw, norm(raw)))
        if required.issubset(set(headers)):
            return table, {h: i for i, h in enumerate(headers)}
    raise SourceError("No fixtures table found with Date, H/A, Opponent, Competition and KO/Score headers")

def parse_fixtures(html: str, team: TeamConfig) -> list[Match]:
    soup = BeautifulSoup(html, "lxml"); years = season_years(soup); table, idx = _fixture_table(soup)
    rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
    out: list[Match] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(idx.values()): continue
        dtxt, ha, opp, comp, score = (clean_text(cells[idx[k]]) for k in ["date","ha","opponent","competition","koscore"])
        try: d = parse_date(dtxt, years)
        except Exception: continue
        sm = re.fullmatch(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*", score)
        finished = sm is not None
        hs = int(sm.group(1)) if sm else None; aws = int(sm.group(2)) if sm else None
        home = team.short_name if ha.upper().startswith("H") else opp
        away = opp if ha.upper().startswith("H") else team.short_name
        link = row.find("a", href=True)
        out.append(Match(match_key(team.key,d,ha[:1],opp,comp), team.key, team.display_name, d, ha[:1].upper(), opp, comp, score, finished, home, away, hs, aws, urljoin(team.fixtures_url, link["href"]) if link else None))
    return out

def parse_goal_events(html: str) -> list[GoalEvent]:
    soup = BeautifulSoup(html, "lxml")
    text = clean_text(soup.find("main") or soup.body or soup)
    pattern = re.compile(r"([A-Za-z][A-Za-z .'-]*?|Unknown)\s*\((\d{1,3}(?:\+\d{1,2})?)'\s*([^)]*?)\)")
    events = []
    for scorer, minute, qual in pattern.findall(text):
        base, _, added = minute.partition("+")
        events.append(GoalEvent(minute, int(base)*100 + (int(added) if added else 0), "Goal" if scorer.strip().lower()=="unknown" else scorer.strip(), qual.strip() or None))
    return sorted(events, key=lambda e: e.minute_sort_value)

def parse_table(html: str, team: TeamConfig) -> TableSnapshot:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        heads = [norm(clean_text(h)) for h in table.find_all("th")]
        if not {"p","w","d","l","pts"}.issubset(heads): continue
        pidx = heads.index("p"); ptsidx = heads.index("pts")
        for pos, row in enumerate(table.find_all("tr")[1:], 1):
            cells = row.find_all(["td","th"]); rowtxt = clean_text(row).lower()
            if team.short_name.lower() not in rowtxt and team.display_name.lower() not in rowtxt: continue
            nums = [int(x) for x in re.findall(r"\b\d+\b", clean_text(cells[0]) if cells else "")]
            position = nums[0] if nums else pos
            vals = [clean_text(c) for c in cells]
            try: played = int(re.search(r"\d+", vals[pidx]).group())  # type: ignore[union-attr]
            except Exception: played = None
            try: points = int(re.search(r"\d+", vals[ptsidx]).group())  # type: ignore[union-attr]
            except Exception: points = None
            return TableSnapshot(position, played, points)
    return TableSnapshot(None, None, None)
