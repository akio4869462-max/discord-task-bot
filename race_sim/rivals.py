"""ライバル馬プールから出走表を組む。

Discord にもファイルI/Oの都合にも依存しない純ロジック。標準ライブラリだけで動く。
プール本体（`data/rivals.json`）は tools/build_rivals.py が実データから生成する。

## 脚質はレースごとに決まる

⭕ 馬に「逃げ」「差し」といった固定の脚質を持たせる形を最初に試したが、実データを
   見ると位置取りの個体内SD(0.226)は個体間SD(0.169)より大きく、脚質は固定の属性では
   なく傾向でしかない。さらに通過順は**レース内の順位**なので、分布は構造上どの馬も
   一様になる（逃げ＝先頭1頭＝約7%）。個体ごとに正規分布で引くと中央に寄り、
   差しが41%（実測33%）に膨らんだ。

   そこでここでは、出走各馬の位置取りを引いたうえで**メンバー内で順位づけ**して
   脚質を決める。実際のレースと同じ手順なので、シェアは定義上そのまま再現され、
   逃げ馬は必ず1頭になる。「行きたい馬が揃うと前を取れない」も自然に起きる。
"""

import json
import os
import random

RIVALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'rivals.json')

# 脚質の宣言 → 位置取りの狙い（0.0が最前、1.0が最後方）
STYLE_INTENT = {'逃げ': 0.02, '先行': 0.24, '差し': 0.50, '追込': 0.80}
# ⭕ 宣言した脚質どおりになる度合い。0.18 だと逃げを宣言しても先行に収まるほうが
#    多く（60回中 逃げ26 / 先行29）、宣言の意味が薄かった。ライバルの位置取りは
#    レースごとに大きく振れる（個体内SD 0.22）ので、宣言側はそれより明確に狭くする。
INTENT_SD = 0.09

# ライバルが「そのレースでどこを狙うか」のブレ幅。保存してある pos_sd に掛ける。
# ⭕ pos_sd はキャリア全体で観測された位置取りのばらつきで、そこには「他馬が
#    行かせてくれたか」という結果が既に含まれている。これをそのまま毎レースの
#    意思として使うと全馬が高頻度でハナを主張し、逃げを宣言しても通るのが
#    半分（52%）まで落ちた。意思のブレは観測されたばらつきより狭いはず。
RIVAL_INTENT_RATIO = 0.6

# 主戦場でない馬が出走してくる相対的な出やすさ
OFF_SURFACE_WEIGHT = 0.08

# 距離適性グレード → その距離のレースに出てくる相対的な出やすさ
# ⭕ 芝ダだけで絞って距離を見ていなかったとき、3000m のレースにマイラーが並び、
#    勝ち時計が実測より0.3秒遅く、能力最上位の勝率が0.42（目標0.33）まで上がった。
#    実際の出走馬は距離も選んで使われている。
DISTANCE_WEIGHT = {'A': 1.0, 'B': 0.45, 'C': 0.12, 'D': 0.02, 'E': 0.01}

# ライバルの調子の出方。ほとんどは平常。
CONDITION_CHOICES = ([-1] * 2 + [0] * 6 + [1] * 2)

_pool_cache = {}


def load_pool(path=None):
    """ライバル馬プールを読み込む。パスごとに1度だけ読んで使い回す。"""
    path = path or RIVALS_FILE
    if path not in _pool_cache:
        with open(path, 'r', encoding='utf-8') as f:
            _pool_cache[path] = json.load(f)
    return _pool_cache[path]


def clear_pool_cache():
    """テストでプールを差し替えるときに呼ぶ。"""
    _pool_cache.clear()


def draw_field_size(cls, rng, pool=None):
    """そのクラスの実際の出走頭数分布から頭数を引く。"""
    pool = pool or load_pool()
    dist = pool.get('field_size', {}).get(cls)
    if not dist:
        return 16
    sizes = sorted(dist, key=int)
    return int(rng.choices(sizes, [dist[s] for s in sizes])[0])


def _is_dirt_horse(horse):
    return horse['aptitude'].get('dirt') == 'A'


def distance_band(distance):
    """適性辞書の距離区分。engine と同じ区切りを使う。"""
    if distance <= 1400:
        return 'sprint'
    if distance <= 1800:
        return 'mile'
    if distance <= 2400:
        return 'middle'
    return 'long'


SUPPORT_MIN = 25    # この頭数を満たさない条件は「実在しない番組」とみなす


def is_supported(race, pool=None, minimum=SUPPORT_MIN):
    """その条件のレースを、まともな出走馬で組めるかを返す。

    ⭕ JRAにダートのG2はほぼ無いため、プールにもG2のダート馬はいない。それでも
       ダートG2を組むと、芝の馬が適性ペナルティを背負って動員され、勝ち時計が
       1.05秒も遅くなった（較正で発覚）。番組を組む側がここを見て、実在しない
       条件を避けること。Phase 5 のレース番組表もこの判定に従う。
    """
    pool = pool or load_pool()
    want_dirt = race['surface'] == 'ダ'
    band = distance_band(race['distance'])
    cls = race.get('class', '1勝')

    n = sum(1 for h in pool['horses']
            if h['class'] == cls
            and _is_dirt_horse(h) == want_dirt
            and h['aptitude'].get(band) in ('A', 'B'))
    return n >= minimum


