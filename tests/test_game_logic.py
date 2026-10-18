import json
import os
from datetime import date

import pytest

import game_logic as gl

TODAY = date(2026, 10, 19)    # 月曜


def entry(title, release_date='2026-10-25', platforms=('Switch 2',), **extra):
    e = {'title': title, 'platforms': list(platforms)}
    if release_date:
        e['release_date'] = release_date
    e.update(extra)
    return e


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """⭕ このモジュールが読み書きする3つのファイルを全部差し替える。漏れると実データを巻き込む。"""
    monkeypatch.setattr(gl, 'SEED_FILE', str(tmp_path / 'seed.json'))
    monkeypatch.setattr(gl, 'USER_FILE', str(tmp_path / 'user.json'))
    monkeypatch.setattr(gl, 'WATCH_FILE', str(tmp_path / 'watch.json'))


def write(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False)


# ====================================================
# 読み込み
# ====================================================

def test_load_releases_is_empty_when_no_files_exist():
    assert gl.load_releases() == []


def test_load_releases_reads_seed_object_and_user_list():
    write(gl.SEED_FILE, {'updated': '2026-10-18', 'releases': [entry('Seed Game')]})
    write(gl.USER_FILE, [entry('My Game', platforms=['PC'])])     # 配列でも、{"releases": [...]}でもよい

    titles = {r['title'] for r in gl.load_releases()}
    assert titles == {'Seed Game', 'My Game'}


def test_user_entry_overrides_the_same_title_and_date_from_seed():
    write(gl.SEED_FILE, {'releases': [entry('Game', '2026-11-01', note='seed')]})
    write(gl.USER_FILE, [entry('game', '2026-11-01', note='user')])    # 大文字小文字は区別しない

    releases = gl.load_releases()
    assert len(releases) == 1
    assert releases[0]['note'] == 'user'


def test_a_date_change_is_kept_as_a_separate_entry():
    """発売日が変わった作品は、別の日付のエントリとして並ぶ（上書きは同じ日付どうしだけ）。"""
    write(gl.SEED_FILE, {'releases': [entry('Game', '2026-11-01')]})
    write(gl.USER_FILE, [entry('Game', '2026-11-08')])
    assert len(gl.load_releases()) == 2


@pytest.mark.parametrize('bad', [
    'not a dict',
    {'platforms': ['PC'], 'release_date': '2026-11-01'},                    # タイトルなし
    {'title': ' ', 'platforms': ['PC'], 'release_date': '2026-11-01'},      # タイトルが空
    {'title': 'X', 'platforms': [], 'release_date': '2026-11-01'},          # 機種なし
    {'title': 'X', 'platforms': ['PS5'], 'release_date': '2026-11-01'},     # 対象外の機種だけ
    {'title': 'X', 'platforms': ['PC']},                                    # 発売日も時期も無い
    {'title': 'X', 'platforms': ['PC'], 'release_date': '2026/11/01'},      # 日付の形式が違う
])
def test_unusable_entries_are_skipped(bad):
    write(gl.SEED_FILE, {'releases': [bad, entry('OK')]})
    assert [r['title'] for r in gl.load_releases()] == ['OK']


def test_platforms_outside_the_supported_ones_are_dropped_not_the_whole_entry():
    write(gl.SEED_FILE, {'releases': [entry('Multi', platforms=['PC', 'PS5', 'Switch'])]})
    assert gl.load_releases()[0]['platforms'] == ['PC', 'Switch']


def test_a_broken_json_file_is_ignored_without_crashing():
    with open(gl.SEED_FILE, 'w', encoding='utf-8') as f:
        f.write('{ broken')
    write(gl.USER_FILE, [entry('Still Works')])
    assert [r['title'] for r in gl.load_releases()] == ['Still Works']


def test_seed_updated_date():
    assert gl.seed_updated() == ''
    write(gl.SEED_FILE, {'updated': '2026-10-18', 'releases': []})
    assert gl.seed_updated() == '2026-10-18'


# ====================================================
# 絞り込み
# ====================================================

def releases_of(*entries):
    write(gl.SEED_FILE, {'releases': list(entries)})
    return gl.load_releases()


def test_filter_keeps_only_upcoming_sorted_by_date():
    rs = releases_of(
        entry('Past', '2026-10-01'),
        entry('Today', '2026-10-19'),
        entry('Later', '2026-12-01'),
        entry('Soon', '2026-10-25'),
    )
    dated, _ = gl.filter_upcoming(rs, TODAY)
    assert [r['title'] for r in dated] == ['Today', 'Soon', 'Later']     # 今日発売は含み、過去は除く


