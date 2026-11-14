from datetime import datetime

import pytest

import study_logic as sl


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/study_data.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(sl, 'STUDY_DATA_FILE', str(tmp_path / 'study_data.json'))


def at(day, hour=12):
    return datetime(2026, 11, day, hour, 0, tzinfo=sl.JST)


# 2026-11-14 は土曜日。その週は 11/9(月)〜11/15(日)
SATURDAY = at(14)


def test_log_session_stores_minutes_and_topic():
    sl.log_session(25, '設計の本', now=SATURDAY)

    assert sl.load_study_data()['sessions'] == [
        {'date': '2026-11-14', 'minutes': 25, 'topic': '設計の本'}]


def test_log_session_message_shows_topic_and_running_totals():
    sl.log_session(25, '設計', now=at(14, 9))
    msg = sl.log_session(25, 'AWS', now=at(14, 15))

    assert '内容: AWS（25分）' in msg
    assert '今日の合計: 50分' in msg
    assert '今週の合計: 50分' in msg


def test_a_session_without_a_topic_is_recorded_not_rejected():
    """⭕ 内容は任意。何を勉強したか書かなくても、25分は記録に残す。"""
    msg = sl.log_session(25, '', now=SATURDAY)

    assert sl.NO_TOPIC_LABEL in msg
    assert len(sl.load_study_data()['sessions']) == 1


@pytest.mark.parametrize('minutes', [0, -5, 601, True, 25.0, '25', None])
def test_an_invalid_duration_is_refused_and_not_stored(minutes):
    msg = sl.log_session(minutes, 'x', now=SATURDAY)

    assert msg.startswith('❌')
    assert sl.load_study_data()['sessions'] == []


def test_topic_is_tidied_and_capped():
    assert sl.normalize_topic('  設計   の\n本  ') == '設計 の 本'
    assert len(sl.normalize_topic('あ' * 100)) == sl.TOPIC_MAX
    assert sl.normalize_topic(None) == ''
    assert sl.normalize_topic(123) == ''


def test_the_week_starts_on_monday_like_the_weekly_summary():
    sl.log_session(25, 'a', now=at(8))      # 日曜（前の週）
    sl.log_session(30, 'b', now=at(9))      # 月曜（今週のはじまり）
    sl.log_session(40, 'c', now=at(14))     # 土曜（今日）

    totals = sl.summarize(SATURDAY)

    assert totals['today'] == 40
    assert totals['week'] == 70
    assert totals['total'] == 95
    assert totals['count'] == 3


def test_sessions_after_today_do_not_count_toward_the_week():
    """未来の日付が紛れても（時計のずれなど）、今週に混ぜない。"""
    sl.log_session(25, 'a', now=at(14))
    sl.log_session(60, 'future', now=at(15))

    assert sl.summarize(SATURDAY)['week'] == 25


def test_summarize_with_no_records_is_zero():
    assert sl.summarize(SATURDAY) == {'today': 0, 'week': 0, 'total': 0, 'count': 0}


def test_a_broken_record_does_not_break_the_totals():
    data = {'sessions': [{'date': '2026-11-14', 'minutes': 'abc'}, {'date': '2026-11-14', 'minutes': 25}, {}]}
    assert sl.summarize(SATURDAY, data)['today'] == 25


@pytest.mark.parametrize('minutes, expected', [(25, '25分'), (60, '1時間'), (85, '1時間25分'), (0, '0分')])
def test_format_minutes(minutes, expected):
    assert sl.format_minutes(minutes) == expected


def test_stats_summary_when_empty_invites_the_first_session():
    assert 'まだありません' in sl.get_stats_summary(SATURDAY)


def test_stats_summary_ranks_topics_by_total_time():
    sl.log_session(25, 'AWS', now=at(10))
    sl.log_session(25, '設計', now=at(11))
    sl.log_session(25, '設計', now=at(12))
    sl.log_session(25, '', now=at(13))

    msg = sl.get_stats_summary(SATURDAY)

    assert msg.index('・設計: 50分') < msg.index('・AWS: 25分')
    assert f"・{sl.NO_TOPIC_LABEL}: 25分" in msg
    assert '累計: 1時間40分（4回）' in msg


def test_stats_summary_caps_the_topic_list():
    for i in range(sl.TOP_TOPICS + 2):
        sl.log_session(25, f'topic{i}', now=at(10))

    assert 'ほか2件' in sl.get_stats_summary(SATURDAY)
