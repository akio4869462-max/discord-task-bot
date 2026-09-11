"""多頭化（主戦馬＋併せ馬・セリ）のテスト。"""
import json
import random
from datetime import date

import pytest

import horse_logic as hl


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))


TODAY = date(2026, 9, 11)          # 金曜
RACE_DAY = date(2026, 9, 12)       # 土曜


def add_horse(data, name, sex='牝'):
    h = hl.new_horse(name=name, sex=sex, today=TODAY, rng=random.Random(len(data['horses'])))
    data['horses'].append(h)
    hl._bind(data)
    return h


def home(races):
    return next(r for r in races if r.get('travel', 0) == 0)


def solo():
    """1頭だけの厩舎（新規は3頭で始まるので、増やす挙動を見るテスト用）。"""
    data = hl.load_stable(TODAY)
    data['horses'] = data['horses'][:1]
    hl._bind(data)
    return data


# ====================================================
# データ構造と読み込み
# ====================================================
def test_new_stable_starts_with_three_horses_main_first():
    """⭕ 最初から3頭。能力は低くていいから頭数が欲しい、という要望。"""
    data = hl.load_stable(TODAY)
    assert len(data['horses']) == hl.MAX_HORSES
    assert data['current'] is data['horses'][0]
    assert data['main'] == data['selected'] == data['current']['id']
    assert data['stable_filled'] is True


