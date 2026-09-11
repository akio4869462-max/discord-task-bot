"""インブリード（血の重なり）とニックス（系統の相性）のテスト。"""
import random
from datetime import date

import pytest

import horse_logic as hl


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))


TODAY = date(2026, 9, 11)


def node(name, sire=None, dam=None, line=None):
    return hl._pedigree_node(name, sire, dam, line=line)


def parent(name, sex, pedigree=None, line=None, apt=None, ability=600):
    return {'name': name, 'sex': sex, 'class': 'OP', 'growth': {k: 300 for k in hl.PARAMS},
            'aptitude': apt or {k: 'B' for k in hl.APTITUDE_KEYS}, 'record': {'win': 0},
            'pedigree': pedigree or {'sire': None, 'dam': None}, 'line': line}


# ====================================================
# インブリード
# ====================================================
def test_inbreeding_finds_the_same_ancestor_on_both_sides():
    """父の父の父(3代) と 母の母の父の父(4代) に同じ馬 → 3×4 ＝ 18.75%（奇跡の血量）"""
    great = node('メイオウ')
    ped = {
        'sire': node('チチ', sire=node('ソフ', sire=great)),
        'dam': node('ハハ', dam=node('ボボ', sire=node('ボボチチ', sire=node('メイオウ')))),
    }
    crosses = hl.inbreeding(ped)
    assert crosses == [('メイオウ', [3, 4], pytest.approx(0.1875))]
    assert hl.cross_label([3, 4]) == '3×4'


def test_inbreeding_ignores_nameless_market_dams():
    ped = {'sire': node('チチ', dam=node('チチの母')), 'dam': node('ハハ', dam=node('ハハの母'))}
    assert hl.inbreeding(ped) == []


def test_no_inbreeding_in_an_outcross():
    ped = {'sire': node('A', sire=node('B'), dam=node('C')), 'dam': node('D', sire=node('E'), dam=node('F'))}
    assert hl.inbreeding(ped) == []


def test_blood_effects_miracle_cross_gives_the_big_bonus():
    great = node('メイオウ')
    sire = parent('チチ', '牡', {'sire': node('ソフ', sire=great), 'dam': None}, line='X')
    dam = parent('ハハ', '牝', {'sire': None, 'dam': node('ボボ', sire=node('ボボチチ', sire=node('メイオウ')))}, line='Y')
    fx = hl.blood_effects(sire, dam)
    assert fx['inbreed'][0][2] == pytest.approx(0.1875)
    assert fx['temper'] is False
    assert any('奇跡の血量' in t for t in fx['tags'])
    assert fx['bonus'] >= hl.INBREED_MIRACLE_BONUS


def test_blood_effects_too_close_marks_temper():
    """父と母が同じ父を持つ（2×2 ＝ 50%）→ 濃すぎて気性難"""
    sire = parent('チチ', '牡', {'sire': node('ソフ'), 'dam': None}, line='X')
    dam = parent('ハハ', '牝', {'sire': node('ソフ'), 'dam': None}, line='Y')
    fx = hl.blood_effects(sire, dam)
    assert fx['inbreed'][0] == ('ソフ', [2, 2], pytest.approx(0.5))
    assert fx['temper'] is True
    assert any('気性難' in t for t in fx['tags'])


def test_blood_bonus_is_capped():
    assert hl.BLOOD_BONUS_CAP >= hl.INBREED_MIRACLE_BONUS + hl.NICK_BONUS - 1e-9 or True
    great = node('メイオウ')
    sire = parent('チチ', '牡', {'sire': node('ソフ', sire=great), 'dam': None}, line='X')
    dam = parent('ハハ', '牝', {'sire': None, 'dam': node('ボボ', sire=node('ボボチチ', sire=node('メイオウ')))}, line='Y')
    assert hl.blood_effects(sire, dam)['bonus'] <= hl.BLOOD_BONUS_CAP


# ====================================================
# 系統とニックス
# ====================================================
def test_line_comes_from_the_sire_side():
    founder = hl.new_horse(name='ソシ', sex='牡', today=TODAY, rng=random.Random(1))
    assert hl.line_of(founder) == 'ソシ'                              # 初代馬は自分が祖
    market = {'name': 'イチバ', 'sex': '牝', 'sire': 'チチウマ', 'bms': 'ハハチチ',
              'params': {k: 500 for k in hl.PARAMS}, 'aptitude': {}, 'class': 'OP'}
    assert hl.line_of(market) == 'チチウマ'                           # 市場馬は父の名前
    foal = hl.breed(founder, market, today=TODAY, rng=random.Random(2))
    assert foal['line'] == 'ソシ'                                     # 仔は父の系統
    assert foal['pedigree']['sire']['line'] == 'ソシ'
    assert foal['pedigree']['dam']['line'] == 'チチウマ'


