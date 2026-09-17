from datetime import datetime, timedelta

import pytest

import heartbeat_logic as hb


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    """各テストが本物のdata/heartbeat.txtに影響しないよう差し替える。"""
    monkeypatch.setattr(hb, 'HEARTBEAT_FILE', str(tmp_path / 'sub' / 'heartbeat.txt'))


NOON = datetime(2026, 6, 2, 12, 0, tzinfo=hb.JST)


def test_write_then_read_roundtrip():
    hb.write_heartbeat(now=NOON)
    assert hb.read_last_heartbeat() == NOON


def test_write_creates_parent_directory(tmp_path):
    # isolated_fileでネストしたディレクトリ(sub/)を指しているため、
    # makedirsが無いと親フォルダ不在で書き込みに失敗する。
    assert hb.write_heartbeat(now=NOON) is True


def test_heartbeat_age_seconds_after_write():
    hb.write_heartbeat(now=NOON)
    later = NOON + timedelta(minutes=5)
    assert hb.heartbeat_age_seconds(now=later) == pytest.approx(300)


def test_heartbeat_age_seconds_missing_file_returns_none():
    assert hb.heartbeat_age_seconds(now=NOON) is None


def test_read_last_heartbeat_missing_file_returns_none():
    assert hb.read_last_heartbeat() is None