def test_single_horse_data_is_migrated_into_horses_on_load():
    """⭕ 1頭だった頃の stable.json（current だけ）を読み替える。"""
    horse = hl.new_horse(name='キュウウマ', today=TODAY, rng=random.Random(1))
    old = {'generation': 3, 'current': horse, 'retired': [], 'stallions': [], 'funds': 500,
           'last_active_date': None, 'current_streak': 0}
    with open(hl.STABLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(old, f, ensure_ascii=False)

    data = hl.load_stable(TODAY)

    # 主戦は元の馬のまま、3頭まで埋まる（一度だけ）
    assert data['horses'][0]['name'] == 'キュウウマ' and len(data['horses']) == hl.MAX_HORSES
    assert data['main'] == data['selected'] == horse['id']
    assert data['current']['name'] == 'キュウウマ'
    assert data['current']['generation'] == 3
    # ⭕ 埋めた馬はその場で保存される。保存しないと読むたびに別のIDの馬になり、
    #    セレクトで選んだIDが見つからず「その馬はいません」になった（本番で実際に起きた）
    again = hl.load_stable(TODAY)
    assert [h['id'] for h in again['horses']] == [h['id'] for h in data['horses']]
    again['horses'].pop()
    hl.save_stable(again)
    assert len(hl.load_stable(TODAY)['horses']) == hl.MAX_HORSES - 1     # 2回目は埋めない


def test_save_drops_the_current_alias_and_reload_rebinds():
    data = solo()
    add_horse(data, 'ニトウメ')
    hl.select_horse(data, data['horses'][1]['id'])
    with open(hl.STABLE_FILE, encoding='utf-8') as f:
        raw = json.load(f)
    assert 'current' not in raw and len(raw['horses']) == 2

    again = hl.load_stable(TODAY)
    assert again['current']['name'] == 'ニトウメ'
    assert again['current'] is next(h for h in again['horses'] if h['name'] == 'ニトウメ')


def test_select_and_main_are_independent():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    hl.select_horse(data, second['id'], save=False)
    assert data['current'] is second and hl.main_horse(data) is first
    hl.set_main(data, second['id'], save=False)
    assert hl.is_main(data, second) and not hl.is_main(data, first)
    with pytest.raises(ValueError):
        hl.select_horse(data, 'nobody', save=False)


# ====================================================
# 調教：主戦に全部、併せ馬に半分
# ====================================================
def test_training_goes_fully_to_the_main_and_half_to_the_others():
    data = solo()
    main = data['horses'][0]
    sub = add_horse(data, 'アワセウマ')
    hl.select_horse(data, sub['id'], save=False)          # 見ているのは併せ馬でも
    result = hl.add_growth('programming', 100, today=TODAY, data=data, save=False)
    assert main['growth']['speed'] == pytest.approx(60)
    assert sub['growth']['speed'] == pytest.approx(60 * hl.SUB_SHARE)
    assert result['horse'] is main                        # 報告は主戦の成長


def test_backfill_also_feeds_the_sub_horses():
    data = solo()
    sub = add_horse(data, 'アワセウマ')
    hl.backfill('typing', [date(2026, 9, 8), date(2026, 9, 9)], data=data, save=False)
    assert sub['growth']['dash'] == pytest.approx(hl.TYPING_MINUTES * 2 * 0.7 * hl.SUB_SHARE)


# ====================================================
# 出走：馬ごとに登録、同じレースは不可、夜に全馬走る
# ====================================================
def test_each_horse_enters_its_own_race_and_the_same_race_is_refused():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    day, races = hl.available_races(data, on=TODAY, horse=first)
    hl.enter_race(home(races), data=data, save=False, horse=first)

    _, races2 = hl.available_races(data, on=TODAY, horse=second)
    assert first['entry']['id'] not in {r['id'] for r in races2}       # 一覧から消える
    with pytest.raises(ValueError, match='2頭出し'):
        hl.enter_race(first['entry'], data=data, save=False, horse=second)


def test_run_entries_runs_every_entered_horse_main_first():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    hl.set_main(data, second['id'], save=False)
    _, r1 = hl.available_races(data, on=TODAY, horse=first)
    hl.enter_race(home(r1), data=data, save=False, horse=first)
    _, r2 = hl.available_races(data, on=TODAY, horse=second)
    hl.enter_race(home(r2), data=data, save=False, horse=second)

    outcomes = hl.run_entries(data=data, today=RACE_DAY, save=False)

    assert [o['horse_name'] for o in outcomes] == ['ニトウメ', first['name']]   # 主戦が先
    assert first['record']['starts'] == 1 and second['record']['starts'] == 1
    assert first['entry'] is None and second['entry'] is None
    assert hl.run_entries(data=data, today=RACE_DAY, save=False) == []


def test_sub_with_a_breeding_plan_is_replaced_by_its_foal():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    hl.select_horse(data, second['id'], save=False)
    second['record']['starts'] = hl.RETIRE_STARTS
    second['slots'] = hl.RETIRE_STARTS
    second['generation'] = 2
    partner = dict(first, sex='牡' if second['sex'] == '牝' else '牝')
    second['breeding_plan'] = {'partner': partner, 'fee': 0, 'foal_name': 'ヨヤクノコ'}

    hl.retire(data, RACE_DAY, horse=second)

    assert len(data['horses']) == 2
    foal = data['horses'][1]
    assert foal['name'] == 'ヨヤクノコ' and foal['generation'] == 3
    assert data['selected'] == foal['id'] and data['current'] is foal
    assert data['main'] == first['id']                                 # 主戦は替わらない
    assert data['retired'][0]['name'] == 'ニトウメ'


def test_sub_without_a_plan_frees_its_slot_but_main_always_continues():
    """⭕ 全部に仔を置くとセリの出番が来ない。予約の無い併せ馬は引退で枠が空く。"""
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    hl.select_horse(data, second['id'], save=False)
    second['slots'] = hl.RETIRE_STARTS

    msg = hl.retire(data, RACE_DAY, horse=second)

    assert '枠が空きました' in msg
    assert [h['id'] for h in data['horses']] == [first['id']]
    assert data['selected'] == first['id'] and data['current'] is first

    first['slots'] = hl.RETIRE_STARTS
    hl.retire(data, RACE_DAY, horse=first)                              # 主戦は予約が無くても仔が継ぐ
    assert len(data['horses']) == 1 and data['main'] == data['horses'][0]['id']


# ====================================================
# セリ
# ====================================================
def test_auction_lists_six_foals_and_is_fixed_within_the_week():
    data = solo()
    lots = hl.auction(data, TODAY)
    assert len(lots) == hl.AUCTION_SIZE
    assert all(lot['price'] > 0 and lot['foal']['growth_type'] in hl.GROWTH_TYPES for lot in lots)
    assert [l['foal']['name'] for l in hl.auction(data, TODAY)] == [l['foal']['name'] for l in lots]
    assert [l['foal']['name'] for l in hl.auction(data, date(2026, 9, 14))] != [l['foal']['name'] for l in lots]


def test_buying_a_foal_adds_a_sub_horse_and_charges():
    data = solo()
    data['funds'] = 1_000_000
    lot = hl.auction(data, TODAY)[0]

    foal, price = hl.buy_foal(lot['key'], name='カッタコ', data=data, today=TODAY, save=False)

    assert price == lot['price'] and data['funds'] == 1_000_000 - price
    assert len(data['horses']) == 2 and data['horses'][1]['name'] == 'カッタコ'
    assert not hl.is_main(data, data['horses'][1])
    assert foal['pedigree']['sire']['name'] == lot['sire']


def test_buying_is_refused_when_full_or_broke():
    data = solo()
    data['funds'] = 0
    lot = hl.auction(data, TODAY)[0]
    with pytest.raises(ValueError, match='資金'):
        hl.buy_foal(lot['key'], data=data, today=TODAY, save=False)
    data['funds'] = 10 ** 9
    add_horse(data, 'ニトウメ')
    add_horse(data, 'サントウメ')
    with pytest.raises(ValueError, match='頭まで'):
        hl.buy_foal(lot['key'], data=data, today=TODAY, save=False)


# ====================================================
# 表示
# ====================================================
def test_stable_view_marks_the_role_and_lists_the_others():
    data = solo()
    add_horse(data, 'アワセウマ')
    text = hl.format_horse(data, TODAY)
    assert '・主戦）' in text and '他の馬' in text and 'アワセウマ（未勝利・併せ馬）' in text


def test_race_day_notice_covers_every_horse():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    _, races = hl.available_races(data, on=RACE_DAY, horse=first)
    hl.enter_race(home(races), data=data, save=False, horse=first)
    text = hl.format_race_day_notice(data=data, today=RACE_DAY)
    assert first['name'] in text and '20:00に発走' in text
    assert 'ニトウメ' in text and '出走登録がありません' in text


def test_weekly_summary_lists_races_of_every_horse():
    data = solo()
    first = data['horses'][0]
    second = add_horse(data, 'ニトウメ')
    for h in (first, second):
        _, races = hl.available_races(data, on=TODAY, horse=h)
        hl.enter_race(home(races), data=data, save=False, horse=h)
    hl.run_entries(data=data, today=RACE_DAY, save=False)
    msg = hl.get_weekly_summary(data=data, today=date(2026, 9, 14), save=False)
    assert '今週の出走: 2戦' in msg and 'ニトウメ' in msg and '主戦' in msg and '併せ馬' in msg
