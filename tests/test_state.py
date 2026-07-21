from datetime import date

import responses

from hashtag_bot.discord_client import DiscordError, payload_for, post_embed
from hashtag_bot.models import Match
from hashtag_bot.state import atomic_write_state, known_score, load_state, record_match


def match(score='1-0'):
    h,a = map(int, score.split('-'))
    return Match('k','men','Hashtag United Men',date.today(),'H','Opp','League',score,True,'Hashtag United','Opp',h,a,None)

def test_state_atomic_and_duplicates(tmp_path):
    p = tmp_path/'state.json'; data = {'version':1,'initialized':False,'matches':{},'tables':{}}
    atomic_write_state(p, data); assert load_state(p)['version'] == 1
    m = match(); record_match(data, m, '123')
    assert known_score(data, m) == '1-0'
    corrected = match('2-0'); assert known_score(data, corrected) != corrected.score

@responses.activate
def test_discord_payload_wait_and_sanitized_exception():
    url = 'https://discord.com/api/webhooks/123/SECRETtoken'
    responses.post(url, json={'id':'42'}, status=200)
    assert post_embed(url, {'title':'x'}) == '42'
    call = responses.calls[0].request
    assert 'wait=true' in call.url
    assert payload_for({'title':'x'})['allowed_mentions'] == {'parse': []}
    responses.reset(); responses.post(url, status=401)
    try: post_embed(url, {'title':'x'})
    except DiscordError as e: assert 'SECRETtoken' not in str(e) and '401' in str(e)
    else: raise AssertionError('expected error')
