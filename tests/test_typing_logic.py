from datetime import date, timedelta

import pytest

import typing_logic as tl


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/typing_data.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(tl, 'TYPING_DATA_FILE', str(tmp_path / 'typing_data.json'))


START = tl.START_DATE


# ====================================================
# 日次メニュー
# ====================================================

def test_daily_menu_shows_current_drill():
    menu = tl.get_daily_menu(today=START)
    assert 'Drill A' in menu
    assert '右小指の単独ドリル' in menu


def test_daily_menu_reflects_drill_progression():
    tl.advance_drill()  # A -> B
    menu = tl.get_daily_menu(today=START)
    assert 'Drill B' in menu


def test_daily_menu_prompts_measurement_when_never_measured():
    """一度も計測していなければ、最後の枠は計測になる"""
    assert '計測' in tl.get_daily_menu(today=START)


def test_daily_menu_shows_drill_d_when_measured_recently():
    tl.log_measurement(20, 90, 50, 5.0, today=START)
    menu = tl.get_daily_menu(today=START + timedelta(days=1))
    assert 'Drill D（実トークン）' in menu


def test_daily_menu_prompts_measurement_after_a_week():
    tl.log_measurement(20, 90, 50, 5.0, today=START)
    menu = tl.get_daily_menu(today=START + timedelta(days=7))
    assert '🎯 **計測**' in menu


def test_daily_menu_rotates_principles():
    """大原則は日替わりで1つずつ提示される"""
    shown = {tl.get_daily_menu(today=START + timedelta(days=i)).split('今日の心得')[1]
             for i in range(len(tl.PRINCIPLES))}
    assert len(shown) == len(tl.PRINCIPLES)


# ====================================================
# ドリル本文
# ====================================================

@pytest.mark.parametrize('drill_id', ['A', 'B', 'C', 'D'])
def test_get_drill_text_wraps_in_code_block(drill_id):
    """コピーしやすいようコードブロックで囲まれている"""
    text = tl.get_drill_text(drill_id)
    assert '```' in text
    assert tl.DRILLS[drill_id]['text'] in text


def test_get_drill_text_accepts_lowercase():
    assert 'Drill A' in tl.get_drill_text('a')


def test_get_drill_text_e_is_keybr_instruction():
    """Drill Eは貼り付け用テキストではなくkeybrの案内"""
    text = tl.get_drill_text('E')
    assert 'keybr.com' in text
    assert '```' not in text


def test_get_drill_text_unknown_returns_message():
    assert '見つかりません' in tl.get_drill_text('Z')


# ====================================================
# ドリル進行
# ====================================================

def test_advance_drill_moves_through_order():
    for expected in ['B', 'C', 'D']:
        tl.advance_drill()
        assert tl.load_typing_data()['current_drill'] == expected


def test_advance_drill_stops_at_last():
    for _ in range(3):
        tl.advance_drill()
    msg = tl.advance_drill()
    assert '既に最終段階' in msg
    assert tl.load_typing_data()['current_drill'] == 'D'


# ====================================================
# 計測記録
# ====================================================

def test_log_measurement_records_and_compares_to_baseline():
    msg = tl.log_measurement(24, 89, 57, 2.5, today=START)
    assert '24 WPM' in msg
    assert 'WPM +7' in msg  # 基準値17からの伸び
    assert len(tl.load_typing_data()['measurements']) == 1


@pytest.mark.parametrize('wpm,acc,cons,afk', [
    (0, 90, 50, 5),      # WPMは1以上
    (20, 101, 50, 5),    # accuracyは100以下
    (20, 90, -1, 5),     # consistencyは0以上
    (20, 90, 50, 101),   # afkは100以下
])
def test_log_measurement_rejects_out_of_range(wpm, acc, cons, afk):
    msg = tl.log_measurement(wpm, acc, cons, afk, today=START)
    assert msg.startswith('❌')
    assert tl.load_typing_data()['measurements'] == []


def test_log_measurement_shows_gap_to_target():
    msg = tl.log_measurement(20, 90, 40, 5.0, today=START)
    assert '2週後の目標まで' in msg
    assert 'WPM あと5' in msg  # 目標25 - 現在20


def test_log_measurement_all_targets_met():
    msg = tl.log_measurement(30, 96, 60, 1.0, today=START)
    assert '全指標クリア' in msg


# ====================================================
# 経過週数・目標ライン
# ====================================================

@pytest.mark.parametrize('days,expected_weeks', [
    (0, 0), (6, 0), (7, 1), (14, 2), (42, 6),
])
def test_weeks_elapsed(days, expected_weeks):
    assert tl.weeks_elapsed(today=START + timedelta(days=days)) == expected_weeks


def test_current_target_advances_with_time():
    week, target = tl.get_current_target(today=START)
    assert week == 2 and target['wpm'] == 25

    week, target = tl.get_current_target(today=START + timedelta(weeks=3))
    assert week == 6 and target['wpm'] == 35


def test_current_target_stays_at_final_after_last_milestone():
    week, target = tl.get_current_target(today=START + timedelta(weeks=20))
    assert week == 6 and target['wpm'] == 35


# ====================================================
# 進捗表示・指の担当表・週間サマリー
# ====================================================

def test_progress_summary_without_measurements():
    summary = tl.get_progress_summary(today=START)
    assert 'まだ計測記録がありません' in summary
    assert 'Drill A' in summary


def test_progress_summary_lists_measurements():
    tl.log_measurement(24, 89, 57, 2.5, note='ウォームアップ後', today=START)
    summary = tl.get_progress_summary(today=START)
    assert '24 WPM' in summary
    assert 'ウォームアップ後' in summary


def test_key_guide_jis_contains_jis_specific_bindings():
    """JIS固有の割り当て（(が8、_がろキー）が含まれる"""
    guide = tl.get_key_guide('jis')
    assert '左シフト + `8`' in guide   # ( はJISでは8
    assert 'ろキー' in guide


def test_key_guide_us_contains_us_specific_bindings():
    guide = tl.get_key_guide('us')
    assert '左シフト + `9`' in guide   # ( はUSでは9


def test_key_guide_unknown_layout():
    assert 'jis / us' in tl.get_key_guide('dvorak')


def test_weekly_summary_without_measurements():
    assert '計測はまだ未実施' in tl.get_weekly_typing_summary(today=START)


def test_weekly_summary_urges_measurement_when_overdue():
    tl.log_measurement(24, 89, 57, 2.5, today=START)
    summary = tl.get_weekly_typing_summary(today=START + timedelta(days=8))
    assert '8日経過' in summary
