"""配合（horse_logic の 🧬 部分）のテスト。

市場は小さな合成プールで検証し、本物のプールは「読めて異性が出る」ことだけ確かめる。
"""
import json
import random
from datetime import date

import pytest

import horse_logic as hl


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))
    return tmp_path


TODAY = date(2026, 9, 11)
RACE_DAY = date(2026, 9, 12)


def grown(data, hours, today=TODAY):
    minutes = hours * 60 / len(hl.PARAMS)
    for category, weights in hl.ACTIVITY_PARAMS.items():
        share = sum(weights.values())
        hl.add_growth(category, minutes * len(weights) / share, today=today,
                      data=data, save=False)
    return data


def _pool_horse(name, sex, cls, ability, apt=None, sire='チチウマ', bms='ハハチチウマ'):
    return {'name': name, 'sex': sex, 'class': cls, 'z': 0.0,
            'params': {k: ability for k in hl.PARAMS},
            'aptitude': apt or {'turf': 'A', 'dirt': 'C', 'sprint': 'D', 'mile': 'C',
                                'middle': 'B', 'long': 'A'},
            'sire': sire, 'bms': bms}


# 下級・中級・上級にそれぞれ2頭以上いる小さなプール。
TINY_POOL = {'horses': [
    _pool_horse('シタノメスイチ', '牝', '未勝利', 200), _pool_horse('シタノメスニ', '牝', '1勝', 300),
    _pool_horse('シタノメスサン', '牝', '2勝', 380),
    _pool_horse('ナカノメスイチ', '牝', '3勝', 470), _pool_horse('ナカノメスニ', '牝', 'G3', 520),
    _pool_horse('ウエノメスイチ', '牝', 'G2', 560), _pool_horse('ウエノメスニ', '牝', 'G1', 700),
    _pool_horse('オスウマ', '牡', 'G1', 750), _pool_horse('センバ', 'セ', 'G1', 750),
]}


def stable_with_stallion(hours=30, sex='牡'):
    """現役馬が sex で、異性の引退馬を1頭持ち、資金もある厩舎。"""
    data = grown(hl.load_stable(TODAY), hours)
    data['current']['sex'] = sex
    data['current']['record']['starts'] = hl.BREEDING_OPEN_STARTS
    data['funds'] = 100_000
    other = '牝' if sex == '牡' else '牡'
    data['stallions'].append({
        'id': 'stud-1', 'name': 'ジカノウマ', 'sex': other, 'class': 'G1',
        'params': {k: 800 for k in hl.PARAMS},
        'aptitude': {'turf': 'C', 'dirt': 'A', 'sprint': 'A', 'mile': 'B', 'middle': 'C', 'long': 'D'},
        'record': {'starts': 20, 'win': 8, 'place': 10, 'show': 12, 'prize': 50000},
        'stud_value': 1.7, 'pedigree': {'sire': None, 'dam': None},
    })
    return data


def g1_mare(data):
    return next(c for c in hl.market(data, pool=TINY_POOL) if c['class'] == 'G1')


# ====================================================
# 市場
# ====================================================
def test_market_shows_two_of_each_tier_of_the_opposite_sex():
    m = hl.market(stable_with_stallion(), pool=TINY_POOL)

    assert len(m) == 6
    assert all(c['sex'] == '牝' for c in m)                     # 牡の現役馬には牝だけ
    tiers = [next(i for i, t in enumerate(hl.MARKET_TIERS) if c['class'] in t) for c in m]
    assert tiers == [0, 0, 1, 1, 2, 2]


def test_market_excludes_geldings():
    names = {c['name'] for c in hl.market(stable_with_stallion(sex='牝'), pool=TINY_POOL)}
    assert 'オスウマ' in names and 'センバ' not in names


def test_market_is_fixed_within_a_generation():
    """⭕ 見るたびに入れ替わると比較できない。現役馬のidをシードにする。"""
    data = stable_with_stallion()
    assert hl.market(data, pool=TINY_POOL) == hl.market(data, pool=TINY_POOL)


def test_market_uses_the_real_pool_by_default():
    m = hl.market(stable_with_stallion())
    assert len(m) == 6 and all(c['sex'] == '牝' for c in m)


def test_stud_fee_follows_the_prize_table():
    assert hl.stud_fee('G1') == 15000 * hl.STUD_FEE_RATIO
    assert hl.stud_fee('未勝利') < hl.stud_fee('OP') < hl.stud_fee('G1')


# ====================================================
# 相手の一覧と予約
# ====================================================
def test_candidates_list_own_retired_horses_for_free():
    cands = hl.breeding_candidates(stable_with_stallion(), pool=TINY_POOL)

    own = [c for c in cands if c['source'] == 'own']
    assert [c['name'] for c in own] == ['ジカノウマ']
    assert own[0]['fee'] == 0 and own[0]['key'] == 'own:stud-1'
    assert all(c['fee'] > 0 for c in cands if c['source'] == 'market')


