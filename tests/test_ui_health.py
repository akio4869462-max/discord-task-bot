import asyncio
import os
from datetime import date

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')

import google_health_logic as ghl
import horse_logic
import main
import steps_logic
import ui_common
import ui_training

TODAY = date(2026, 10, 19)
YESTERDAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """⭕ 馬のデータ（厩舎と旧RPG）・歩数・認証情報を全部差し替える。漏れると実データを巻き込む。"""
    monkeypatch.setattr(horse_logic, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(horse_logic, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))
    monkeypatch.setattr(steps_logic, 'STEPS_DATA_FILE', str(tmp_path / 'steps_data.json'))
    monkeypatch.setattr(ghl, 'TOKEN_FILE', str(tmp_path / 'google_health_token.json'))


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


def fake_sync_day(steps, credit):
    def _sync(day):
        return {'day': day, 'steps': steps, 'credit': credit, 'message': '👟 記録しました'}
    return _sync


# ====================================================
# 昨日ぶんの歩数は、連続記録を動かさない
# ====================================================

def test_walking_for_yesterday_does_not_touch_the_streak():
    """⭕ 連続記録は「今日やったか」の指標。翌朝に昨日ぶんを取り込んだだけで、今日の記録に
       してはいけない（last_active_date を過去へ巻き戻してもいけない）。"""
    before = horse_logic.load_stable(TODAY)

    ui_common.process_walking(6000, today=YESTERDAY, update_streak=False)

    after = horse_logic.load_stable(TODAY)
    assert after['current']['growth']['stamina'] > 0                      # 能力には入る
    assert after.get('current_streak') == before.get('current_streak')
    assert after.get('last_active_date') == before.get('last_active_date')


def test_walking_for_today_does_move_the_streak():
    ui_common.process_walking(6000, today=TODAY, update_streak=True)
    assert horse_logic.load_stable(TODAY)['last_active_date'] == TODAY.strftime('%Y-%m-%d')


# ====================================================
# 取り込み（Discordへの投稿）
# ====================================================

def test_import_trains_the_horse_with_the_newly_countable_steps(monkeypatch):
    monkeypatch.setattr(ghl, 'sync_day', fake_sync_day(7000, 7000))

    result = asyncio.run(ui_training.import_google_health_steps(YESTERDAY, is_today=False))

    assert result['steps'] == 7000
    assert 'スタミナ' in result['detail']
    assert horse_logic.load_stable(TODAY)['current']['growth']['stamina'] > 0


def test_import_returns_none_when_google_has_no_data_yet(monkeypatch):
    monkeypatch.setattr(ghl, 'sync_day', lambda day: None)
    assert asyncio.run(ui_training.import_google_health_steps(TODAY, is_today=True)) is None


def test_posting_announces_the_import_with_the_day_label(monkeypatch):
    monkeypatch.setattr(ghl, 'sync_day', fake_sync_day(7000, 7000))
    channel = FakeChannel()

    asyncio.run(ui_training.post_google_health_steps(channel, YESTERDAY, is_today=False))

    assert len(channel.sent) >= 1
    assert '7,000歩' in channel.sent[0]
    assert '昨日' in channel.sent[0]


def test_posting_says_nothing_when_there_is_nothing_new_to_count(monkeypatch):
    """⭕ 毎朝・毎晩の自動処理。新しく数える歩数が無いのに毎回投稿すると、ただのノイズになる。"""
    monkeypatch.setattr(ghl, 'sync_day', fake_sync_day(7000, 0))
    channel = FakeChannel()

    asyncio.run(ui_training.post_google_health_steps(channel, TODAY, is_today=True))

    assert channel.sent == []


def test_posting_says_nothing_when_google_has_no_data(monkeypatch):
    monkeypatch.setattr(ghl, 'sync_day', lambda day: None)
    channel = FakeChannel()

    asyncio.run(ui_training.post_google_health_steps(channel, TODAY, is_today=True))

    assert channel.sent == []


# ====================================================
# 定期配信への組み込み：失敗がループを止めない
# ====================================================

@pytest.fixture
def alerts(monkeypatch):
    sent = []

    async def fake_alert(message):
        sent.append(message)

    monkeypatch.setattr(main, 'alert', fake_alert)
    return sent


def run_sync(channel=None, configured=True, raises=None, monkeypatch=None):
    calls = []

    async def fake_post(ch, day, is_today):
        calls.append((day, is_today))
        if raises is not None:
            raise raises

    monkeypatch.setattr(main, 'post_google_health_steps', fake_post)
    monkeypatch.setattr(main.google_health_logic, 'is_configured', lambda: configured)
    asyncio.run(main.sync_steps_or_alert(FakeChannel() if channel is None else channel, TODAY, True))
    return calls


def test_unconfigured_integration_is_silently_skipped(monkeypatch, alerts):
    assert run_sync(configured=False, monkeypatch=monkeypatch) == []
    assert alerts == []


def test_configured_integration_runs_and_stays_quiet_on_success(monkeypatch, alerts):
    assert run_sync(monkeypatch=monkeypatch) == [(TODAY, True)]
    assert alerts == []


def test_a_known_failure_becomes_an_alert_with_the_reason(monkeypatch, alerts):
    err = ghl.GoogleHealthError('Googleが 400 を返しました（invalid_grant）。再認証してください', needs_reauth=True)

    run_sync(raises=err, monkeypatch=monkeypatch)

    assert len(alerts) == 1
    assert 'invalid_grant' in alerts[0]


def test_an_unexpected_failure_is_contained_and_alerted(monkeypatch, alerts):
    """⭕ 配信ループは全機能で1つを共有している。ここから例外が漏れると、ニュースも
       トレーニング通知もレース実行も、ループごと止まる。"""
    run_sync(raises=KeyError('boom'), monkeypatch=monkeypatch)       # 例外が外へ出ないこと自体が検査

    assert len(alerts) == 1
    assert 'KeyError' in alerts[0]


def test_no_channel_means_nothing_to_do(monkeypatch, alerts):
    calls = []

    async def fake_post(*args):
        calls.append(args)

    monkeypatch.setattr(main, 'post_google_health_steps', fake_post)
    monkeypatch.setattr(main.google_health_logic, 'is_configured', lambda: True)
    asyncio.run(main.sync_steps_or_alert(None, TODAY, True))

    assert calls == []