def test_filter_by_platform():
    rs = releases_of(
        entry('OnlyPC', platforms=['PC']),
        entry('Both', platforms=['PC', 'Switch 2']),
        entry('OnlySwitch2', platforms=['Switch 2']),
    )
    dated, _ = gl.filter_upcoming(rs, TODAY, platform='PC')
    assert {r['title'] for r in dated} == {'OnlyPC', 'Both'}


def test_filter_by_days_includes_the_boundary_day():
    rs = releases_of(
        entry('In', '2026-11-02'),        # ちょうど14日後
        entry('Out', '2026-11-03'),
    )
    dated, _ = gl.filter_upcoming(rs, TODAY, days=14)
    assert [r['title'] for r in dated] == ['In']


def test_undated_entries_are_listed_only_when_no_period_is_given():
    """発売時期しか分からない作品は、期間内に収まるとは言えないので、期間を指定したときは出さない。"""
    rs = releases_of(entry('Someday', None, release_label='2026年内'), entry('Dated', '2026-10-25'))

    dated, undated = gl.filter_upcoming(rs, TODAY)
    assert [r['title'] for r in undated] == ['Someday']

    _, undated = gl.filter_upcoming(rs, TODAY, days=30)
    assert undated == []


# ====================================================
# 表示
# ====================================================

def test_release_line_shows_date_weekday_platforms_and_countdown():
    r = releases_of(entry('Game', '2026-10-22', platforms=['PC', 'Switch 2'], genre='RPG'))[0]
    line = gl.format_release(r, TODAY)
    assert '10/22(木)' in line          # 2026-10-22 は木曜
    assert 'あと3日' in line
    assert 'PC / Switch 2' in line
    assert 'RPG' in line


def test_release_line_marks_today_and_omits_countdown_far_away():
    today_game = releases_of(entry('Now', '2026-10-19'))[0]
    assert '今日発売' in gl.format_release(today_game, TODAY)

    far = releases_of(entry('Far', '2026-12-25'))[0]
    assert 'あと' not in gl.format_release(far, TODAY)


def test_release_line_shows_the_year_for_next_year():
    r = releases_of(entry('NewYear', '2027-01-15'))[0]
    assert '2027/1/15' in gl.format_release(r, TODAY)


def test_note_is_shown_only_in_the_detailed_view():
    r = releases_of(entry('Game', note='ここが見どころ'))[0]
    assert 'ここが見どころ' not in gl.format_release(r, TODAY)
    assert 'ここが見どころ' in gl.format_release(r, TODAY, detail=True)


def test_games_message_lists_titles_and_the_update_date():
    write(gl.SEED_FILE, {'updated': '2026-10-18', 'releases': [entry('Alpha'), entry('Beta', '2026-11-01')]})
    msg = gl.build_games_message(gl.load_releases(), TODAY)
    assert 'Alpha' in msg and 'Beta' in msg
    assert '2026-10-18' in msg
    assert '変更されること' in msg


def test_games_message_header_names_the_filters():
    msg = gl.build_games_message(releases_of(entry('Alpha')), TODAY, platform='Switch 2', days=14, period_label='今後2週間')
    assert 'Switch 2' in msg.splitlines()[0]
    assert '今後2週間' in msg.splitlines()[0]


def test_games_message_when_nothing_matches():
    msg = gl.build_games_message(releases_of(entry('Alpha', platforms=['PC'])), TODAY, platform='Switch')
    assert '見つかりませんでした' in msg


def test_games_message_stays_within_the_discord_limit_and_counts_the_rest():
    many = [entry(f'長いタイトルのゲーム その{i:03d}', '2026-11-01', platforms=['PC', 'Switch', 'Switch 2'],
                  genre='アクションアドベンチャー') for i in range(80)]
    msg = gl.build_games_message(releases_of(*many), TODAY)

    assert len(msg) <= 2000
    assert 'ほか' in msg and '件' in msg


# ====================================================
# 月曜の紹介
# ====================================================

def test_weekly_digest_is_empty_when_nothing_is_coming_soon():
    """近日発売が無い週に、空のセクションを送らない。"""
    rs = releases_of(entry('Far', '2027-01-15'), entry('Past', '2026-10-01'))
    assert gl.build_weekly_digest(TODAY, releases=rs) == ''


