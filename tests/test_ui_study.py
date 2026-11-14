import asyncio
import os

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')

import horse_logic
import study_logic
import ui_study
from bot_state import active_focus_timers

USER_ID = 4242


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """⭕ 学習の記録と馬のデータを両方差し替える。タイマーの管理表は共有変数なので毎回空にする。"""
    monkeypatch.setattr(study_logic, 'STUDY_DATA_FILE', str(tmp_path / 'study_data.json'))
    monkeypatch.setattr(horse_logic, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(horse_logic, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))
    active_focus_timers.clear()
    yield
    active_focus_timers.clear()


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append(content)


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))


class FakeInteraction:
    def __init__(self, user_id=USER_ID):
        self.user = type('U', (), {'id': user_id, 'mention': '<@4242>'})()
        self.channel = FakeChannel()
        self.response = FakeResponse()


@pytest.fixture
def instant_sleep(monkeypatch):
    async def fake_sleep(_):
        return None
    monkeypatch.setattr(ui_study.asyncio, 'sleep', fake_sleep)


def growth_of_wit():
    return horse_logic.load_stable()['current']['growth'].get('wit', 0)


# ====================================================
# タイマー本体
# ====================================================

def test_when_the_timer_ends_the_session_is_recorded_and_announced(instant_sleep):
    channel = FakeChannel()

    async def scenario():
        active_focus_timers[USER_ID] = asyncio.current_task()
        await ui_study.run_study_timer(channel, USER_ID, '<@4242>', '設計の本')

    asyncio.run(scenario())

    assert '<@4242>' in channel.sent[0]
    assert '25分経過' in channel.sent[0]
    assert '設計の本' in channel.sent[0]
    assert study_logic.load_study_data()['sessions'][0]['minutes'] == 25
    assert study_logic.load_study_data()['sessions'][0]['topic'] == '設計の本'
    assert USER_ID not in active_focus_timers


def test_the_session_also_trains_the_horse_by_time(instant_sleep):
    """25分ぶんの学習が、賢さの調教に入る（開発の集中タイマーと同じ扱い）。"""
    before = growth_of_wit()

    async def scenario():
        await ui_study.run_study_timer(FakeChannel(), USER_ID, '<@4242>', '')

    asyncio.run(scenario())

    assert growth_of_wit() > before


def test_a_horse_side_failure_does_not_lose_the_record_or_the_announcement(instant_sleep, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(ui_study.horse_logic, 'add_growth', boom)
    channel = FakeChannel()

    asyncio.run(ui_study.run_study_timer(channel, USER_ID, '<@4242>', 'AWS'))

    assert len(channel.sent) == 1                                 # 知らせは出る
    assert len(study_logic.load_study_data()['sessions']) == 1    # 記録も残る


def test_a_cancelled_timer_records_and_sends_nothing():
    """キャンセルしたのに「25分経ちました」と出たり、記録されたりしてはいけない。"""
    channel = FakeChannel()

    async def scenario():
        task = asyncio.create_task(ui_study.run_study_timer(channel, USER_ID, '<@4242>', 'x', seconds=60))
        active_focus_timers[USER_ID] = task
        await asyncio.sleep(0)
        task.cancel()
        await task

    asyncio.run(scenario())

    assert channel.sent == []
    assert study_logic.load_study_data()['sessions'] == []
    assert USER_ID not in active_focus_timers


def test_finishing_does_not_remove_a_newer_timer_of_the_same_user(instant_sleep):
    """⭕ キャンセル直後に始めた次のタイマーまで、前のタイマーの後始末で消えてはいけない。"""
    newer = object()

    async def scenario():
        active_focus_timers[USER_ID] = newer
        await ui_study.run_study_timer(FakeChannel(), USER_ID, '<@4242>', '')

    asyncio.run(scenario())

    assert active_focus_timers[USER_ID] is newer


# ====================================================
# 始めるとき
# ====================================================

def test_starting_registers_the_timer_and_tells_the_end_time(instant_sleep):
    interaction = FakeInteraction()

    async def scenario():
        await ui_study.begin_study_timer(interaction, '  設計   の本 ')
        await active_focus_timers[USER_ID]

    asyncio.run(scenario())

    text, kwargs = interaction.response.messages[0]
    assert '25分の学習タイマーを開始しました（設計 の本）' in text     # 内容は整えて表示する
    assert '<t:' in text
    assert kwargs['ephemeral'] is True
    assert interaction.channel.sent                                    # 終わりの知らせが出ている


def test_starting_without_a_topic_has_no_empty_parentheses(instant_sleep):
    interaction = FakeInteraction()

    async def scenario():
        await ui_study.begin_study_timer(interaction, '')
        await active_focus_timers[USER_ID]

    asyncio.run(scenario())

    assert '開始しました。' in interaction.response.messages[0][0]
    assert '（）' not in interaction.response.messages[0][0]


def test_a_second_timer_is_refused_while_one_is_running():
    interaction = FakeInteraction()

    async def scenario():
        active_focus_timers[USER_ID] = asyncio.current_task()
        await ui_study.begin_study_timer(interaction, 'x')

    asyncio.run(scenario())

    assert interaction.response.messages[0][0] == '既にタイマーが動いています。'
    assert study_logic.load_study_data()['sessions'] == []
