"""成長型（早熟／普通／晩成）と、今週の重点（調教メニュー）のテスト。"""
import random
from datetime import date

import pytest

import horse_logic as hl


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))


TODAY = date(2026, 9, 11)          # 金曜
MINUTES = {k: 1500.0 for k in hl.PARAMS}


# ====================================================
# 成長型
# ====================================================
def test_growth_factor_runs_from_debut_to_retirement():
    assert hl.growth_factor('早熟', 0.0) == pytest.approx(1.12)
    assert hl.growth_factor('早熟', 1.0) == pytest.approx(0.92)
    assert hl.growth_factor('晩成', 0.0) == pytest.approx(0.90)
    assert hl.growth_factor('晩成', 1.0) == pytest.approx(1.12)
    assert hl.growth_factor('普通', 0.5) == 1.0


def test_early_type_is_stronger_at_debut_and_late_type_at_the_end():
    early0 = hl.derive_params(MINUTES, '早熟', 0.0)['speed']
    late0 = hl.derive_params(MINUTES, '晩成', 0.0)['speed']
    normal = hl.derive_params(MINUTES, '普通', 0.0)['speed']
    early1 = hl.derive_params(MINUTES, '早熟', 1.0)['speed']
    late1 = hl.derive_params(MINUTES, '晩成', 1.0)['speed']
    assert early0 > normal > late0
    assert late1 > normal > early1


def test_types_average_out_over_a_career():
    """⭕ 難易度の較正（G1 7勝）を崩さないよう、現役平均ではほぼ同じ強さ。"""
    def mean(gtype):
        return sum(hl.derive_params(MINUTES, gtype, p / 20)['speed'] for p in range(21)) / 21
    assert abs(mean('早熟') - mean('普通')) / mean('普通') < 0.03
    assert abs(mean('晩成') - mean('普通')) / mean('普通') < 0.03


def test_early_type_has_a_lower_cap():
    huge = {k: 10 ** 6 for k in hl.PARAMS}
    assert hl.derive_params(huge, '早熟', 0.0)['speed'] == hl.GROWTH_TYPE_CAP['早熟'] < hl.ABILITY_CAP
    assert hl.derive_params(huge, '晩成', 1.0)['speed'] == hl.ABILITY_CAP


def test_params_of_uses_the_horse_progress():
    data = hl.load_stable(TODAY)
    horse = data['current']
    horse['growth'] = dict(MINUTES)
    horse['growth_type'] = '晩成'
    horse['slots'] = 0
    debut = hl.params_of(horse)['speed']
    horse['slots'] = hl.RETIRE_STARTS
    assert hl.params_of(horse)['speed'] > debut


def test_new_horse_gets_a_random_type_with_the_expected_mix():
    types = [hl.new_horse(today=TODAY, rng=random.Random(i))['growth_type'] for i in range(400)]
    share = {t: types.count(t) / 400 for t in hl.GROWTH_TYPES}
    assert 0.15 < share['早熟'] < 0.35 and 0.35 < share['普通'] < 0.65 and 0.15 < share['晩成'] < 0.35


def test_foal_inherits_the_type_from_the_parents():
    same = [hl.inherit_growth_type('晩成', '晩成', random.Random(i)) for i in range(300)]
    assert same.count('晩成') / 300 > 0.6
    mixed = {hl.inherit_growth_type('早熟', '晩成', random.Random(i)) for i in range(50)}
    assert mixed == {'早熟', '晩成'}


def test_market_horse_type_is_deterministic_from_its_name():
    m = {'name': 'イチバノウマ', 'sex': '牝', 'class': 'OP', 'params': {}, 'aptitude': {}}
    assert hl.growth_type_of(m) == hl.growth_type_of(dict(m))
    assert hl.growth_type_of(m) in hl.GROWTH_TYPES


def test_old_data_keeps_the_normal_type_and_shows_it(tmp_path):
    import json
    stable = hl._default_stable(TODAY)
    del stable['current']['growth_type']
    with open(hl.STABLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(stable, f, ensure_ascii=False)
    data = hl.load_stable(TODAY)
    assert data['current']['growth_type'] == '普通'      # 途中の馬の能力を急に変えない
    assert '・普通・' in hl.format_horse(data, TODAY)


# ====================================================
# 今週の重点
# ====================================================
def test_focus_shifts_part_of_the_split_without_changing_the_total():
    w = hl.weights_with_focus({'speed': 0.6, 'guts': 0.4}, 'stamina')
    assert w['stamina'] == pytest.approx(0.15)
    assert w['speed'] == pytest.approx(0.6 * 0.85) and w['guts'] == pytest.approx(0.4 * 0.85)
    assert sum(w.values()) == pytest.approx(1.0)
    # 重点が元から入っている活動なら、その分が増える
    w = hl.weights_with_focus({'speed': 0.6, 'guts': 0.4}, 'guts')
    assert w['guts'] == pytest.approx(0.4 + 0.15) and sum(w.values()) == pytest.approx(1.0)
    assert hl.weights_with_focus({'speed': 0.6, 'guts': 0.4}, None) == {'speed': 0.6, 'guts': 0.4}


def test_focus_applies_to_this_week_only():
    data = hl.load_stable(TODAY)
    hl.set_focus('stamina', data=data, today=TODAY, save=False)
    assert hl.focus_param(data, TODAY) == 'stamina'
    assert hl.focus_param(data, date(2026, 9, 13)) == 'stamina'      # 同じ週の日曜
    assert hl.focus_param(data, date(2026, 9, 14)) is None           # 翌週の月曜


def test_focused_training_lands_on_the_focused_parameter():
    data = hl.load_stable(TODAY)
    hl.set_focus('stamina', data=data, today=TODAY, save=False)
    hl.add_growth('programming', 100, today=TODAY, data=data, save=False)
    g = data['current']['growth']
    assert g['stamina'] == pytest.approx(15) and g['speed'] == pytest.approx(51) and g['guts'] == pytest.approx(34)


def test_set_focus_rejects_unknown_parameters_and_can_be_cleared():
    data = hl.load_stable(TODAY)
    with pytest.raises(ValueError):
        hl.set_focus('luck', data=data, today=TODAY, save=False)
    hl.set_focus('wit', data=data, today=TODAY, save=False)
    hl.set_focus(None, data=data, today=TODAY, save=False)
    assert hl.focus_param(data, TODAY) is None


def test_stable_view_shows_the_focus():
    data = hl.load_stable(TODAY)
    hl.set_focus('dash', data=data, today=TODAY, save=False)
    assert '今週の重点: 瞬発力' in hl.format_horse(data, TODAY)
