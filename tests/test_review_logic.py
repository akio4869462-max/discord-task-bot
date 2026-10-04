from datetime import datetime

import pytest

import review_logic as rl

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=rl.JST)


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, 'REVIEW_DATA_FILE', str(tmp_path / 'review_data.json'))


def _add(title='R5秋 午前 問23', field='technology', keywords=('デッドロック',)):
    return rl.add_item(title, field, list(keywords), now=NOW)


# ====================================================
# 手動登録・状態管理
# ====================================================

def test_parse_keywords_splits_and_dedups():
    assert rl.parse_keywords('デッドロック、排他制御, デッドロック\nセマフォ') == ['デッドロック', '排他制御', 'セマフォ']
    assert rl.parse_keywords('') == []


def test_add_item_registers_unlearned():
    ok, msg = _add()
    assert ok and '令和5年秋期 問23' in msg  # 識別名はCSVと同じ形に揃えて登録される
    item = rl.list_items()[0]
    assert item['status'] == 0 and item['wrong'] == 1 and item['created'] == '2026-10-04'


def test_add_item_rejects_blank_title_and_unknown_field():
    assert not rl.add_item('  ', 'technology', [])[0]
    assert not rl.add_item('x', 'nope', [])[0]
    assert rl.list_items() == []


def test_advance_until_done_drops_from_list():
    _add()
    item_id = rl.list_items()[0]['id']
    for expected in (1, 2, 3, 3):
        assert rl.advance(item_id, now=NOW)['status'] == expected
    assert rl.list_items() == []
    assert len(rl.list_items(include_done=True)) == 1


def test_mark_wrong_again_resets_status_and_counts():
    _add()
    item_id = rl.list_items()[0]['id']
    rl.advance(item_id)
    item = rl.mark_wrong_again(item_id)
    assert item['status'] == 0 and item['wrong'] == 2


def test_unknown_id_returns_none():
    assert rl.advance('zzz') is None
    assert rl.mark_wrong_again('zzz') is None
    assert rl.set_keywords('zzz', ['x']) is None
    assert rl.delete_item('zzz') is False


def test_delete_item():
    _add()
    assert rl.delete_item(rl.list_items()[0]['id'])
    assert rl.list_items() == []


# ====================================================
# キーワード一覧・朝の通知
# ====================================================

def test_keyword_list_groups_by_field_and_skips_learned():
    _add('問A', 'technology', ['デッドロック'])
    _add('問B', 'strategy', ['ROI'])
    learned = [i for i in rl.list_items() if i['title'] == '問B'][0]['id']
    rl.advance(learned)
    msg = rl.build_keyword_list()
    assert 'テクノロジ系' in msg and 'デッドロック' in msg
    assert 'ROI' not in msg


def test_keyword_list_empty_message():
    assert '調べる問題はありません' in rl.build_keyword_list()


def test_morning_notice_empty_when_nothing_pending():
    assert rl.build_morning_notice() == ''


def test_morning_notice_counts():
    _add('問A')
    _add('問B')
    assert '未学習 2問' in rl.build_morning_notice()


# ====================================================
# キーワード編集
# ====================================================

def test_set_keywords_replaces_and_limits():
    _add()
    item_id = rl.list_items()[0]['id']
    item = rl.set_keywords(item_id, [f'語{i}' for i in range(20)], now=NOW)
    assert len(item['keywords']) == rl.MAX_KEYWORDS


def test_old_items_without_topic_are_backfilled():
    _add()
    assert rl.list_items()[0]['topic'] == ''


# ====================================================
# 過去問道場のCSV
# ====================================================

def _csv_bytes():
    def link(label):
        return '"=HYPERLINK(""https://www.ap-siken.com/kakomon/06_haru/q1.html"",""' + label + '"")"'

    lines = [
        "No.,正誤,分野名,大分類,中分類,出典,学習日",
        f'1,×,テクノロジ系,技術要素,データベース,{link("令和6年春期 問26")},2026/10/1',
        f'2,×,マネジメント系,サービスマネジメント,システム監査,{link("令和6年秋期 問59")},2026/10/1',
        f'3,○,テクノロジ系,技術要素,データベース,{link("令和6年春期 問26")},2026/10/4',
        f'4,○,ストラテジ系,企業と法務,法務,{link("令和6年春期 問78")},2026/10/4',
    ]
    return "\n".join(lines).encode('cp932')


def test_parse_dojo_csv_uses_latest_result_per_question():
    entries = rl.parse_dojo_csv(rl.decode_csv_bytes(_csv_bytes()))
    # 問26は後で正解済み、問78は最初から正解 → 残るのは問59だけ
    assert [e['title'] for e in entries] == ['令和6年秋期 問59']
    assert entries[0]['field'] == 'management'
    assert entries[0]['keywords'] == []
    assert entries[0]['topic'] == 'システム監査'


def test_parse_dojo_csv_rejects_unknown_header():
    assert rl.parse_dojo_csv('a,b,c\n1,2,3') == []
    assert rl.parse_dojo_csv('') == []


