import json
import statistics

import pytest

from race_sim import engine


def make_entry(no, level=0.0, style='先行', **params):
    """能力水準 level（zスコア相当）の出走馬を1頭作る。"""
    base = {k: 500 + 200 * level for k in engine.JST_PARAMS}
    base.update(params)
    return {'no': no, 'name': f"テスト{no:02d}", 'params': base,
            'style': style, 'aptitude': {}, 'condition': 0}


def make_field(size=12, level=0.0):
    styles = ['逃げ'] + ['先行'] * 3 + ['差し'] * 5 + ['追込'] * 3
    return [make_entry(i + 1, level, styles[i % len(styles)]) for i in range(size)]


TURF_1600 = {'course': '東京', 'surface': '芝', 'distance': 1600,
             'cond': '良', 'class': '1勝', 'name': 'テスト特別'}


# ====================================================
# 較正データの読み込み
# ====================================================
def test_load_baseline_uses_module_level_path(tmp_path, monkeypatch):
    """テストから較正データを差し替えられること（本物のdata/を読まない）。"""
    fake = tmp_path / 'baseline.json'
    fake.write_text(json.dumps({
        'base': {'東京|芝|1600': {'win_time': 100.0, 'last3f': 34.0, 'n': 500, 'field': 15.0}},
        'class_offset': {}, 'cond_offset': {}, 'margin': {}, 'style': {}, 'favorite': {},
    }), encoding='utf-8')
    monkeypatch.setattr(engine, 'BASELINE_FILE', str(fake))
    engine.clear_baseline_cache()

    assert engine.base_time(TURF_1600) == 100.0
    engine.clear_baseline_cache()


def test_base_time_applies_track_condition():
    """馬場が渋ると芝は遅くなり、ダートは速くなる（実測どおりの符号）。"""
    turf_good = engine.base_time(dict(TURF_1600, cond='良'))
    turf_heavy = engine.base_time(dict(TURF_1600, cond='重'))
    assert turf_heavy > turf_good

    dirt = {'course': '東京', 'surface': 'ダ', 'distance': 1400, 'cond': '良'}
    assert engine.base_time(dict(dirt, cond='重')) < engine.base_time(dirt)


def test_base_time_interpolates_unknown_course():
    """較正データに無い距離でもレースを開催できる。"""
    t = engine.base_time({'course': '東京', 'surface': '芝', 'distance': 1900, 'cond': '良'})
    t1800 = engine.base_time({'course': '東京', 'surface': '芝', 'distance': 1800, 'cond': '良'})
    assert t1800 < t < t1800 * 1900 / 1800 * 1.05


def test_base_time_raises_for_unknown_surface():
    with pytest.raises(ValueError):
        engine.base_time({'course': '架空', 'surface': '砂', 'distance': 1600, 'cond': '良'})


# ====================================================
# レース結果の整合性
# ====================================================
def test_same_seed_gives_same_result():
    """seedが同じなら結果は完全に一致する（保存せず再現できる前提）。"""
    field = make_field()
    a = engine.simulate(TURF_1600, field, seed=42)
    b = engine.simulate(TURF_1600, field, seed=42)
    assert a == b


def test_different_seed_changes_result():
    field = make_field()
    a = engine.simulate(TURF_1600, field, seed=1)
    b = engine.simulate(TURF_1600, field, seed=2)
    assert [h['no'] for h in a['horses']] != [h['no'] for h in b['horses']]


def test_splits_sum_to_total_time():
    """区間ラップの合計は走破タイムと一致する（ビューアが位置を補間する前提）。"""
    result = engine.simulate(TURF_1600, make_field(), seed=7)
    for h in result['horses']:
        assert h['splits'] == pytest.approx(h['splits'])
        assert sum(h['splits']) == pytest.approx(h['time'], abs=0.02)
        assert len(h['splits']) == 8      # 1600m ÷ 200m


def test_finish_order_matches_times():
    result = engine.simulate(TURF_1600, make_field(16), seed=3)
    times = [h['time'] for h in result['horses']]
    assert times == sorted(times)
    assert [h['finish'] for h in result['horses']] == list(range(1, 17))
    assert result['horses'][0]['margin'] == 0.0


def test_passing_positions_are_a_permutation():
    """各通過地点で順位が1..頭数の重複なしになっていること。"""
    result = engine.simulate(TURF_1600, make_field(14), seed=5)
    n = len(result['horses'])
    for point in range(len(result['horses'][0]['passing'])):
        ranks = sorted(h['passing'][point] for h in result['horses'])
        assert ranks == list(range(1, n + 1))


