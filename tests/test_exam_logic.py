from datetime import datetime

import pytest

import exam_logic as el


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/exam_data.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(el, 'EXAM_DATA_FILE', str(tmp_path / 'exam_data.json'))


# ====================================================
# log_session
# ====================================================

def test_log_session_records_result():
    msg = el.log_session('technology', 20, 13)

    assert '13/20問正解' in msg
    assert '65%' in msg
    sessions = el.load_exam_data()['sessions']
    assert len(sessions) == 1
    assert sessions[0]['field'] == 'technology'


def test_log_session_rejects_unknown_field():
    msg = el.log_session('unknown_field', 10, 5)
    assert '不明な分野' in msg
    assert el.load_exam_data()['sessions'] == []


def test_log_session_rejects_zero_total():
    msg = el.log_session('technology', 0, 0)
    assert '問題数は1以上' in msg
    assert el.load_exam_data()['sessions'] == []


def test_log_session_rejects_correct_greater_than_total():
    msg = el.log_session('technology', 10, 11)
    assert '正解数は0〜10の範囲' in msg
    assert el.load_exam_data()['sessions'] == []


def test_log_session_rejects_negative_correct():
    msg = el.log_session('technology', 10, -1)
    assert '正解数は' in msg
    assert el.load_exam_data()['sessions'] == []


def test_log_session_accepts_perfect_and_zero_score():
    assert '10/10問正解' in el.log_session('technology', 10, 10)
    assert '0/10問正解' in el.log_session('technology', 10, 0)


@pytest.mark.parametrize('correct,total,expected_phrase', [
    (9, 10, '素晴らしい'),   # 90% → 高評価
    (7, 10, 'まずまず'),      # 70% → 中評価
    (4, 10, '伸びしろ'),      # 40% → 弱点
])
def test_log_session_feedback_varies_by_rate(correct, total, expected_phrase):
    msg = el.log_session('technology', total, correct)
    assert expected_phrase in msg


# ====================================================
# aggregate_by_field
# ====================================================

def test_aggregate_by_field_sums_multiple_sessions():
    sessions = [
        {"field": "technology", "total": 10, "correct": 5},
        {"field": "technology", "total": 10, "correct": 9},
    ]
    stats = el.aggregate_by_field(sessions)

    assert stats['technology']['total'] == 20
    assert stats['technology']['correct'] == 14
    assert stats['technology']['rate'] == 70


def test_aggregate_by_field_ignores_unknown_fields():
    sessions = [{"field": "bogus", "total": 10, "correct": 5}]
    assert el.aggregate_by_field(sessions) == {}


def test_aggregate_by_field_empty_returns_empty():
    assert el.aggregate_by_field([]) == {}


# ====================================================
# get_stats_summary
# ====================================================

def test_get_stats_summary_when_empty():
    assert 'まだ演習記録がありません' in el.get_stats_summary()


def test_get_stats_summary_lists_weak_field_first():
    el.log_session('strategy', 10, 9)      # 90%
    el.log_session('basic_theory', 10, 3)  # 30% → 弱点

    summary = el.get_stats_summary()
    idx_weak = summary.index('基礎理論')
    idx_strong = summary.index('ストラテジ')

    assert idx_weak < idx_strong  # 正答率が低い分野が先に表示される
    assert '⚠️' in summary


def test_get_stats_summary_shows_untouched_fields():
    el.log_session('technology', 10, 8)
    summary = el.get_stats_summary()
    assert '未着手の分野' in summary
    assert 'マネジメント系' in summary


# ====================================================
# get_weekly_exam_summary
# ====================================================

def test_weekly_exam_summary_empty_when_no_sessions():
    assert el.get_weekly_exam_summary() == ''


def test_weekly_exam_summary_reports_since_last_snapshot():
    el.log_session('technology', 20, 15)
    summary = el.get_weekly_exam_summary()

    assert '20問' in summary
    assert '75%' in summary


def test_weekly_exam_summary_only_counts_new_sessions():
    el.log_session('technology', 20, 15)
    el.get_weekly_exam_summary()  # スナップショット更新

    el.log_session('management', 10, 5)
    summary = el.get_weekly_exam_summary()

    assert '10問' in summary  # 前回以降の分だけ
    assert '50%' in summary