def test_weekly_digest_covers_the_next_two_weeks_with_notes():
    rs = releases_of(
        entry('Soon', '2026-10-22', note='注目ポイント'),
        entry('TooFar', '2026-11-03'),
    )
    msg = gl.build_weekly_digest(TODAY, releases=rs)
    assert 'Soon' in msg
    assert '注目ポイント' in msg
    assert 'TooFar' not in msg
    assert '/games' in msg


def test_weekly_digest_reads_the_files_by_default():
    write(gl.USER_FILE, [entry('FromFile', '2026-10-22')])
    assert 'FromFile' in gl.build_weekly_digest(TODAY)


# ====================================================
# 予約の状況
# ====================================================

def one(**extra):
    return releases_of(entry('Game', '2026-12-01', **extra))[0]


def test_preorder_text_is_empty_when_nothing_is_known():
    """載っていない作品は「予約できない」のではなく「未確認」。何も言わない。"""
    assert gl.preorder_text(one(), TODAY) == ''


def test_preorder_text_when_preorders_are_open():
    text = gl.preorder_text(one(preorder_start='2026-10-01'), TODAY)
    assert '予約受付中' in text
    assert '10/1' in text


def test_preorder_text_when_preorders_have_not_started():
    text = gl.preorder_text(one(preorder_start='2026-10-25'), TODAY)
    assert '10/25' in text and 'から' in text
    assert 'あと6日' in text


def test_preorder_note_is_appended_to_the_status():
    text = gl.preorder_text(one(preorder_start='2026-10-01', preorder_note='特典あり'), TODAY)
    assert '予約受付中' in text and '特典あり' in text


def test_preorder_note_alone_is_shown_without_a_start_date():
    assert gl.preorder_text(one(preorder_note='予約受付中（DL版）'), TODAY) == '予約受付中（DL版）'


def test_preorder_text_is_empty_once_the_game_is_released():
    r = releases_of(entry('Old', '2026-10-01', preorder_start='2026-08-01'))[0]
    assert gl.preorder_text(r, TODAY) == ''


def test_list_line_marks_preorder_availability_and_the_detail_view_explains_it():
    r = one(preorder_start='2026-10-01', preorder_note='特典あり')
    assert gl.format_release(r, TODAY).endswith('🛒')
    assert '特典あり' not in gl.format_release(r, TODAY)
    assert '🛒 予約受付中' in gl.format_release(r, TODAY, detail=True)


def test_list_line_has_no_cart_mark_without_preorder_info():
    assert '🛒' not in gl.format_release(one(), TODAY)


# ====================================================
# 気になる作品（ウォッチリスト）
# ====================================================

def test_watch_list_is_empty_when_no_file_exists():
    assert gl.load_watch() == []
    assert gl.watched_keys() == set()


def test_update_watch_saves_the_selection_and_reads_it_back():
    gl.update_watch(['A', 'B', 'C'], ['B', 'C'])
    assert gl.load_watch() == ['B', 'C']
    assert gl.watched_keys() == {'b', 'c'}


def test_deselecting_a_shown_title_removes_it():
    gl.update_watch(['A', 'B'], ['A', 'B'])
    gl.update_watch(['A', 'B'], ['A'])
    assert gl.load_watch() == ['A']


def test_titles_not_shown_on_the_screen_keep_their_registration():
    """⭕ 機種や期間で絞って見ているとき、画面に出ていない作品の登録まで外してはいけない。"""
    gl.update_watch(['A', 'B', 'C'], ['A', 'C'])
    gl.update_watch(['B'], ['B'])            # Bだけが見えている画面で、Bを足す
    assert set(gl.load_watch()) == {'A', 'B', 'C'}

    gl.update_watch(['B'], [])               # 同じ画面でBを外す。AとCはそのまま
    assert set(gl.load_watch()) == {'A', 'C'}


def test_update_watch_does_not_duplicate_titles_regardless_of_case():
    gl.update_watch(['Game'], ['Game'])
    gl.update_watch(['Other'], ['game'])
    assert [t.casefold() for t in gl.load_watch()].count('game') == 1


def test_a_corrupted_watch_file_is_treated_as_empty():
    with open(gl.WATCH_FILE, 'w', encoding='utf-8') as f:
        f.write('{ broken')
    assert gl.load_watch() == []


def test_watched_titles_get_a_star_in_the_list():
    rs = releases_of(entry('Watched'), entry('Plain'))
    msg = gl.build_games_message(rs, TODAY, watched={'watched'})
    lines = {l for l in msg.splitlines() if '**' in l}
    assert any('⭐' in l and 'Watched' in l for l in lines)
    assert not any('⭐' in l and 'Plain' in l for l in lines)


