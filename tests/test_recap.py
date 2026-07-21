from pathlib import Path

from hashtag_bot.config import TEAMS
from hashtag_bot.fwp_source import parse_fixtures, parse_goal_events
from hashtag_bot.models import TableSnapshot
from hashtag_bot.recap import build_embed, implications, next_fixture_text, ordinal


def fx(n): return Path('tests/fixtures', n).read_text()

def test_recap_rules_and_limits():
    fixtures = parse_fixtures(fx('men_fixtures.html'), TEAMS['men']); m = fixtures[0]
    embed = build_embed(m, parse_goal_events(fx('match_details.html')), fixtures, TableSnapshot(6,11,18), TableSnapshot(8,10,15))
    assert embed['title'] == 'FULL TIME | #UPTHETAGS' and '#UPTHETAGS' in str(embed)
    assert "45+4'" in str(embed) and 'Goal' in str(embed)
    assert 'allowed_mentions' not in embed
    assert len(str(embed)) < 6000
    assert 'Billericay' in next_fixture_text(fixtures, m)
    assert ordinal(11) == '11th' and ordinal(12) == '12th' and ordinal(13) == '13th'
    assert implications(fixtures[2], None, None) == 'Pre-season friendly — no league-table impact.'
    assert 'advances' not in implications(fixtures[1], None, None).lower()