def test_candidates_skip_own_horses_of_the_same_sex():
    data = stable_with_stallion(sex='牝')                     # 引退馬は牡
    data['stallions'].append(dict(data['stallions'][0], id='stud-2', name='メスノウマ', sex='牝'))
    own = [c['name'] for c in hl.breeding_candidates(data, pool=TINY_POOL) if c['source'] == 'own']
    assert own == ['ジカノウマ']


def test_breeding_opens_after_fifteen_starts():
    data = stable_with_stallion()
    data['current']['record']['starts'] = hl.BREEDING_OPEN_STARTS - 3
    ok, reason = hl.breeding_status(data['current'])
    assert not ok and 'あと3戦' in reason
    with pytest.raises(ValueError):
        hl.reserve_breeding('own:stud-1', data=data, save=False, pool=TINY_POOL)

    data['current']['record']['starts'] = hl.BREEDING_OPEN_STARTS
    assert hl.breeding_status(data['current']) == (True, '')


def test_reserving_a_market_horse_charges_the_fee():
    data = stable_with_stallion()
    mare = g1_mare(data)

    plan = hl.reserve_breeding(mare['key'], foal_name='ユメノコ', data=data, save=False, pool=TINY_POOL)

    assert data['funds'] == 100_000 - hl.stud_fee('G1')
    assert plan['partner']['name'] == mare['name'] and plan['foal_name'] == 'ユメノコ'
    assert hl.breeding_status(data['current']) == (False, '予約済み')


def test_reserving_fails_without_enough_funds_and_changes_nothing():
    data = stable_with_stallion()
    data['funds'] = 10
    with pytest.raises(ValueError, match='資金'):
        hl.reserve_breeding(g1_mare(data)['key'], data=data, save=False, pool=TINY_POOL)
    assert data['funds'] == 10 and data['current']['breeding_plan'] is None


def test_reserving_an_unknown_partner_fails():
    with pytest.raises(ValueError):
        hl.reserve_breeding('market:99', data=stable_with_stallion(), save=False, pool=TINY_POOL)


def test_cancelling_refunds_the_fee():
    data = stable_with_stallion()
    hl.reserve_breeding(g1_mare(data)['key'], data=data, save=False, pool=TINY_POOL)

    hl.cancel_breeding(data, save=False)

    assert data['funds'] == 100_000
    assert data['current']['breeding_plan'] is None


# ====================================================
# 誕生
# ====================================================
def test_foal_is_born_from_the_plan_at_retirement():
    data = stable_with_stallion()
    sire = data['current']
    sire_name, sire_growth = sire['name'], dict(sire['growth'])
    hl.reserve_breeding('own:stud-1', foal_name='ユメノコ', data=data, save=False, pool=TINY_POOL)
    data['current']['record']['starts'] = hl.RETIRE_STARTS - 1

    msg = hl.retire(data, RACE_DAY)

    foal = data['current']
    assert foal['name'] == 'ユメノコ' and 'ユメノコ' in msg
    assert hl._ped_name(foal['pedigree']['sire']) == sire_name
    assert hl._ped_name(foal['pedigree']['dam']) == 'ジカノウマ'
    assert foal['breeding_plan'] is None                       # 予約は消費される
    # 能力は両親の積み上げの平均 × 10% × 種牡馬価値の平均
    dam_minutes = hl.minutes_for(800)
    value = (hl.stud_value(sire) + 1.7) / 2
    for k in hl.PARAMS:
        expected = (sire_growth[k] + dam_minutes) / 2 * hl.INHERIT_RATE * value
        assert foal['growth'][k] == pytest.approx(expected)


def test_without_a_plan_the_foal_has_one_parent_as_before():
    data = grown(hl.load_stable(TODAY), 20)
    parent = data['current']['name']
    hl.retire(data, RACE_DAY)
    names = [hl._ped_name(data['current']['pedigree'][s]) for s in ('sire', 'dam')]
    assert parent in names and '－' in names


def test_foal_aptitude_comes_from_one_of_the_parents():
    """⭕ 配合の核。適性は項目ごとに父か母のどちらかから来て、ときどき1段ずれる。"""
    sire = {'name': 'S', 'sex': '牡', 'growth': {k: 100 for k in hl.PARAMS},
            'aptitude': {k: 'A' for k in hl.APTITUDE_KEYS}, 'record': {'win': 0}, 'class': 'OP'}
    dam = {'name': 'D', 'sex': '牝', 'growth': {k: 100 for k in hl.PARAMS},
           'aptitude': {k: 'D' for k in hl.APTITUDE_KEYS}, 'record': {'win': 0}, 'class': 'OP'}
    counts = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
    for seed in range(300):
        foal = hl.breed(sire, dam, today=RACE_DAY, rng=random.Random(seed))
        for g in foal['aptitude'].values():
            counts[g] += 1
    total = sum(counts.values())
    # 親由来(A/D)が大半で、変異(B/C)が APTITUDE_MUTATION 程度
    assert (counts['B'] + counts['C']) / total == pytest.approx(hl.APTITUDE_MUTATION, abs=0.03)
    assert abs(counts['A'] - counts['D']) / total < 0.1       # 父母どちらにも偏らない