def test_decode_csv_bytes_handles_utf8_bom_and_cp932():
    assert rl.decode_csv_bytes('﻿正誤'.encode('utf-8')) == '正誤'
    assert rl.decode_csv_bytes('正誤'.encode('cp932')) == '正誤'


def test_add_items_from_csv_registers_and_is_idempotent():
    msg = rl.add_items_from_csv(_csv_bytes(), now=NOW)
    assert '1問' in msg and '令和6年秋期 問59' in msg
    assert '飛ばしました' in rl.add_items_from_csv(_csv_bytes(), now=NOW)
    assert len(rl.list_items()) == 1


def test_add_items_from_csv_rejects_bad_input():
    assert rl.add_items_from_csv(b'not a csv').startswith('❌')
    assert rl.add_items_from_csv(b'x' * (rl.MAX_CSV_BYTES + 1)).startswith('❌')


def test_csv_import_stores_topic_not_keywords():
    rl.add_items_from_csv(_csv_bytes(), now=NOW)
    item = rl.list_items()[0]
    assert item['keywords'] == [] and item['topic'] == 'システム監査'
    assert 'システム監査' in rl.format_item(item)


def test_keyword_list_separates_unset_items_from_keywords():
    rl.add_items_from_csv(_csv_bytes(), now=NOW)
    _add('問A', 'technology', ['デッドロック'])
    msg = rl.build_keyword_list()
    assert 'デッドロック' in msg
    assert 'キーワード未設定（1問）' in msg and '令和6年秋期 問59（システム監査）' in msg


# ====================================================
# 識別名の正規化・重複の扱い
# ====================================================

@pytest.mark.parametrize('raw, expected', [
    ('R6春 午前 問26', '令和6年春期 問26'),
    ('令和6年度春期 問26', '令和6年春期 問26'),
    ('Ｒ６秋問５９', '令和6年秋期 問59'),
    ('r5秋期 問23', '令和5年秋期 問23'),
    ('令和1年秋期 問3', '令和元年秋期 問3'),
    ('令和元年秋 問03', '令和元年秋期 問3'),
    ('H30春 午前 問12', '平成30年春期 問12'),
    ('令和6年春期 問26', '令和6年春期 問26'),
])
def test_normalize_title(raw, expected):
    assert rl.normalize_title(raw) == expected


@pytest.mark.parametrize('raw', ['令和6年春期 午後 問1', 'デッドロックの問題', '  ', ''])
def test_normalize_title_keeps_unrecognized_text(raw):
    assert rl.normalize_title(raw) == raw.strip()


def test_add_item_normalizes_title():
    rl.add_item('R6秋 午前 問59', 'management', [], now=NOW)
    assert rl.list_items()[0]['title'] == '令和6年秋期 問59'


def test_load_normalizes_old_titles(tmp_path):
    import json
    path = rl.REVIEW_DATA_FILE
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({"items": [{"id": "a", "title": "R5秋 午前 問23", "field": "technology", "keywords": [],
                              "memo": "", "status": 0, "wrong": 1, "created": "2026-10-01",
                              "updated": "2026-10-01"}]}, f, ensure_ascii=False)
    assert rl.list_items()[0]['title'] == '令和5年秋期 問23'


def test_manual_entry_and_csv_do_not_duplicate():
    rl.add_item('R6秋 午前 問59', 'management', ['システム監査'], now=NOW)
    msg = rl.add_items_from_csv(_csv_bytes(), now=NOW)
    assert '0問' in msg and '1問は飛ばしました' in msg
    assert len(rl.list_items()) == 1
    assert rl.list_items()[0]['keywords'] == ['システム監査']  # 既存の内容は変えない


def test_parse_dojo_csv_reads_study_date():
    entries = rl.parse_dojo_csv(rl.decode_csv_bytes(_csv_bytes()))
    assert entries[0]['date'] == '2026-10-01'


def _done_item(done_on):
    """令和6年秋期 問59を完了済み（完了日=done_on）にする。"""
    rl.add_item('令和6年秋期 問59', 'management', [], now=done_on)
    item_id = rl.list_items()[0]['id']
    for _ in range(3):
        rl.advance(item_id, now=done_on)
    return item_id


def test_csv_reopens_done_item_when_wrong_again_after_completion():
    item_id = _done_item(datetime(2026, 9, 30, tzinfo=rl.JST))
    msg = rl.add_items_from_csv(_csv_bytes(), now=NOW)  # CSVの学習日は2026/10/1
    assert '🔁' in msg and '1問を復習対象に戻しました' in msg
    item = rl.get_item(item_id)
    assert item['status'] == 0 and item['wrong'] == 2
    assert len(rl.load_review_data()['items']) == 1


@pytest.mark.parametrize('done_day', [1, 4])  # CSVの学習日と同日・それより後に完了
def test_csv_ignores_old_wrong_result_for_done_item(done_day):
    item_id = _done_item(datetime(2026, 10, done_day, tzinfo=rl.JST))
    msg = rl.add_items_from_csv(_csv_bytes(), now=NOW)
    assert '🔁' not in msg and '飛ばしました' in msg
    assert rl.get_item(item_id)['status'] == 3
    assert len(rl.load_review_data()['items']) == 1
