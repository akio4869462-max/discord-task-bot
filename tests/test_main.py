import os
from datetime import date

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')  # main.pyのimport時にclient.run用のTOKEN取得で使われるだけ

import main
import task_logic


# ====================================================
# 環境変数の読み込み（docker-composeの空文字列展開への耐性）
# ====================================================

def test_getenv_int_reads_defined_value(monkeypatch):
    monkeypatch.setenv('SOME_CHANNEL_ID', '12345')
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 12345


def test_getenv_int_falls_back_when_undefined(monkeypatch):
    monkeypatch.delenv('SOME_CHANNEL_ID', raising=False)
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 999


def test_getenv_int_falls_back_when_empty_string(monkeypatch):
    """docker-composeの ${VAR} 展開は、.envにキーが無いと空文字列を渡す。
    ここでクラッシュせずデフォルトへフォールバックできることの回帰テスト
    （本番でint('')によりBotが起動時クラッシュした実際の障害に対応）。"""
    monkeypatch.setenv('SOME_CHANNEL_ID', '')
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 999


@pytest.mark.parametrize('text,expected', [
    ('25', 25),
    ('  25  ', 25),      # 前後の空白は許容
    ('２５', 25),         # 全角数字も受け付ける
    ('0', 0),
    ('-5', -5),          # 符号付きも変換自体は成功する（範囲判定は呼び出し側の責務）
    ('abc', None),
    ('', None),
    ('2.5', None),       # 小数は整数として解釈できない
    ('²', None),         # isdigit()はTrueだがint()できない文字（クラッシュ防止の要）
    (None, None),
])
def test_parse_positive_int(text, expected):
    assert main.parse_positive_int(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('2.5', 2.5),
    ('  2.5  ', 2.5),
    ('10', 10.0),
    ('０.５', 0.5),   # 全角数字も受け付ける
    ('abc', None),
    ('', None),
    (None, None),
])
def test_parse_float(text, expected):
    assert main.parse_float(text) == expected


def make_result(is_level_up=False, new_level=None, event=None, streak=1, new_badges=None):
    """study_logic.add_exp()が返す辞書と同じ形の、テスト用の結果データを組み立てる。"""
    return {
        "is_level_up": is_level_up,
        "new_level": new_level,
        "event": event,
        "earned_exp": 0,
        "streak": streak,
        "new_badges": new_badges or [],
    }


def test_build_event_message_no_event_no_levelup():
    detail, public = main.build_event_message(make_result())
    assert detail == ''
    assert public is None


def test_build_event_message_boss_appear():
    detail, public = main.build_event_message(make_result(event='BOSS_APPEAR'))
    assert 'ボス' in detail
    assert public is not None and 'ボス' in public


def test_build_event_message_boss_damage_is_not_publicly_announced():
    detail, public = main.build_event_message(make_result(event='BOSS_DAMAGE'))
    assert 'ダメージ' in detail
    assert public is None  # 通常ダメージは公開告知の対象外


def test_build_event_message_level_up_and_boss_defeated_combined():
    detail, public = main.build_event_message(make_result(is_level_up=True, new_level=5, event='BOSS_DEFEATED'))
    assert 'Lv.5' in detail
    assert public is not None
    assert 'Lv.5' in public
    assert '撃破' in public


def test_build_event_message_streak_milestone_is_announced():
    detail, public = main.build_event_message(make_result(streak=7))
    assert '7日連続' in detail
    assert public is not None and '7日連続' in public


def test_build_event_message_non_milestone_streak_is_not_announced():
    detail, public = main.build_event_message(make_result(streak=5))
    assert public is None


def test_build_event_message_new_badge_is_announced():
    badge = {"id": "first_boss", "name": "🗡️ 初撃破の証"}
    detail, public = main.build_event_message(make_result(new_badges=[badge]))
    assert '初撃破の証' in detail
    assert public is not None and '初撃破の証' in public


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(task_logic, 'DB_FILE', str(tmp_path / 'todo.json'))


def test_build_deadline_reminders_includes_tasks_within_three_days():
    today = date.today()
    task_logic.add_task('今日締切', 'programming', today.strftime('%Y-%m-%d'), 2)
    task_logic.add_task('来月締切', 'programming', '2099-01-01', 2)

    reminders = main.build_deadline_reminders(today)

    assert len(reminders) == 1
    assert '今日が締切' in reminders[0]
    assert '今日締切' in reminders[0]


def test_build_deadline_reminders_empty_when_no_tasks():
    assert main.build_deadline_reminders(date.today()) == []
