from pathlib import Path

from hashtag_bot.config import TEAMS
from hashtag_bot.fwp_source import parse_fixtures, parse_goal_events, parse_table


def fx(n): return Path('tests/fixtures', n).read_text()

def test_fixture_parsing_cases():
    ms = parse_fixtures(fx('men_fixtures.html'), TEAMS['men'])
    assert ms[0].is_finished and ms[0].home_team == 'Hashtag United' and ms[0].score == '2-1' and ms[0].detail_url
    assert ms[1].is_finished and ms[1].away_team == 'Hashtag United' and ms[1].score == '2-3'
    assert not ms[2].is_finished and ms[2].kickoff_or_score == '3pm'
    assert ms[3].date.year == 2026 and ms[4].date.year == 2027 and not ms[4].is_finished
    ws = parse_fixtures(fx('women_fixtures.html'), TEAMS['women'])
    assert ws[0].team_display_name == 'Hashtag United Women' and ws[0].score == '4-0'

def test_goal_events_and_table():
    ev = parse_goal_events(fx('match_details.html'))
    assert [e.minute for e in ev][:3] == ['12','45+4','58']
    assert ev[2].scorer == 'Goal'
    table = parse_table(fx('team_overview.html'), TEAMS['men'])
    assert (table.position, table.played, table.points) == (6,11,18)