def test_front_runner_leads_early():
    """逃げ馬は序盤で前にいる。"""
    field = [make_entry(1, 0.0, '逃げ')] + [make_entry(i + 2, 0.0, '追込') for i in range(9)]
    result = engine.simulate(TURF_1600, field, seed=11)
    leader = next(h for h in result['horses'] if h['no'] == 1)
    assert leader['passing'][0] == 1


def test_short_race_has_no_index_error():
    """1000mでも区間生成が壊れないこと。"""
    race = dict(TURF_1600, distance=1000, course='中山')
    result = engine.simulate(race, make_field(10), seed=9)
    assert len(result['horses'][0]['splits']) == 5


# ====================================================
# 能力とレース結果の関係
# ====================================================
def test_stronger_horse_wins_more_often():
    """能力が高い馬ほど勝ちやすいが、必ず勝つわけではない。"""
    wins = 0
    n = 300
    for seed in range(n):
        field = [make_entry(1, 0.9)] + [make_entry(i + 2, 0.0) for i in range(11)]
        result = engine.simulate(TURF_1600, field, seed=seed)
        if result['horses'][0]['no'] == 1:
            wins += 1
    assert 0.35 < wins / n < 0.95


def test_ability_z_weights_stamina_more_at_long_distance():
    """長距離ではスタミナの重みが大きい。"""
    stayer = make_entry(1, 0.0, stamina=900)
    sprinter = make_entry(2, 0.0, speed=900)
    long_race = {'course': '京都', 'surface': '芝', 'distance': 3000, 'cond': '良'}
    short_race = {'course': '中山', 'surface': '芝', 'distance': 1200, 'cond': '良'}

    assert engine.ability_z(stayer, long_race) > engine.ability_z(sprinter, long_race)
    assert engine.ability_z(sprinter, short_race) > engine.ability_z(stayer, short_race)


def test_dirt_rewards_power():
    """ダートではパワーの寄与が芝より大きい。"""
    powerful = make_entry(1, 0.0, power=900)
    turf = engine.ability_z(powerful, TURF_1600)
    dirt = engine.ability_z(powerful, dict(TURF_1600, surface='ダ', distance=1400))
    assert dirt > turf


def test_condition_and_aptitude_shift_ability():
    good = make_entry(1)
    good['condition'] = 2
    assert engine.ability_z(good, TURF_1600) > engine.ability_z(make_entry(1), TURF_1600)

    unsuited = make_entry(1)
    unsuited['aptitude'] = {'turf': 'E'}
    assert engine.ability_z(unsuited, TURF_1600) < engine.ability_z(make_entry(1), TURF_1600)


def test_high_pace_helps_closers():
    """逃げ・先行が揃ってペースが上がると、追込馬の評価が上がる。"""
    front_heavy = [make_entry(i + 1, 0.0, '逃げ') for i in range(8)]
    slow = [make_entry(i + 1, 0.0, '追込') for i in range(8)]
    assert engine.race_pace(front_heavy) > engine.race_pace(slow)


# ====================================================
# 実測との一致（較正目標のうち、テストとして固定できるもの）
# ====================================================
def test_winning_time_matches_real_baseline():
    """1勝クラスの平均勝ちタイムが実測の基準値とほぼ一致すること。"""
    baseline = engine.load_baseline()
    ref = baseline['base']['東京|芝|1600']['win_time']
    times = []
    for seed in range(200):
        field = make_field(14, engine.CLASS_MEAN_Z['1勝'])
        times.append(engine.simulate(TURF_1600, field, seed=seed)['horses'][0]['time'])
    assert statistics.fmean(times) == pytest.approx(ref, abs=0.5)


def test_runner_up_margin_matches_real_distribution():
    """1着-2着の着差の中央値が実測（0.2秒）付近に収まること。"""
    margins = []
    for seed in range(300):
        field = make_field(14, engine.CLASS_MEAN_Z['1勝'])
        margins.append(engine.simulate(TURF_1600, field, seed=seed)['horses'][1]['margin'])
    assert statistics.median(margins) == pytest.approx(0.2, abs=0.1)


def test_class_levels_are_ordered():
    """上のクラスほど出走馬の能力水準が高い（3勝とOPは実測どおり同水準）。"""
    z = engine.CLASS_MEAN_Z
    assert z['未勝利'] < z['1勝'] < z['2勝'] < z['3勝']
    assert z['3勝'] <= z['G3'] < z['G2'] < z['G1']


def test_format_result_contains_all_horses():
    result = engine.simulate(TURF_1600, make_field(12), seed=4)
    text = engine.format_result(result)
    assert '東京芝1600m' in text
    assert text.count('\n') == 13      # ヘッダ2行 + 12頭 - 1
