"""海外遠征（月1回・G1 2勝で解放・出走枠2つ・次の開催日は休み）のテスト。"""
from datetime import date

import pytest

import horse_logic as hl
from race_sim import calendar as cal
from race_sim import engine, rivals


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))


TODAY = date(2026, 9, 11)                # 金曜
OVERSEAS_DAY = date(2026, 10, 3)         # 10月最初の土曜
PLAIN_SATURDAY = date(2026, 10, 10)
NEXT_WEDNESDAY = date(2026, 10, 7)


def g1_horse(g1_wins=2, hours=40):
    """G1クラスで、G1を g1_wins 勝している馬の厩舎。資金もある。"""
    data = hl.load_stable(TODAY)
    minutes = hours * 60 / len(hl.PARAMS)
    for category, weights in hl.ACTIVITY_PARAMS.items():
        hl.add_growth(category, minutes * len(weights) / sum(weights.values()),
                      today=TODAY, data=data, save=False)
    horse = data['current']
    horse['class'] = 'G1'
    horse['record'].update({'starts': 10, 'win': 7 + g1_wins})
    horse['history'] = [{'class': 'G1', 'finish': 1, 'date': '2026-09-05', 'race': 'x',
                         'course': '東京', 'surface': '芝', 'distance': 2000, 'field': 16}
                        for _ in range(g1_wins)]
    data['funds'] = 50_000
    return data


def overseas_in(races):
    return [r for r in races if r.get('overseas')]


# ====================================================
# 番組表
# ====================================================
def test_overseas_day_is_the_first_saturday_of_the_month():
    assert cal.is_overseas_day(OVERSEAS_DAY)
    assert not cal.is_overseas_day(PLAIN_SATURDAY)
    assert not cal.is_overseas_day(date(2026, 10, 1))          # 木曜


def test_overseas_offers_only_on_overseas_days():
    assert cal.overseas_offers(PLAIN_SATURDAY) == []
    races = cal.overseas_offers(OVERSEAS_DAY)
    assert races and all(r['overseas'] and r['class'] == 'G1' for r in races)
    assert all(r['course'] == cal.overseas_destination(OVERSEAS_DAY)['venue'] for r in races)


def test_destination_rotates_by_month():
    venues = {cal.overseas_destination(date(2026, m, 1))['venue'] for m in range(1, 13)}
    assert venues == {d['venue'] for d in cal.OVERSEAS}


def test_overseas_race_is_expensive_and_lucrative():
    race = cal.overseas_offers(OVERSEAS_DAY)[0]
    assert race['travel'] > max(cal.TRAVEL_COST.values())
    assert race['prize'] > cal.CLASS_INFO['G1']['prize']


def test_overseas_race_runs_on_a_proxy_course():
    """⭕ 較正データはJRAのものしか無い。基準タイムは proxy_course から借り、
       表示用の course は「香港」のまま。"""
    race = cal.overseas_offers(OVERSEAS_DAY)[0]
    proxy = dict(race, course=race['proxy_course'])
    del proxy['proxy_course']
    assert engine.base_time(race) == pytest.approx(engine.base_time(proxy))
    assert race['course'] not in engine.load_baseline()['base'].__repr__()


def test_overseas_rivals_are_stronger_than_domestic_g1():
    race = cal.overseas_offers(OVERSEAS_DAY)[0]
    domestic = dict(race, rival_boost=0)
    abroad = rivals.build_field(race, size=12, seed=7)
    home = rivals.build_field(domestic, size=12, seed=7)
    mean = lambda f: sum(sum(e['params'].values()) / 6 for e in f) / len(f)
    assert mean(abroad) > mean(home) + cal.OVERSEAS_RIVAL_BOOST * 0.8


# ====================================================
# 解放条件
# ====================================================
def test_overseas_needs_two_g1_wins():
    assert not hl.overseas_eligible(g1_horse(g1_wins=1)['current'])
    assert hl.overseas_eligible(g1_horse(g1_wins=2)['current'])


def test_eligible_horse_sees_overseas_races_only_on_overseas_days():
    data = g1_horse()
    _, races = hl.available_races(data, on=OVERSEAS_DAY)
    assert overseas_in(races) and any(not r.get('overseas') for r in races)    # 国内も残る
    _, races = hl.available_races(data, on=PLAIN_SATURDAY)
    assert not overseas_in(races)


def test_ineligible_horse_never_sees_overseas_races():
    _, races = hl.available_races(g1_horse(g1_wins=1), on=OVERSEAS_DAY)
    assert not overseas_in(races)


