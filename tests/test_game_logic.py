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
    """⭕ seed と data の両方を差し替える。片方だけだと実データを巻き込む。"""
    monkeypatch.setattr(gl, 'SEED_FILE', str(tmp_path / 'seed.json'))
    monkeypatch.setattr(gl, 'USER_FILE', str(tmp_path / 'user.json'))


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


def test_note_is_shown_only_when_asked():
    r = releases_of(entry('Game', note='ここが見どころ'))[0]
    assert 'ここが見どころ' not in gl.format_release(r, TODAY)
    assert 'ここが見どころ' in gl.format_release(r, TODAY, with_note=True)


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


def test_bundled_seed_declares_when_it_was_updated():
    assert gl._parse_date(real_seed().get('updated')) is not None
