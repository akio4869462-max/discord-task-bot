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
    """火〜日（月曜以外）は毎日同じ全身サーキットメニュー。"""
    for weekday in range(1, 7):
        assert 'サーキット' in tl.get_today_menu(weekday=weekday)


def test_get_today_menu_rest_day():
    result = tl.get_today_menu(weekday=0)
    assert '休養日' in result


def test_get_today_menu_does_not_duplicate_ab_finisher():
    """メインサーキットに前腕プランクが含まれるため、仕上げ（AB_FINISHER）は廃止した。
    復活すると前腕プランクと内容が重複するため、出てこないことを固定しておく。"""
    result = tl.get_today_menu(weekday=1)
    assert 'プランク' in result
    assert 'レッグレイズ' not in result
    assert '仕上げ' not in result


def test_log_session_on_rest_day_does_not_record():
    monday = datetime(2026, 6, 1, 10, 0, tzinfo=tl.JST)
    assert monday.weekday() == 0

    msg, streak = tl.log_session(now=monday)

    assert '休養日' in msg
    assert streak is None
    assert tl.load_training_data()['sessions'] == []


def test_log_session_records_and_starts_streak_at_1():
    msg, streak = tl.log_session(now=TUESDAY)

    assert '記録しました' in msg
    assert streak == 1
    data = tl.load_training_data()
    assert len(data['sessions']) == 1
    assert data['sessions'][0]['day_type'] == '全身サーキット（脂肪燃焼＆筋力アップ）'


def test_log_session_twice_on_same_day_does_not_duplicate():
    tl.log_session(now=TUESDAY)
    msg, streak = tl.log_session(now=TUESDAY)

    assert '既に完了' in msg
    assert streak is None
    assert len(tl.load_training_data()['sessions']) == 1


def test_streak_continues_across_planned_rest_day():
    # 前日(月曜・休養日)の前の日曜にトレーニング済みの状態を用意
    last_sunday = TUESDAY - timedelta(days=2)
    data = tl.load_training_data()
    data['last_active_date'] = last_sunday.strftime('%Y-%m-%d')
    data['current_streak'] = 5
    tl.save_training_data(data)

    # 月曜(休養日)を挟んで火曜にトレーニングしても、連続記録が途切れない
    _, streak = tl.log_session(now=TUESDAY)
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


@pytest.mark.parametrize('weight_kg,waist_cm', [
    (6.0, 80.0),     # 桁の打ち間違い（60.0のつもり）
    (400.0, 80.0),   # 上限超過
    (60.0, 10.0),    # 桁の打ち間違い（100.0のつもり）
    (60.0, 300.0),   # 上限超過
])
def test_log_measurement_rejects_implausible_values(weight_kg, waist_cm):
    """明らかな桁間違いを防ぐための緩い範囲チェック。他の計測系（typing_logic）と
    同様、記録前に妥当性を検証する（以前はここに一切チェックが無かった）。"""
    msg = tl.log_measurement(weight_kg, waist_cm, now=TUESDAY)
    assert msg.startswith('❌')
    assert tl.load_training_data()['measurements'] == []


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


def test_weekly_training_rate_excludes_monday_from_scheduled_days():
    today = TUESDAY.date()  # 火曜基準で直近7日間 = 前週水〜今週火（月曜が1日含まれる）
    completed, scheduled = tl.get_weekly_training_rate(today=today)
    assert scheduled == 6  # 7日間のうち月曜1日を除いた6日
    assert completed == 0


def test_weekly_training_rate_counts_completed_sessions():
    tl.log_session(now=TUESDAY)
    completed, scheduled = tl.get_weekly_training_rate(today=TUESDAY.date())
    assert completed == 1


def test_get_today_menu_image_paths_returns_empty_on_rest_day():
    assert tl.get_today_menu_image_paths(weekday=0) == []


def test_get_today_menu_image_paths_returns_empty_when_no_images_configured():
    """新メニューは一致する画像がまだ無いため、デフォルトでは空リスト。"""
    assert tl.get_today_menu_image_paths(weekday=1) == []


def test_get_today_menu_image_paths_filters_out_missing_files(tmp_path, monkeypatch):
    existing = tmp_path / 'exists.png'
    existing.write_bytes(b'')
    monkeypatch.setitem(tl.WEEKLY_MENU[1], 'images', [str(existing), str(tmp_path / 'does_not_exist.png')])

    assert tl.get_today_menu_image_paths(weekday=1) == [str(existing)]

def test_is_rest_day():
    assert tl.is_rest_day(weekday=0) is True
    for wd in range(1, 7):
        assert tl.is_rest_day(weekday=wd) is False