def test_second_g1_win_announces_the_unlock():
    data = g1_horse(g1_wins=1)
    race = dict(cal.offers('G1', PLAIN_SATURDAY)[0])
    mine = {'finish': 1, 'time': 118.0, 'last3f': 34.0, 'passing': [3, 3], 'style': '先行'}
    events = hl._apply_result(data, race, mine, PLAIN_SATURDAY, 16)
    assert any('海外遠征' in e for e in events)


# ====================================================
# 出走枠と休み
# ====================================================
def run_overseas(data, finish=1):
    race = cal.overseas_offers(OVERSEAS_DAY)[0]
    mine = {'finish': finish, 'time': 118.0, 'last3f': 34.0, 'passing': [3, 3], 'style': '先行'}
    return race, hl._apply_result(data, race, mine, OVERSEAS_DAY, 14)


def test_overseas_race_uses_two_slots_but_counts_as_one_start():
    """⭕ 引退は枠で数える。海外は2枠使うので「1走減る週」が本当の費用になる。"""
    data = g1_horse()
    horse = data['current']
    before_slots, before_starts = hl.slots_used(horse), horse['record']['starts']
    run_overseas(data)
    assert horse['record']['starts'] == before_starts + 1
    assert hl.slots_used(horse) == before_slots + hl.OVERSEAS_SLOTS


def test_after_overseas_the_next_race_day_is_off():
    data = g1_horse()
    run_overseas(data)
    horse = data['current']
    assert hl.rest_reason(horse, NEXT_WEDNESDAY)
    assert hl.available_races(data, on=NEXT_WEDNESDAY)[1] == []
    assert hl.rest_reason(horse, PLAIN_SATURDAY) is None
    assert hl.available_races(data, on=PLAIN_SATURDAY)[1]


def test_overseas_win_does_not_change_class_but_pays_and_raises_stud_value():
    data = g1_horse()
    horse = data['current']
    funds_before = data['funds']
    race, events = run_overseas(data, finish=1)
    assert horse['class'] == 'G1'
    assert any('海外G1制覇' in e for e in events)
    assert data['funds'] == funds_before + race['prize']
    assert hl.stud_value(horse) == pytest.approx(1.0 + 0.05 * horse['record']['win'] + hl.OVERSEAS_STUD_BONUS)


def test_domestic_g1_win_keeps_the_smaller_bonus():
    horse = g1_horse()['current']
    assert hl.stud_value(horse) == pytest.approx(1.0 + 0.05 * horse['record']['win'] + 0.30)


def test_entering_overseas_charges_the_travel_cost():
    data = g1_horse()
    _, races = hl.available_races(data, on=OVERSEAS_DAY)
    race = overseas_in(races)[0]
    hl.enter_race(race, data=data, save=False)
    assert data['funds'] == 50_000 - race['travel']
    hl.cancel_entry(data=data, save=False)
    assert data['funds'] == 50_000                               # 取り消せば戻る
    data['funds'] = race['travel'] - 1
    with pytest.raises(ValueError, match='遠征費'):
        hl.enter_race(race, data=data, save=False)


def test_overseas_race_can_be_simulated_end_to_end():
    data = g1_horse()
    _, races = hl.available_races(data, on=OVERSEAS_DAY)
    hl.enter_race(overseas_in(races)[0], data=data, save=False)
    out = hl.run_entry(data=data, today=OVERSEAS_DAY, save=False)
    assert 1 <= out['finish'] <= len(out['result']['horses'])
    assert data['current']['history'][-1]['overseas'] is True


# ====================================================
# 告知と表示
# ====================================================
def test_race_list_marks_overseas_races():
    data = g1_horse()
    day, races = hl.available_races(data, on=OVERSEAS_DAY)
    text = hl.format_races(day, races)
    assert '🌏' in text and '遠征費' in text


def test_morning_notice_mentions_the_overseas_day():
    data = g1_horse()
    assert '海外遠征日' in hl.format_race_day_notice(data=data, today=OVERSEAS_DAY)
    assert '来週の土曜は海外遠征日' in hl.format_race_day_notice(data=data, today=date(2026, 9, 26))
    assert '海外' not in hl.format_race_day_notice(data=data, today=PLAIN_SATURDAY)


def test_morning_notice_tells_an_ineligible_horse_the_condition():
    text = hl.format_race_day_notice(data=g1_horse(g1_wins=1), today=OVERSEAS_DAY)
    assert '出られません' in text and '2勝で解放' in text


def test_morning_notice_explains_the_rest_day():
    data = g1_horse()
    run_overseas(data)
    assert '戻る途中' in hl.format_race_day_notice(data=data, today=NEXT_WEDNESDAY)
