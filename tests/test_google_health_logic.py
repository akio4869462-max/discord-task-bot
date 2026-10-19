import io
import json
import urllib.error
from datetime import date

import pytest

import google_health_logic as ghl
import steps_logic

DAY = date(2026, 10, 19)

# テスト用の、秘密情報に見立てた文字列。どのエラーメッセージにも漏れてはいけない
CLIENT_SECRET = 'TEST-CLIENT-SECRET-xyz'
REFRESH_TOKEN = 'TEST-REFRESH-TOKEN-abc'
ACCESS_TOKEN = 'TEST-ACCESS-TOKEN-123'
SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN)


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """⭕ このモジュールと、流し込み先（steps_logic）の保存先を両方差し替える。"""
    monkeypatch.setattr(ghl, 'TOKEN_FILE', str(tmp_path / 'google_health_token.json'))
    monkeypatch.setattr(steps_logic, 'STEPS_DATA_FILE', str(tmp_path / 'steps_data.json'))


def write_token(**overrides):
    data = {'client_id': 'cid', 'client_secret': CLIENT_SECRET, 'refresh_token': REFRESH_TOKEN}
    data.update(overrides)
    with open(ghl.TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def rollup(count):
    return {'rollupDataPoints': [{'steps': {'countSum': str(count)}}]}


# ====================================================
# 認証情報
# ====================================================

def test_not_configured_without_a_token_file():
    assert ghl.load_credentials() is None
    assert ghl.is_configured() is False


def test_configured_with_all_three_values():
    write_token()
    assert ghl.is_configured() is True
    assert ghl.load_credentials()['refresh_token'] == REFRESH_TOKEN


@pytest.mark.parametrize('missing', ['client_id', 'client_secret', 'refresh_token'])
def test_not_configured_when_a_value_is_missing_or_empty(missing):
    write_token(**{missing: ''})
    assert ghl.is_configured() is False


def test_a_corrupted_token_file_means_not_configured_not_a_crash():
    with open(ghl.TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write('{ broken')
    assert ghl.is_configured() is False


# ====================================================
# 応答の読み取り
# ====================================================

def test_parse_daily_steps_reads_the_int64_string():
    assert ghl.parse_daily_steps(rollup(3822)) == 3822


def test_zero_steps_is_a_real_value_not_missing():
    """⭕ 0歩と「データ無し」は別物。"""
    assert ghl.parse_daily_steps(rollup(0)) == 0


@pytest.mark.parametrize('response', [
    {},
    {'rollupDataPoints': []},                              # 端末が未同期などで、その日のデータが無い
    {'rollupDataPoints': [{}]},
    {'rollupDataPoints': [{'steps': {}}]},
    {'rollupDataPoints': [{'steps': {'countSum': 'abc'}}]},
    'not a dict',
    None,
])
def test_parse_daily_steps_returns_none_when_there_is_no_data(response):
    assert ghl.parse_daily_steps(response) is None


# ====================================================
# 取得（通信は差し替える）
# ====================================================

class FakeGoogle:
    """_request_json の代わり。呼ばれた内容を記録して、順に応答を返す。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, data=None, json_body=None, headers=None):
        self.calls.append({'url': url, 'data': data, 'json_body': json_body, 'headers': headers or {}})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_fetch_refreshes_the_token_then_asks_for_the_days_total(monkeypatch):
    write_token()
    fake = FakeGoogle({'access_token': ACCESS_TOKEN}, rollup(8200))
    monkeypatch.setattr(ghl, '_request_json', fake)

    assert ghl.fetch_daily_steps(DAY) == 8200

    token_call, steps_call = fake.calls
    assert token_call['url'] == ghl.TOKEN_URL
    assert b'grant_type=refresh_token' in token_call['data']
    assert steps_call['url'] == ghl.STEPS_URL
    assert steps_call['headers']['Authorization'] == f'Bearer {ACCESS_TOKEN}'

    body = steps_call['json_body']
    assert body['windowSizeDays'] == 1
    assert body['range']['start']['date'] == {'year': 2026, 'month': 10, 'day': 19}
    assert body['range']['end']['date'] == {'year': 2026, 'month': 10, 'day': 19}
    assert body['range']['start']['time']['hours'] == 0
    assert body['range']['end']['time']['hours'] == 23


def test_fetch_returns_none_when_google_has_no_data_for_the_day(monkeypatch):
    write_token()
    monkeypatch.setattr(ghl, '_request_json', FakeGoogle({'access_token': ACCESS_TOKEN}, {'rollupDataPoints': []}))
    assert ghl.fetch_daily_steps(DAY) is None


def test_fetch_without_credentials_explains_what_is_missing():
    with pytest.raises(ghl.GoogleHealthError) as e:
        ghl.fetch_daily_steps(DAY)
    assert 'google_health_token.json' in str(e.value)


def test_a_response_without_an_access_token_asks_for_reauthentication(monkeypatch):
    write_token()
    monkeypatch.setattr(ghl, '_request_json', FakeGoogle({}))
    with pytest.raises(ghl.GoogleHealthError) as e:
        ghl.fetch_daily_steps(DAY)
    assert e.value.needs_reauth is True


# ====================================================
# エラー（実際のHTTP層まで通して、メッセージに秘密情報が漏れないことを確かめる）
# ====================================================

def http_error(status, body):
    return urllib.error.HTTPError(ghl.TOKEN_URL, status, 'err', {}, io.BytesIO(json.dumps(body).encode()))


def run_failing_refresh(monkeypatch, raised):
    def fake_urlopen(request, timeout=None):
        raise raised
    monkeypatch.setattr(ghl.urllib.request, 'urlopen', fake_urlopen)
    creds = {'client_id': 'cid', 'client_secret': CLIENT_SECRET, 'refresh_token': REFRESH_TOKEN}
    with pytest.raises(ghl.GoogleHealthError) as e:
        ghl.refresh_access_token(creds)
    return e.value


def test_an_expired_refresh_token_asks_for_reauthentication(monkeypatch):
    """⭕ 同意画面が「テスト」状態だと、リフレッシュトークンは7日で切れる。それに気づける文面か。"""
    err = run_failing_refresh(monkeypatch, http_error(400, {'error': 'invalid_grant',
                                                            'error_description': 'Token has been expired or revoked.'}))
    assert err.needs_reauth is True
    assert 'google_health_auth.py' in str(err)
    assert 'invalid_grant' in str(err)


def test_401_asks_for_reauthentication(monkeypatch):
    err = run_failing_refresh(monkeypatch, http_error(401, {'error': {'status': 'UNAUTHENTICATED', 'message': 'x'}}))
    assert err.needs_reauth is True


def test_403_points_at_the_api_setting_not_at_reauthentication(monkeypatch):
    """403は認証切れとは限らない（APIが無効・スコープ不足など）。誤誘導しない。"""
    err = run_failing_refresh(monkeypatch, http_error(403, {'error': {'status': 'PERMISSION_DENIED', 'message': 'x'}}))
    assert err.needs_reauth is False
    assert 'Google Health API' in str(err)
    assert 'google_health_auth.py' not in str(err)


def test_a_server_error_has_no_misleading_hint(monkeypatch):
    err = run_failing_refresh(monkeypatch, http_error(500, {'error': {'status': 'INTERNAL', 'message': 'x'}}))
    assert err.needs_reauth is False
    assert '500' in str(err)


@pytest.mark.parametrize('raised', [
    urllib.error.URLError('dns failure'),
    TimeoutError('timed out'),
    ConnectionResetError('reset'),
])
def test_network_failures_become_a_readable_error(monkeypatch, raised):
    err = run_failing_refresh(monkeypatch, raised)
    assert '接続できませんでした' in str(err)
    assert err.needs_reauth is False


@pytest.mark.parametrize('raised', [
    http_error(400, {'error': 'invalid_grant', 'error_description': 'expired'}),
    http_error(403, {'error': {'status': 'PERMISSION_DENIED', 'message': 'denied'}}),
    urllib.error.URLError('dns failure'),
])
def test_error_messages_never_contain_secrets(monkeypatch, raised):
    """⭕ エラーはそのままDiscordのアラートに載る。トークン類が1つでも混ざってはいけない。"""
    err = run_failing_refresh(monkeypatch, raised)
    for secret in SECRETS:
        assert secret not in str(err)


def test_non_json_error_body_does_not_crash_the_error_path(monkeypatch):
    raised = urllib.error.HTTPError(ghl.TOKEN_URL, 502, 'bad gateway', {}, io.BytesIO(b'<html>oops</html>'))
    err = run_failing_refresh(monkeypatch, raised)
    assert '502' in str(err)


# ====================================================
# 歩数の記録への流し込み
# ====================================================

def test_sync_day_records_the_steps_and_returns_what_is_newly_countable(monkeypatch):
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: 8200)

    result = ghl.sync_day(DAY)

    assert result['steps'] == 8200
    assert result['credit'] == 8200
    saved = steps_logic.load_steps_data()['days']['2026-10-19']
    assert saved['steps'] == 8200
    assert saved['source'] == 'google_health'


def test_sync_day_with_no_data_records_nothing(monkeypatch):
    """⭕ データが無い日を0歩として記録しない（端末が未同期のだけかもしれない）。"""
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: None)

    assert ghl.sync_day(DAY) is None
    assert steps_logic.load_steps_data()['days'] == {}


def test_syncing_the_same_total_twice_credits_only_once(monkeypatch):
    """20:00の途中経過と、翌朝8:00の確定値が同じでも、二重に数えない。"""
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: 8200)
    ghl.sync_day(DAY)
    assert ghl.sync_day(DAY)['credit'] == 0


def test_the_morning_final_count_only_adds_what_the_evening_missed(monkeypatch):
    totals = iter([6000, 9500])
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: next(totals))

    assert ghl.sync_day(DAY)['credit'] == 6000       # 20:00の途中経過
    assert ghl.sync_day(DAY)['credit'] == 3500       # 翌朝8:00の確定値。増えた分だけ


def test_a_manual_entry_and_the_import_do_not_double_count(monkeypatch):
    """手入力した日にあとから自動取り込みが来ても、重複して数えない。"""
    steps_logic.log_steps(5000, now=ghl.datetime.combine(DAY, ghl.time(12, 0), tzinfo=ghl.JST))
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: 8000)

    assert ghl.sync_day(DAY)['credit'] == 3000


def test_sync_day_is_recorded_under_the_days_own_date_not_today(monkeypatch):
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: 4000)
    ghl.sync_day(date(2025, 1, 5))
    assert '2025-01-05' in steps_logic.load_steps_data()['days']


def test_an_implausible_value_from_google_is_not_credited(monkeypatch):
    monkeypatch.setattr(ghl, 'fetch_daily_steps', lambda day: 5_000_000)

    result = ghl.sync_day(DAY)

    assert result['credit'] == 0
    assert result['message'].startswith('❌')