def test_breed_accepts_parents_in_either_order():
    sire = {'name': 'S', 'sex': '牡', 'growth': {k: 100 for k in hl.PARAMS},
            'aptitude': {k: 'A' for k in hl.APTITUDE_KEYS}, 'record': {'win': 0}, 'class': 'OP'}
    dam = {'name': 'D', 'sex': '牝', 'growth': {k: 300 for k in hl.PARAMS},
           'aptitude': {k: 'B' for k in hl.APTITUDE_KEYS}, 'record': {'win': 0}, 'class': 'OP'}
    a = hl.breed(sire, dam, today=RACE_DAY, rng=random.Random(1))
    b = hl.breed(dam, sire, today=RACE_DAY, rng=random.Random(1))
    assert a['pedigree'] == b['pedigree']
    assert hl._ped_name(a['pedigree']['sire']) == 'S'


def test_market_parent_carries_its_sire_and_broodmare_sire_into_the_pedigree():
    data = stable_with_stallion()
    mare = g1_mare(data)
    hl.reserve_breeding(mare['key'], data=data, save=False, pool=TINY_POOL)
    data['current']['record']['starts'] = hl.RETIRE_STARTS - 1
    hl.retire(data, RACE_DAY)

    dam = data['current']['pedigree']['dam']
    assert dam['name'] == mare['name']
    assert dam['sire']['name'] == 'チチウマ'
    assert dam['dam']['sire']['name'] == 'ハハチチウマ'          # 母父は母の父として残る


def test_pedigree_is_trimmed_to_four_generations():
    node = {'name': 'g0', 'sire': None, 'dam': None}
    for i in range(1, 8):
        node = {'name': f'g{i}', 'sire': node, 'dam': None}
    trimmed = hl._trim_pedigree(node)
    depth = 0
    while trimmed:
        depth += 1
        trimmed = trimmed['sire']
    assert depth == hl.PEDIGREE_DEPTH


def test_retired_horse_keeps_its_pedigree_for_later_matings():
    data = stable_with_stallion()
    hl.reserve_breeding('own:stud-1', data=data, save=False, pool=TINY_POOL)
    data['current']['record']['starts'] = hl.RETIRE_STARTS - 1
    hl.retire(data, RACE_DAY)

    stud = data['stallions'][-1]                               # 引退した父
    assert stud['growth'] and stud['id'] and stud['pedigree'] == {'sire': None, 'dam': None}


# ====================================================
# 資金
# ====================================================
def test_prize_money_also_fills_the_stable_funds():
    data = grown(hl.load_stable(TODAY), 12)
    _, races = hl.available_races(data, on=TODAY)
    hl.enter_race(races[0], data=data, save=False)
    hl.run_entry(data=data, today=RACE_DAY, save=False)
    assert data['funds'] == data['current']['record']['prize']


def test_old_data_gets_funds_from_past_prize_money():
    """⭕ 資金は配合で初めて使い道ができた。既存データは賞金の合計で補う（読み込み時移行）。"""
    stable = hl._default_stable(TODAY)
    del stable['funds']
    stable['current']['record']['prize'] = 1200
    stable['current']['pedigree'] = {'sire': 'チチウマ', 'dam': '－'}      # 旧形式
    stable['retired'].append({'name': 'インタイ', 'id': 'r1', 'record': {'prize': 3000},
                              'pedigree': {'sire': '－', 'dam': '－'}})
    stable['stallions'].append({'name': 'インタイ', 'sex': '牝', 'class': '1勝',
                                'params': {k: 300 for k in hl.PARAMS}, 'aptitude': {},
                                'record': {'prize': 3000}, 'stud_value': 1.0})
    with open(hl.STABLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(stable, f, ensure_ascii=False)

    data = hl.load_stable(TODAY)

    assert data['funds'] == 4200
    assert data['current']['pedigree'] == {'sire': {'name': 'チチウマ', 'sire': None, 'dam': None},
                                           'dam': None}
    assert data['stallions'][0]['id'] == 'r1'                 # 引退馬からidを引き継ぐ
    assert data['stallions'][0]['pedigree'] == {'sire': None, 'dam': None}


# ====================================================
# 表示
# ====================================================
def test_format_candidates_shows_origin_and_price():
    text = hl.format_candidates(stable_with_stallion(), pool=TINY_POOL)
    assert '[自家]' in text and '無料' in text
    assert '[市場]' in text and '万円' in text


def test_format_candidates_explains_when_closed():
    data = stable_with_stallion()
    data['current']['record']['starts'] = 3
    assert 'あと12戦' in hl.format_candidates(data, pool=TINY_POOL)


def test_stable_view_shows_funds_plan_and_pedigree():
    data = stable_with_stallion()
    hl.reserve_breeding('own:stud-1', data=data, save=False, pool=TINY_POOL)
    assert '厩舎資金 100,000万円' in hl.format_horse(data, TODAY)
    assert '配合予約: ジカノウマ' in hl.format_horse(data, TODAY)

    data['current']['record']['starts'] = hl.RETIRE_STARTS - 1
    hl.retire(data, RACE_DAY)
    assert 'ジカノウマ' in hl.format_pedigree(data['current'])
    assert '血統: 父' in hl.format_horse(data, RACE_DAY)