def pick_rivals(race, count, rng, pool=None, exclude=None):
    """レース条件に合うライバルを count 頭選ぶ。

    ⭕ 同じクラスの馬から選ぶが、主戦場が違う馬もわずかに混ぜる。実データでも
       芝馬がダートを試す出走はあり、全部が得意条件の馬だと堅くなりすぎる。
    """
    pool = pool or load_pool()
    exclude = exclude or set()
    want_dirt = race['surface'] == 'ダ'

    band = distance_band(race['distance'])

    candidates, weights = [], []
    for h in pool['horses']:
        if h['class'] != race.get('class', '1勝') or h['name'] in exclude:
            continue
        w = 1.0 if _is_dirt_horse(h) == want_dirt else OFF_SURFACE_WEIGHT
        w *= DISTANCE_WEIGHT.get(h['aptitude'].get(band, 'B'), 0.45)
        candidates.append(h)
        weights.append(w)

    if not candidates:
        raise ValueError(f"該当するライバルがいません: {race.get('class')}")

    picked = []
    pool_items = list(zip(candidates, weights))
    for _ in range(min(count, len(pool_items))):
        total = sum(w for _, w in pool_items)
        r = rng.random() * total
        acc = 0.0
        for i, (h, w) in enumerate(pool_items):
            acc += w
            if r <= acc:
                picked.append(h)
                pool_items.pop(i)
                break
    return picked


def assign_styles(members, rng):
    """出走各馬の位置取りを引き、メンバー内の順位から脚質を決める。

    Args:
        members (list): {'pos_mean', 'pos_sd'} を持つ辞書のリスト。

    Returns:
        list: members と同じ並びの脚質のリスト。
    """
    n = len(members)
    latents = []
    for i, m in enumerate(members):
        sd = m['pos_sd'] if m.get('is_player') else m['pos_sd'] * RIVAL_INTENT_RATIO
        latents.append((rng.gauss(m['pos_mean'], sd), i))
    latents.sort()

    styles = [None] * n
    for rank, (_, idx) in enumerate(latents, start=1):
        if rank == 1:
            styles[idx] = '逃げ'
        elif rank <= n * 0.33:
            styles[idx] = '先行'
        elif rank <= n * 0.66:
            styles[idx] = '差し'
        else:
            styles[idx] = '追込'
    return styles


def build_field(race, size=None, seed=None, player=None, pool=None):
    """レースの出走表を組む。

    Args:
        race (dict): course/surface/distance/cond/class を持つレース条件。
        size (int): 頭数。省略時はそのクラスの実際の分布から引く。
        seed (int): 乱数シード。同じ seed なら必ず同じ出走表になる。
        player (dict): 自分の馬。name/params/aptitude と、脚質の宣言 style
            （または pos_mean）を持つ。省略すればライバルだけの出走表になる。
        pool (dict): ライバル馬プール。省略時はファイルから読む。

    Returns:
        list: engine.simulate() にそのまま渡せる出走馬のリスト。
    """
    rng = random.Random(seed)
    pool = pool or load_pool()
    cls = race.get('class', '1勝')

    if size is None:
        size = draw_field_size(cls, rng, pool)

    n_rivals = size - (1 if player else 0)
    rivals = pick_rivals(race, n_rivals, rng, pool,
                         exclude={player['name']} if player else None)

    members = []
    if player:
        intent = player.get('pos_mean')
        if intent is None:
            intent = STYLE_INTENT.get(player.get('style', '差し'), 0.5)
        members.append({
            'name': player.get('name', 'マイホース'),
            'params': player['params'],
            'aptitude': player.get('aptitude', {}),
            'condition': player.get('condition', 0),
            'pos_mean': intent,
            'pos_sd': player.get('pos_sd', INTENT_SD),
            'is_player': True,
        })
    for h in rivals:
        members.append({
            'name': h['name'],
            'params': dict(h['params']),
            'aptitude': dict(h['aptitude']),
            'condition': rng.choice(CONDITION_CHOICES),
            'pos_mean': h['pos_mean'],
            'pos_sd': h['pos_sd'],
            'sex': h.get('sex'),
            'age': h.get('age'),
            'sire': h.get('sire'),
            'is_player': False,
        })

    styles = assign_styles(members, rng)

    order = list(range(len(members)))
    rng.shuffle(order)
    entries = []
    for no, idx in enumerate(order, start=1):
        m = members[idx]
        entries.append({
            'no': no,
            'name': m['name'],
            'params': m['params'],
            'aptitude': m['aptitude'],
            'condition': m['condition'],
            'style': styles[idx],
            'is_player': m['is_player'],
            'sex': m.get('sex'),
            'age': m.get('age'),
            'sire': m.get('sire'),
        })
    entries.sort(key=lambda e: e['no'])
    return entries
