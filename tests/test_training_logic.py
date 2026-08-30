import os
from datetime import datetime, timedelta

import pytest

import training_logic as tl


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/training_data.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(tl, 'TRAINING_DATA_FILE', str(tmp_path / 'training_data.json'))


# 曜日の基準点として、確実に平日(火曜)である日時を使う
TUESDAY = datetime(2026, 6, 2, 10, 0, tzinfo=tl.JST)  # 2026-06-02は火曜日
assert TUESDAY.weekday() == 1


def test_get_today_menu_matches_weekly_schedule():
    assert '上半身①' in tl.get_today_menu(weekday=0)
    assert '下半身' in tl.get_today_menu(weekday=1)
    assert 'サーキット' in tl.get_today_menu(weekday=2)
    assert '上半身②' in tl.get_today_menu(weekday=3)
    assert '下半身' in tl.get_today_menu(weekday=4)
    assert 'サーキット' in tl.get_today_menu(weekday=5)


def test_get_today_menu_rest_day():
    result = tl.get_today_menu(weekday=6)
    assert '休養日' in result


def test_get_today_menu_includes_ab_finisher_on_training_day():
    result = tl.get_today_menu(weekday=0)
    assert 'プランク' in result
    assert 'レッグレイズ' in result


def test_log_session_on_rest_day_does_not_record():
    sunday = datetime(2026, 6, 7, 10, 0, tzinfo=tl.JST)
    assert sunday.weekday() == 6

    msg, streak = tl.log_session(now=sunday)

    assert '休養日' in msg
    assert streak is None
    assert tl.load_training_data()['sessions'] == []


def test_log_session_records_and_starts_streak_at_1():
    msg, streak = tl.log_session(now=TUESDAY)

    assert '記録しました' in msg
    assert streak == 1
    data = tl.load_training_data()
    assert len(data['sessions']) == 1
    assert data['sessions'][0]['day_type'] == '下半身・臀部'


def test_log_session_twice_on_same_day_does_not_duplicate():
    tl.log_session(now=TUESDAY)
    msg, streak = tl.log_session(now=TUESDAY)

    assert '既に完了' in msg
    assert streak is None
    assert len(tl.load_training_data()['sessions']) == 1


def test_streak_continues_across_planned_rest_day():
    # 前週の土曜にトレーニング済みの状態を用意
    this_monday = TUESDAY - timedelta(days=1)
    last_saturday = this_monday - timedelta(days=2)
    data = tl.load_training_data()
    data['last_active_date'] = last_saturday.strftime('%Y-%m-%d')
    data['current_streak'] = 5
    tl.save_training_data(data)

    # 日曜(休養日)を挟んで月曜にトレーニングしても、連続記録が途切れない
    _, streak = tl.log_session(now=this_monday)
    assert streak == 6


def test_streak_resets_when_a_real_gap_occurs():
    data = tl.load_training_data()
    data['last_active_date'] = (TUESDAY - timedelta(days=3)).strftime('%Y-%m-%d')
    data['current_streak'] = 5
    tl.save_training_data(data)

    _, streak = tl.log_session(now=TUESDAY)
    assert streak == 1


def test_log_measurement_records_value():
    msg = tl.log_measurement(60.0, 80.0, now=TUESDAY)
    assert '60.0kg' in msg
    assert '80.0cm' in msg

    data = tl.load_training_data()
    assert len(data['measurements']) == 1


def test_log_measurement_shows_diff_from_previous():
    tl.log_measurement(60.0, 80.0, now=TUESDAY)
    msg = tl.log_measurement(59.0, 78.5, now=TUESDAY + timedelta(days=7))

    assert '-1.0kg' in msg
    assert '-1.5cm' in msg


def test_get_measurement_history_when_empty():
    assert 'まだ記録がありません' in tl.get_measurement_history()


def test_get_measurement_history_lists_records():
    tl.log_measurement(60.0, 80.0, now=TUESDAY)
    result = tl.get_measurement_history()
    assert '60.0kg' in result
    assert '80.0cm' in result


def test_weekly_training_rate_excludes_sunday_from_scheduled_days():
    today = TUESDAY.date()  # 火曜基準で直近7日間 = 前週水〜今週火（日曜が1日含まれる）
    completed, scheduled = tl.get_weekly_training_rate(today=today)
    assert scheduled == 6  # 7日間のうち日曜1日を除いた6日
    assert completed == 0


def test_weekly_training_rate_counts_completed_sessions():
    tl.log_session(now=TUESDAY)
    completed, scheduled = tl.get_weekly_training_rate(today=TUESDAY.date())
    assert completed == 1


def test_get_today_menu_image_paths_returns_empty_on_rest_day():
    assert tl.get_today_menu_image_paths(weekday=6) == []


def test_get_today_menu_image_paths_returns_existing_files_for_training_day():
    paths = tl.get_today_menu_image_paths(weekday=0)
    assert len(paths) == 3  # upper1は3枚に分割済み
    assert all(os.path.exists(p) for p in paths)


def test_get_today_menu_image_paths_excludes_missing_files(monkeypatch):
    monkeypatch.setitem(tl.WEEKLY_MENU[0], 'images', ['assets/training/does_not_exist.png'])
    assert tl.get_today_menu_image_paths(weekday=0) == []

def test_is_rest_day():
    assert tl.is_rest_day(weekday=6) is True
    for wd in range(6):
        assert tl.is_rest_day(weekday=wd) is False
