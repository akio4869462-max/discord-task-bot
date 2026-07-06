import os
from datetime import date

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')  # main.pyのimport時にclient.run用のTOKEN取得で使われるだけ

import main
import task_logic


def test_build_event_message_no_event_no_levelup():
    detail, public = main.build_event_message(False, None, None)
    assert detail == ''
    assert public is None


def test_build_event_message_boss_appear():
    detail, public = main.build_event_message(False, None, 'BOSS_APPEAR')
    assert 'ボス' in detail
    assert public is not None and 'ボス' in public


def test_build_event_message_boss_damage_is_not_publicly_announced():
    detail, public = main.build_event_message(False, None, 'BOSS_DAMAGE')
    assert 'ダメージ' in detail
    assert public is None  # 通常ダメージは公開告知の対象外


def test_build_event_message_level_up_and_boss_defeated_combined():
    detail, public = main.build_event_message(True, 5, 'BOSS_DEFEATED')
    assert 'Lv.5' in detail
    assert public is not None
    assert 'Lv.5' in public
    assert '撃破' in public


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