def test_watching_only_shows_just_the_watched_titles_with_details():
    rs = releases_of(entry('Watched', note='注目', preorder_note='予約受付中'), entry('Plain'))
    msg = gl.build_games_message(rs, TODAY, watched={'watched'}, only_watched=True)
    assert 'Watched' in msg and 'Plain' not in msg
    assert '注目' in msg and '🛒' in msg
    assert '気になるゲーム' in msg.splitlines()[0]


def test_watching_only_with_nothing_registered_explains_how_to_register():
    msg = gl.build_games_message(releases_of(entry('Plain')), TODAY, watched=set(), only_watched=True)
    assert '登録' in msg and '/games' in msg


# ====================================================
# 気になる作品の通知
# ====================================================

def alerts(*entries, watched=None):
    rs = releases_of(*entries)
    return gl.build_watch_alerts(TODAY, releases=rs,
                                 watched={e['title'].casefold() for e in entries} if watched is None else watched)


@pytest.mark.parametrize('release_date,expected', [
    ('2026-10-19', '本日発売'),
    ('2026-10-20', '明日発売'),
    ('2026-10-26', '1週間'),
])
def test_alert_on_the_seven_day_one_day_and_release_day(release_date, expected):
    assert expected in alerts(entry('Game', release_date))


@pytest.mark.parametrize('release_date', ['2026-10-21', '2026-10-25', '2026-10-27', '2026-11-30', '2026-10-18'])
def test_no_alert_on_other_days(release_date):
    """⭕ 毎朝1回だけ呼ばれる前提なので、対象日以外は何も言わない（毎日通知にならない）。"""
    assert alerts(entry('Game', release_date)) == ''


def test_alert_on_the_day_preorders_start():
    msg = alerts(entry('Game', '2026-12-01', preorder_start='2026-10-19', preorder_note='特典あり'))
    assert '予約開始' in msg
    assert '特典あり' in msg


def test_no_alert_for_titles_that_are_not_watched():
    assert alerts(entry('Game', '2026-10-20'), watched={'someone else'}) == ''


def test_no_alert_for_undated_titles():
    assert alerts(entry('Someday', None, release_label='2026年内')) == ''


def test_alert_follows_a_date_change_because_the_watch_is_by_title():
    """延期で発売日が変わっても、同じタイトルのまま新しい日付で通知される。"""
    rs = releases_of(entry('Game', '2026-11-20'))
    watched = {'game'}
    assert gl.build_watch_alerts(date(2026, 11, 19), releases=rs, watched=watched) != ''
    assert gl.build_watch_alerts(TODAY, releases=rs, watched=watched) == ''


def test_alert_lists_several_titles_at_once():
    msg = alerts(entry('One', '2026-10-20'), entry('Two', '2026-10-19'))
    assert 'One' in msg and 'Two' in msg


def test_alert_reads_the_watch_file_by_default():
    write(gl.SEED_FILE, {'releases': [entry('Game', '2026-10-20')]})
    assert gl.build_watch_alerts(TODAY) == ''
    gl.update_watch(['Game'], ['Game'])
    assert 'Game' in gl.build_watch_alerts(TODAY)


# ====================================================
# 同梱の初期データ（差し替えずに、実物を検査する）
# ====================================================

def real_seed():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'seed', 'game_releases.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_bundled_seed_has_no_unusable_entries():
    """⭕ 書き間違い（機種名のtypoや日付の形式）があると、そのエントリは黙って表示されなくなる。"""
    raw = real_seed()['releases']
    assert len(raw) == 22
    for e in raw:
        assert gl._normalize(e) is not None, e['title']


def test_bundled_seed_entries_are_unique_and_cite_a_source():
    raw = real_seed()['releases']
    keys = [(e['title'].casefold(), e.get('release_date')) for e in raw]
    assert len(keys) == len(set(keys))
    for e in raw:
        assert e.get('source', '').startswith('https://'), e['title']


def test_bundled_seed_preorder_info_has_a_valid_date_and_a_source():
    """予約の情報は、日付が読める形で、出典つきのものだけを載せる。"""
    with_preorder = [e for e in real_seed()['releases'] if 'preorder_start' in e or 'preorder_note' in e]
    assert with_preorder, '予約の情報が1件も無い'
    for e in with_preorder:
        if 'preorder_start' in e:
            assert gl._parse_date(e['preorder_start']) is not None, e['title']
        assert e.get('preorder_source', '').startswith('https://'), e['title']


def test_bundled_seed_declares_when_it_was_updated():
    assert gl._parse_date(real_seed().get('updated')) is not None