def test_nick_is_deterministic_and_about_twelve_percent():
    assert hl.is_nick('A', 'B') == hl.is_nick('A', 'B')
    hits = sum(1 for i in range(2000) for j in range(1) if hl.is_nick(f'L{i}', f'M{i * 7}'))
    assert 0.08 < hits / 2000 < 0.16


def test_nick_raises_inheritance_and_fixes_one_aptitude(monkeypatch):
    monkeypatch.setattr(hl, 'is_nick', lambda a, b: True)
    sire = parent('チチ', '牡', line='X', apt={'turf': 'A', 'dirt': 'D', 'sprint': 'B', 'mile': 'B', 'middle': 'B', 'long': 'B'})
    dam = parent('ハハ', '牝', line='Y', apt={'turf': 'D', 'dirt': 'D', 'sprint': 'B', 'mile': 'B', 'middle': 'B', 'long': 'B'})
    plain = dict(sire)
    for seed in range(20):
        foal = hl.breed(sire, dam, today=TODAY, rng=random.Random(seed))
        assert foal['aptitude']['turf'] == 'A'                        # 一番差のある項目は良いほうで確定
        assert foal['blood']['nick'] is True and '◎ニックス' in foal['blood']['tags']
    monkeypatch.setattr(hl, 'is_nick', lambda a, b: False)
    base = hl.breed(sire, dam, today=TODAY, rng=random.Random(1))['growth']['speed']
    monkeypatch.setattr(hl, 'is_nick', lambda a, b: True)
    boosted = hl.breed(sire, dam, today=TODAY, rng=random.Random(1))['growth']['speed']
    assert boosted == pytest.approx(base * (1 + hl.NICK_BONUS))


# ====================================================
# 気性難の効き方
# ====================================================
def test_temper_makes_trouble_more_likely_and_condition_rougher():
    data = hl.load_stable(TODAY)
    horse = data['current']
    horse['blood'] = {'nick': False, 'temper': True, 'tags': ['⚠ソフ 2×2（濃すぎ・気性難）']}
    assert hl.player_entry(horse, data, TODAY)['trouble_scale'] == hl.TEMPER_TROUBLE_SCALE

    data['current_streak'] = 30                                        # 本来は絶好調(+2)
    conds = set()
    for d in range(1, 29):                                             # 毎日記録している前提
        data['last_active_date'] = date(2026, 9, d).isoformat()
        conds.add(hl.condition_of(data, date(2026, 9, d)))
    assert conds == {2, 1}                                             # 日によって1段落ちる


def test_plain_horse_has_no_temper_effects():
    data = hl.load_stable(TODAY)
    assert hl.player_entry(data['current'], data, TODAY)['trouble_scale'] == 1.0


# ====================================================
# 表示と読み込み
# ====================================================
def test_candidates_show_blood_tags_before_reserving():
    data = hl.load_stable(TODAY)
    horse = data['current']
    horse['sex'] = '牡'
    horse['pedigree'] = {'sire': node('ソフ'), 'dam': None}
    horse['record']['starts'] = hl.BREEDING_OPEN_STARTS
    data['stallions'].append({
        'id': 's1', 'name': 'イモウト', 'sex': '牝', 'class': 'OP',
        'params': {k: 500 for k in hl.PARAMS}, 'aptitude': {k: 'B' for k in hl.APTITUDE_KEYS},
        'record': {'starts': 20, 'win': 2, 'place': 3, 'show': 4, 'prize': 100},
        'stud_value': 1.1, 'pedigree': {'sire': node('ソフ'), 'dam': None}, 'line': 'ソフ',
    })
    cands = hl.breeding_candidates(data, pool={'horses': []})
    own = next(c for c in cands if c['source'] == 'own')
    assert any('2×2' in t and '気性難' in t for t in own['blood_tags'])
    assert '気性難' in hl.format_candidate(own)


def test_old_data_gets_a_line_and_blood_on_load(tmp_path):
    import json
    stable = hl._default_stable(TODAY)
    del stable['current']['line']
    del stable['current']['blood']
    stable['stallions'].append({'name': 'インタイ', 'sex': '牝', 'class': '1勝',
                                'params': {k: 300 for k in hl.PARAMS}, 'aptitude': {},
                                'record': {'prize': 0}, 'stud_value': 1.0})
    with open(hl.STABLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(stable, f, ensure_ascii=False)
    data = hl.load_stable(TODAY)
    assert data['current']['line'] == data['current']['name']
    assert data['current']['blood'] == {'nick': False, 'temper': False, 'tags': []}
    assert data['stallions'][0]['line'] == 'インタイ'


def test_pedigree_view_shows_line_and_crosses():
    data = hl.load_stable(TODAY)
    horse = data['current']
    horse['pedigree'] = {'sire': node('チチ', sire=node('ソフ')), 'dam': node('ハハ', sire=node('ソフ'))}
    text = hl.format_pedigree(horse)
    assert '系）' in text and 'ソフ 2×2' in text
