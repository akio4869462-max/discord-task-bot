import zipfile
from datetime import datetime

import pytest

import backup_logic


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """各テストが本物のdata/に影響しないよう、一時ディレクトリに差し替える。"""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    monkeypatch.setattr(backup_logic, 'DATA_DIR', str(data_dir))
    monkeypatch.setattr(backup_logic, 'BACKUP_DIR', str(data_dir / '_backups'))
    return data_dir


def _write(data_dir, name, content):
    (data_dir / name).write_text(content, encoding='utf-8')


MONDAY = datetime(2026, 8, 31, 8, 10, tzinfo=backup_logic.JST)  # 2026-08-31は月曜日
assert MONDAY.weekday() == 0


# ====================================================
# 秘密鍵の混入防止（最重要）
# ====================================================

def test_backup_targets_never_declare_credentials():
    """許可リストに秘密鍵が紛れ込んでいないことを、設定レベルで固定する。"""
    assert 'service_account.json' not in backup_logic.BACKUP_TARGETS


def test_create_archive_never_includes_service_account(isolated_data_dir):
    """★秘密鍵がZIPへ混入しないことの回帰テスト（最重要）。"""
    _write(isolated_data_dir, 'todo.json', '[]')
    _write(isolated_data_dir, 'service_account.json', '{"private_key": "SECRET"}')

    zip_path, included, _ = backup_logic.create_archive()

    assert 'service_account.json' not in included
    with zipfile.ZipFile(zip_path) as archive:
        assert 'service_account.json' not in archive.namelist()


def test_denylist_wins_even_if_accidentally_added_to_targets(isolated_data_dir, monkeypatch):
    """許可リストに誤って追加されても、DENYLISTが二重の防波堤として弾く。"""
    monkeypatch.setattr(backup_logic, 'BACKUP_TARGETS', backup_logic.BACKUP_TARGETS + ('service_account.json',))
    _write(isolated_data_dir, 'service_account.json', '{"private_key": "SECRET"}')

    found, _ = backup_logic.collect_targets()

    assert not any(p.endswith('service_account.json') for p in found)


# ====================================================
# collect_targets / create_archive
# ====================================================

def test_collect_targets_reports_missing_files(isolated_data_dir):
    _write(isolated_data_dir, 'todo.json', '[]')
    found, missing = backup_logic.collect_targets()

    assert any(p.endswith('todo.json') for p in found)
    assert 'player_data.json' in missing


def test_create_archive_returns_none_when_nothing_found(isolated_data_dir):
    zip_path, included, missing = backup_logic.create_archive()
    assert zip_path is None
    assert included == []
    assert set(missing) == set(backup_logic.BACKUP_TARGETS)


def test_create_archive_includes_only_existing_targets(isolated_data_dir):
    _write(isolated_data_dir, 'todo.json', '[]')
    _write(isolated_data_dir, 'player_data.json', '{}')

    zip_path, included, missing = backup_logic.create_archive(now=MONDAY)

    assert set(included) == {'todo.json', 'player_data.json'}
    assert 'glossary.json' in missing
    with zipfile.ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == {'todo.json', 'player_data.json'}


def test_create_archive_filename_includes_date(isolated_data_dir):
    _write(isolated_data_dir, 'todo.json', '[]')
    zip_path, _, _ = backup_logic.create_archive(now=MONDAY)
    assert zip_path.endswith('backup_2026-08-31.zip')


# ====================================================
# is_within_upload_limit
# ====================================================

def test_is_within_upload_limit_true_for_small_file(isolated_data_dir):
    _write(isolated_data_dir, 'todo.json', '[]')
    zip_path, _, _ = backup_logic.create_archive()
    assert backup_logic.is_within_upload_limit(zip_path) is True


def test_is_within_upload_limit_false_when_over_threshold(isolated_data_dir, monkeypatch):
    _write(isolated_data_dir, 'todo.json', '[]')
    zip_path, _, _ = backup_logic.create_archive()
    monkeypatch.setattr(backup_logic, 'MAX_UPLOAD_BYTES', 0)
    assert backup_logic.is_within_upload_limit(zip_path) is False


# ====================================================
# prune_old_archives
# ====================================================

def test_prune_old_archives_keeps_only_latest_n(isolated_data_dir):
    for day in range(1, 11):
        _write(isolated_data_dir, 'todo.json', '[]')
        backup_logic.create_archive(now=datetime(2026, 8, day, tzinfo=backup_logic.JST))

    removed = backup_logic.prune_old_archives(keep=8)

    remaining = sorted(name for name in (isolated_data_dir / '_backups').iterdir())
    assert len(remaining) == 8
    assert len(removed) == 2
    # 一番古い日付から消えている
    assert 'backup_2026-08-01.zip' in removed
    assert 'backup_2026-08-10.zip' not in removed


def test_prune_old_archives_returns_empty_when_dir_missing(isolated_data_dir):
    assert backup_logic.prune_old_archives() == []


# ====================================================
# build_message
# ====================================================

def test_build_message_when_nothing_found():
    msg = backup_logic.build_message(None, [], list(backup_logic.BACKUP_TARGETS), now=MONDAY)
    assert '見つかりませんでした' in msg
    assert '2026-08-31' in msg


def test_build_message_lists_included_and_missing(isolated_data_dir):
    _write(isolated_data_dir, 'todo.json', '[]')
    zip_path, included, missing = backup_logic.create_archive(now=MONDAY)

    msg = backup_logic.build_message(zip_path, included, missing, now=MONDAY)

    assert 'todo.json' in msg
    assert '未収録' in msg
    assert 'player_data.json' in msg


def test_build_message_warns_when_over_upload_limit(isolated_data_dir, monkeypatch):
    _write(isolated_data_dir, 'todo.json', '[]')
    zip_path, included, missing = backup_logic.create_archive(now=MONDAY)
    monkeypatch.setattr(backup_logic, 'MAX_UPLOAD_BYTES', 0)

    msg = backup_logic.build_message(zip_path, included, missing, now=MONDAY)

    assert '添付していません' in msg
