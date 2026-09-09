import json
from collections import Counter

import pytest

from race_sim import engine, rivals


TURF_1600 = {'course': '東京', 'surface': '芝', 'distance': 1600,
             'cond': '良', 'class': '1勝', 'name': 'テスト特別'}
LONG_3000 = {'course': '京都', 'surface': '芝', 'distance': 3000,
             'cond': '良', 'class': 'OP', 'name': 'テスト長距離'}
DIRT_1400 = {'course': '東京', 'surface': 'ダ', 'distance': 1400,
             'cond': '良', 'class': '1勝', 'name': 'テストダート'}


def make_player(name='マイホース', style='差し', level=0.0):
    return {
        'name': name, 'style': style,
        'params': {k: 500 + 200 * level for k in engine.JST_PARAMS},
        'aptitude': {'turf': 'A', 'mile': 'A'}, 'condition': 0,
    }


# ====================================================
# プールの読み込み
# ====================================================
def test_load_pool_uses_module_level_path(tmp_path, monkeypatch):
    """テストからプールを差し替えられること（本物のプールを読まない）。"""
    fake = tmp_path / 'rivals.json'
    fake.write_text(json.dumps({
        'meta': {}, 'field_size': {'1勝': {'8': 1}},
        'horses': [{
            'name': f"テスト{i}", 'sex': '牡', 'age': 4, 'class': '1勝', 'z': 0.0,
            'params': {k: 500 for k in engine.JST_PARAMS},
            'pos_mean': 0.5, 'pos_sd': 0.2,
            'aptitude': {'turf': 'A', 'dirt': 'D', 'sprint': 'B', 'mile': 'A',
                         'middle': 'B', 'long': 'D'},
            'sire': 'テスト父', 'bms': 'テスト母父',
        } for i in range(20)],
    }), encoding='utf-8')
    monkeypatch.setattr(rivals, 'RIVALS_FILE', str(fake))
    rivals.clear_pool_cache()

    entries = rivals.build_field(TURF_1600, seed=1)
    assert len(entries) == 8          # field_size の分布どおり
    assert all(e['name'].startswith('テスト') for e in entries)
    rivals.clear_pool_cache()


def test_pool_has_every_class():
    """全クラスでレースを開催できるだけの頭数があること。"""
    pool = rivals.load_pool()
    counts = Counter(h['class'] for h in pool['horses'])
    for cls in engine.CLASS_ORDER:
        assert counts[cls] >= 60, f"{cls} が{counts[cls]}頭しかいない"


def test_pool_names_are_plausible():
    """馬名がカタカナ4〜9文字（実在馬の字数の範囲）であること。"""
    pool = rivals.load_pool()
    for h in pool['horses'][:200]:
        assert 4 <= len(h['name']) <= 9
        assert all('ァ' <= ch <= 'ヶ' or ch == 'ー' for ch in h['name']), h['name']


# ====================================================
# 出走表の組み立て
# ====================================================
def test_field_has_unique_consecutive_numbers():
    entries = rivals.build_field(TURF_1600, size=16, seed=3)
    assert [e['no'] for e in entries] == list(range(1, 17))
    assert len({e['name'] for e in entries}) == 16


def test_same_seed_gives_same_field():
    a = rivals.build_field(TURF_1600, size=14, seed=42)
    b = rivals.build_field(TURF_1600, size=14, seed=42)
    assert a == b


def test_exactly_one_front_runner():
    """脚質はメンバー内の順位で決まるので、逃げ馬は必ず1頭になる。"""
    for seed in range(20):
        entries = rivals.build_field(TURF_1600, size=16, seed=seed)
        assert sum(1 for e in entries if e['style'] == '逃げ') == 1


def test_style_shares_match_the_definition():
    """脚質シェアが通過順の定義どおりに出ること（逃げは約7%）。"""
    counts = Counter()
    for seed in range(200):
        for e in rivals.build_field(TURF_1600, size=16, seed=seed):
            counts[e['style']] += 1
    total = sum(counts.values())
    assert 0.05 < counts['逃げ'] / total < 0.09
    assert 0.20 < counts['先行'] / total < 0.30
    assert 0.28 < counts['差し'] / total < 0.38


