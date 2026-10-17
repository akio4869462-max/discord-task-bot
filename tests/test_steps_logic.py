from datetime import datetime, timedelta

import pytest

import steps_logic as sl


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/steps_data.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(sl, 'STEPS_DATA_FILE', str(tmp_path / 'steps_data.json'))


DAY = datetime(2026, 10, 17, 21, 0, tzinfo=sl.JST)


def test_first_record_credits_all_steps():
    msg, credit = sl.log_steps(8200, now=DAY)

    assert credit == 8200
    assert '8,200歩' in msg
    assert sl.load_steps_data()['days']['2026-10-17']['steps'] == 8200


def test_same_day_rerecord_credits_only_the_increase():
    """朝3,000歩→夜9,000歩なら、2回目に調教へ入るのは差の6,000歩だけ。"""
    sl.log_steps(3000, now=DAY)
    _, credit = sl.log_steps(9000, now=DAY)

    assert credit == 6000
    assert sl.load_steps_data()['days']['2026-10-17']['steps'] == 9000


def test_recording_the_same_total_again_credits_nothing():
    """自動取り込みが同じ日の合計を繰り返し送ってきても、二重に加算されない。"""
    sl.log_steps(5000, now=DAY)
    _, credit = sl.log_steps(5000, now=DAY)

    assert credit == 0


def test_correcting_downward_does_not_claw_back_or_credit_again():
    sl.log_steps(9000, now=DAY)
    _, credit = sl.log_steps(7000, now=DAY)        # 入力ミスの訂正
    assert credit == 0
    assert sl.load_steps_data()['days']['2026-10-17']['steps'] == 7000

    _, credit = sl.log_steps(9500, now=DAY)        # 数えた9,000歩を超えた500歩だけ
    assert credit == 500


def test_steps_above_the_daily_cap_are_recorded_but_not_credited():
    msg, credit = sl.log_steps(20000, now=DAY)

    assert credit == sl.STEPS_DAILY_CAP
    assert sl.load_steps_data()['days']['2026-10-17']['steps'] == 20000
    assert f'{sl.STEPS_DAILY_CAP:,}歩まで' in msg

    _, credit = sl.log_steps(30000, now=DAY)       # 上限に達したあとは増えても数えない
    assert credit == 0


def test_each_day_is_counted_separately():
    sl.log_steps(6000, now=DAY)
    _, credit = sl.log_steps(6000, now=DAY + timedelta(days=1))

    assert credit == 6000


@pytest.mark.parametrize('steps', [-1, sl.STEPS_RANGE[1] + 1, 12.5, '8000', None, True])
def test_invalid_steps_are_rejected_without_recording(steps):
    msg, credit = sl.log_steps(steps, now=DAY)

    assert msg.startswith('❌')
    assert credit == 0
    assert sl.load_steps_data()['days'] == {}


def test_zero_steps_is_a_valid_record_that_credits_nothing():
    msg, credit = sl.log_steps(0, now=DAY)

    assert not msg.startswith('❌')
    assert credit == 0


def test_source_is_kept_so_imports_can_be_told_apart_from_manual_entries():
    sl.log_steps(5000, now=DAY)
    assert sl.load_steps_data()['days']['2026-10-17']['source'] == 'manual'

    sl.log_steps(7000, now=DAY, source='healthkit')
    assert sl.load_steps_data()['days']['2026-10-17']['source'] == 'healthkit'
