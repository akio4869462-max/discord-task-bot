"""復元（backup_logic.restore_archive）のテスト。

バックアップのZIPを data/ に書き戻す。許可リスト以外・秘密鍵・壊れたJSONは書き戻さない。
"""
import json
import zipfile
from datetime import datetime

import pytest

import backup_logic


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    monkeypatch.setattr(backup_logic, 'DATA_DIR', str(data_dir))
    monkeypatch.setattr(backup_logic, 'BACKUP_DIR', str(data_dir / '_backups'))
    return data_dir


NOW = datetime(2026, 9, 12, 21, 0, tzinfo=backup_logic.JST)


def make_zip(tmp_path, members):
    """{名前: 中身} からZIPを作る。"""
    path = tmp_path / 'upload.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return str(path)


def test_inspect_accepts_only_allowlisted_flat_files(tmp_path):
    z = make_zip(tmp_path, {
        'stable.json': '{}',
        'todo.json': '[]',
        'service_account.json': '{"private_key": "SECRET"}',   # 秘密鍵
        'sub/stable.json': '{}',                                 # ディレクトリ付き
        'notes.txt': 'x',                                        # 許可リスト外
    })
    accepted, ignored, error = backup_logic.inspect_archive(z)
    assert error is None
    assert accepted == ['stable.json', 'todo.json']
    assert set(ignored) == {'service_account.json', 'sub/stable.json', 'notes.txt'}


def test_inspect_rejects_non_zip_and_empty(tmp_path):
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'not a zip')
    assert backup_logic.inspect_archive(str(bad))[2]
    z = make_zip(tmp_path, {'notes.txt': 'x'})
    assert '復元できるファイル' in backup_logic.inspect_archive(z)[2]


def test_restore_writes_files_and_snapshots_the_old_state(isolated_data_dir, tmp_path):
    """⭕ 上書きの前に今の状態をZIPへ退避する。間違えても1つ前に戻れる。"""
    (isolated_data_dir / 'stable.json').write_text('{"generation": 1}', encoding='utf-8')
    z = make_zip(tmp_path, {'stable.json': '{"generation": 5}', 'todo.json': '[]'})

    restored, snapshot, error = backup_logic.restore_archive(z, now=NOW)

    assert error is None and restored == ['stable.json', 'todo.json']
    assert json.loads((isolated_data_dir / 'stable.json').read_text(encoding='utf-8'))['generation'] == 5
    assert (isolated_data_dir / 'todo.json').exists()
    assert snapshot and 'before-restore' in snapshot
    with zipfile.ZipFile(snapshot) as archive:
        assert json.loads(archive.read('stable.json'))['generation'] == 1


def test_restore_never_touches_the_service_account(isolated_data_dir, tmp_path):
    """★秘密鍵はZIPに入っていても書き戻さない（最重要）。"""
    (isolated_data_dir / 'service_account.json').write_text('{"private_key": "REAL"}', encoding='utf-8')
    z = make_zip(tmp_path, {'service_account.json': '{"private_key": "FAKE"}', 'todo.json': '[]'})

    restored, _, _ = backup_logic.restore_archive(z, now=NOW)

    assert 'service_account.json' not in restored
    assert 'REAL' in (isolated_data_dir / 'service_account.json').read_text(encoding='utf-8')


def test_restore_skips_broken_json(isolated_data_dir, tmp_path):
    """壊れたJSONを置くとBotが読み込みで落ちるので、そのファイルだけ飛ばす。"""
    (isolated_data_dir / 'stable.json').write_text('{"generation": 1}', encoding='utf-8')
    z = make_zip(tmp_path, {'stable.json': '{broken', 'todo.json': '[]'})

    restored, _, error = backup_logic.restore_archive(z, now=NOW)

    assert error is None and restored == ['todo.json']
    assert json.loads((isolated_data_dir / 'stable.json').read_text(encoding='utf-8'))['generation'] == 1


def test_restore_round_trips_a_real_backup(isolated_data_dir):
    """create_archive で作ったZIPを、そのまま restore_archive に食わせて戻せること。"""
    (isolated_data_dir / 'stable.json').write_text('{"generation": 3}', encoding='utf-8')
    zip_path, _, _ = backup_logic.create_archive(now=NOW)
    (isolated_data_dir / 'stable.json').write_text('{"generation": 0}', encoding='utf-8')

    restored, _, error = backup_logic.restore_archive(zip_path, now=NOW)

    assert error is None and 'stable.json' in restored
    assert json.loads((isolated_data_dir / 'stable.json').read_text(encoding='utf-8'))['generation'] == 3


def test_restore_message_reads_well():
    msg = backup_logic.build_restore_message(['stable.json'], 'data/_backups/backup_x_before-restore.zip', None)
    assert '復元しました' in msg and 'stable.json' in msg and '退避' in msg
    assert '復元できませんでした' in backup_logic.build_restore_message([], None, 'ZIPが壊れています。')
