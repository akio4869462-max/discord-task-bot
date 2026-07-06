from datetime import datetime

import pytest

import task_logic


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """各テストが本物のdata/todo.jsonに影響しないよう、一時ディレクトリに差し替える。"""
    monkeypatch.setattr(task_logic, 'DB_FILE', str(tmp_path / 'todo.json'))


def test_load_data_returns_empty_list_when_file_missing():
    assert task_logic.load_data() == []


def test_add_task_creates_item_with_expected_fields():
    task_logic.add_task('サンプルタスク', 'document', '2026-06-15', 3)
    data = task_logic.load_data()

    assert len(data) == 1
    assert data[0]['task'] == 'サンプルタスク'
    assert data[0]['category'] == 'document'
    assert data[0]['deadline'] == '2026-06-15'
    assert data[0]['priority'] == 3
    assert 'id' in data[0]


def test_add_task_invalid_category_falls_back_to_programming():
    task_logic.add_task('タスク', category='invalid_category')
    assert task_logic.load_data()[0]['category'] == 'programming'


def test_add_task_invalid_priority_falls_back_to_2():
    task_logic.add_task('タスク', priority=99)
    assert task_logic.load_data()[0]['priority'] == 2


def test_add_task_ids_are_unique():
    task_logic.add_task('タスク1')
    task_logic.add_task('タスク2')
    data = task_logic.load_data()
    assert data[0]['id'] != data[1]['id']


@pytest.mark.parametrize('deadline_str,expected', [
    ('2026-06-15', '2026-06-15'),
    ('2026/06/15', '2026-06-15'),
    ('', None),
    (None, None),
    ('invalid', None),
])
def test_parse_deadline_with_year(deadline_str, expected):
    assert task_logic.parse_deadline(deadline_str) == expected


def test_parse_deadline_without_year_uses_current_year():
    current_year = datetime.now().year
    assert task_logic.parse_deadline('6/15') == f'{current_year}-06-15'


def test_list_tasks_when_empty():
    assert task_logic.list_tasks() == '現在、登録されたタスクはありません。'


def test_list_tasks_sorts_by_priority_then_deadline():
    task_logic.add_task('低優先度', priority=1)
    task_logic.add_task('高優先度_期限遠い', priority=3, deadline_str='2026-12-31')
    task_logic.add_task('高優先度_期限近い', priority=3, deadline_str='2026-01-01')

    result = task_logic.list_tasks()
    idx_near = result.index('高優先度_期限近い')
    idx_far = result.index('高優先度_期限遠い')
    idx_low = result.index('低優先度')

    assert idx_near < idx_far < idx_low


def test_complete_task_by_id_removes_correct_task():
    task_logic.add_task('残すタスク')
    task_logic.add_task('消すタスク')
    target_id = task_logic.load_data()[1]['id']

    msg, category = task_logic.complete_task(target_id)

    assert 'お疲れ様でした' in msg
    assert category == 'programming'
    remaining = task_logic.load_data()
    assert len(remaining) == 1
    assert remaining[0]['task'] == '残すタスク'


def test_complete_task_by_number_removes_correct_task():
    task_logic.add_task('1番目')
    task_logic.add_task('2番目')

    msg, category = task_logic.complete_task('1')

    assert '1番目' in msg
    remaining = task_logic.load_data()
    assert len(remaining) == 1
    assert remaining[0]['task'] == '2番目'


def test_complete_task_unknown_id_returns_error():
    msg, category = task_logic.complete_task('nonexistent')
    assert category is None
    assert '見つかりませんでした' in msg


def test_complete_task_out_of_range_number_returns_error():
    msg, category = task_logic.complete_task('999')
    assert category is None
    assert '見つかりません' in msg


def test_get_display_fields_returns_task_text_and_stars():
    item = {'task': 'テストタスク', 'priority': 3}
    task_text, stars = task_logic.get_display_fields(item)
    assert task_text == 'テストタスク'
    assert stars == '★★★'