def test_player_is_included_once():
    player = make_player()
    entries = rivals.build_field(TURF_1600, size=12, seed=5, player=player)
    mine = [e for e in entries if e['is_player']]
    assert len(mine) == 1
    assert mine[0]['name'] == 'マイホース'
    assert len(entries) == 12


def test_player_name_is_not_duplicated_by_a_rival():
    """自分の馬と同名のライバルが選ばれないこと。"""
    pool = rivals.load_pool()
    taken = pool['horses'][0]['name']
    entries = rivals.build_field(TURF_1600, size=12, seed=7, player=make_player(name=taken))
    assert sum(1 for e in entries if e['name'] == taken) == 1


def test_declared_style_is_an_intention_not_a_guarantee():
    """逃げを宣言しても、行きたい馬が揃えば前を取れないことがある。"""
    got = Counter()
    for seed in range(60):
        entries = rivals.build_field(TURF_1600, size=16, seed=seed, player=make_player(style='逃げ'))
        got[next(e['style'] for e in entries if e['is_player'])] += 1
    assert got['逃げ'] > got['先行']     # 宣言どおりになるのが最も多い
    assert got['逃げ'] < 60              # それでも毎回は取れない


# ====================================================
# レース条件との噛み合わせ
# ====================================================
def test_long_race_is_filled_with_stayers():
    """3000mの出走馬は長距離をこなす馬が中心になる。

    ⭕ 「長距離がトップ区分(A)の馬」だけを期待すると実態と合わない。実際の長距離戦は
       中距離主戦で長距離もこなす馬（B）が中心である。
    """
    grades = Counter()
    for seed in range(30):
        for e in rivals.build_field(LONG_3000, size=14, seed=seed):
            grades[e['aptitude'].get('long', 'D')] += 1
    total = sum(grades.values())
    assert (grades['A'] + grades['B']) / total > 0.6


def test_dirt_race_is_filled_with_dirt_horses():
    dirt = turf = 0
    for seed in range(30):
        for e in rivals.build_field(DIRT_1400, size=14, seed=seed):
            if e['aptitude'].get('dirt') == 'A':
                dirt += 1
            else:
                turf += 1
    assert dirt > turf * 4


def test_field_size_follows_real_distribution():
    """頭数を省略すると、そのクラスの実際の分布から引かれる。"""
    sizes = [len(rivals.build_field(TURF_1600, seed=s)) for s in range(200)]
    assert min(sizes) >= 5 and max(sizes) <= 18
    assert Counter(sizes).most_common(1)[0][0] == 16     # 実データの最頻値


def test_all_entries_are_from_the_requested_class():
    pool = {h['name']: h for h in rivals.load_pool()['horses']}
    for e in rivals.build_field(LONG_3000, size=14, seed=2):
        assert pool[e['name']]['class'] == 'OP'


# ====================================================
# エンジンとの接続
# ====================================================
def test_field_runs_through_the_engine():
    entries = rivals.build_field(TURF_1600, size=16, seed=11, player=make_player())
    result = engine.simulate(TURF_1600, entries, seed=11)
    assert len(result['horses']) == 16
    assert [h['finish'] for h in result['horses']] == list(range(1, 17))
    assert sum(1 for h in result['horses'] if h['is_player']) == 1


def test_stronger_player_horse_wins_more_often():
    """自分の馬を強くすれば勝率が上がる。"""
    def win_rate(level):
        wins = 0
        for seed in range(120):
            entries = rivals.build_field(TURF_1600, size=16, seed=seed,
                                         player=make_player(level=level))
            result = engine.simulate(TURF_1600, entries, seed=seed)
            wins += 1 if result['horses'][0]['is_player'] else 0
        return wins / 120

    assert win_rate(-1.5) < win_rate(0.5)


def test_winning_time_stays_near_the_real_baseline():
    """プールで組んだ出走表でも、勝ちタイムが実測の基準から外れないこと。"""
    baseline = engine.load_baseline()
    ref = (baseline['base']['東京|芝|1600']['win_time']
           + baseline['class_offset']['1勝']['offset'])
    times = []
    for seed in range(150):
        entries = rivals.build_field(TURF_1600, seed=seed)
        times.append(engine.simulate(TURF_1600, entries, seed=seed)['horses'][0]['time'])
    assert sum(times) / len(times) == pytest.approx(ref, abs=0.5)
