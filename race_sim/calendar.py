"""番組表。その日に出走できるレースを組む。

Discord にもファイルI/Oにも依存しない純ロジック。標準ライブラリだけで動く。

⭕ 出走登録には「出走できるレースの一覧」が要るので、番組表は Phase 5 ではなく
   Phase 4 に含めている。無いと厩舎まわりが単体で完結しない。

⭕ 提示するのは `rivals.is_supported()` を満たす条件だけ。JRAにダートのG2はほぼ無く、
   プールにもG2のダート馬はいない。そういう番組を組むと芝の馬が適性ペナルティを
   背負って動員され、勝ち時計が1秒以上遅くなる。
"""

import datetime
import random
import zlib

from race_sim import engine, rivals

# 開催は土曜と水曜（Pythonのweekdayは月曜=0）
RACE_WEEKDAYS = (2, 5)

# 1回の登録で提示するレース数
OFFER_COUNT = 4

# クラス → (格, 1着賞金[万円])
CLASS_INFO = {
    '未勝利': {'grade': None, 'prize': 520},
    '1勝': {'grade': None, 'prize': 770},
    '2勝': {'grade': None, 'prize': 1060},
    '3勝': {'grade': None, 'prize': 1500},
    'OP': {'grade': 'OP', 'prize': 2200},
    'G3': {'grade': 'G3', 'prize': 3900},
    'G2': {'grade': 'G2', 'prize': 5800},
    'G1': {'grade': 'G1', 'prize': 15000},
}

# 馬場状態の出方。実データの割合（良74% / 稍19% / 重9% / 不4%）に近づけている。
COND_CHOICES = ['良'] * 74 + ['稍'] * 19 + ['重'] * 9 + ['不'] * 4

# レース名の部品。実在のレース名は使わない。
NAME_HEAD = [
    '銀嶺', '朱雀', '若草', '白樺', '青嵐', '紅葉', '玄武', '常磐', '陽春', '霜月',
    '天嶺', '瑞穂', '早苗', '涼風', '黎明', '暁光', '磯風', '飛燕', '穂波', '雪解',
]
NAME_TAIL_OPEN = ['ステークス', 'カップ', '記念']
NAME_TAIL_COND = ['特別', '賞']

# 内回り・外回りがある競馬場。⭕ ビューアが描き分けられるよう race に持たせる。
DUAL_COURSES = {'中山', '京都', '阪神', '新潟'}

# ⭕ 重賞の開催場は実態に寄せる。プールが埋められる条件でも、G1が福島や小倉で
#    組まれると競馬として嘘になる。
GRADE_COURSES = {
    'G1': {'東京', '中山', '京都', '阪神'},
    'G2': {'東京', '中山', '京都', '阪神', '中京'},
    'G3': {'東京', '中山', '京都', '阪神', '中京', '新潟', '札幌', '函館', '福島', '小倉'},
}


def _candidates(cls, baseline=None, pool=None):
    """そのクラスで実際に組める (場所, 芝ダ, 距離) を集める。"""
    baseline = baseline or engine.load_baseline()
    out = []
    for key in baseline['base']:
        course, surface, distance = key.split('|')
        race = {'course': course, 'surface': surface, 'distance': int(distance),
                'class': cls}
        if rivals.is_supported(race, pool=pool):
            out.append((course, surface, int(distance)))
    out.sort()
    return out


def _date_seed(date, cls):
    """同じ日・同じクラスなら毎回同じ番組表になるようにする。

    ⭕ 組み込みの hash() は文字列に対してプロセスごとに違う値を返す（ハッシュの
       ランダム化）。それを使うとBotを再起動するたびに番組表が変わってしまう。
    """
    return zlib.crc32((date.isoformat() + "|" + cls).encode("utf-8"))


def is_race_day(date):
    return date.weekday() in RACE_WEEKDAYS


def next_race_day(date):
    """その日を含めて次の開催日を返す。"""
    for i in range(8):
        d = date + datetime.timedelta(days=i)
        if is_race_day(d):
            return d
    return date


def offers(cls, date, count=OFFER_COUNT, baseline=None, pool=None, aptitude=None):
    """その日にそのクラスで出走できるレースを count 本組む。

    Args:
        cls (str): 馬のクラス。
        date (datetime.date): 開催日。
        aptitude (dict): 馬の適性。あれば得意な条件を優先して提示する。

    Returns:
        list: race 辞書のリスト。engine.simulate() にそのまま渡せる形。
    """
    rng = random.Random(_date_seed(date, cls))
    cands = _candidates(cls, baseline, pool)
    allowed = GRADE_COURSES.get(cls)
    if allowed:
        cands = [c for c in cands if c[0] in allowed]
    if not cands:
        return []

    # ⭕ 得意条件ばかりだと選ぶ意味が無く、不得意ばかりだと出走できない。
    #    適性が分かっているときは重みをつけて、得意寄りに散らす。
    weights = []
    for course, surface, distance in cands:
        w = 1.0
        if aptitude:
            surface_key = 'turf' if surface == '芝' else 'dirt'
            band = rivals.distance_band(distance)
            w *= {'A': 3.0, 'B': 1.4, 'C': 0.5, 'D': 0.15, 'E': 0.05}.get(
                aptitude.get(surface_key, 'B'), 1.0)
            w *= {'A': 2.5, 'B': 1.3, 'C': 0.6, 'D': 0.2, 'E': 0.05}.get(
                aptitude.get(band, 'B'), 1.0)
        weights.append(w)

    picked, items = [], list(zip(cands, weights))
    for _ in range(min(count, len(items))):
        total = sum(w for _, w in items)
        r = rng.random() * total
        acc = 0.0
        for i, (c, w) in enumerate(items):
            acc += w
            if r <= acc:
                picked.append(c)
                items.pop(i)
                break

    info = CLASS_INFO.get(cls, CLASS_INFO['1勝'])
    races, used_names = [], set()
    for i, (course, surface, distance) in enumerate(picked):
        races.append({
            'id': f"{date.isoformat()}-{cls}-{i}",
            'name': _race_name(rng, cls, used_names),
            'date': date.isoformat(),
            'course': course,
            'surface': surface,
            'distance': distance,
            'cond': rng.choice(COND_CHOICES),
            'class': cls,
            'grade': info['grade'],
            'prize': info['prize'],
            # ⭕ ビューアが内回り・外回りを描き分けられるように持たせる。
            #    いまは距離で決めているだけの目安。
            'course_config': _config_of(course, distance),
        })
    return races


def _config_of(course, distance):
    if course not in DUAL_COURSES:
        return None
    return '外' if distance >= 1800 else '内'


def _race_name(rng, cls, used=None):
    """レース名を作る。⭕ 同じ日に同名のレースが並ばないよう既出を避ける。"""
    if cls in ('未勝利', '1勝'):
        return f"{cls}クラス"
    tails = NAME_TAIL_COND if cls in ('2勝', '3勝') else NAME_TAIL_OPEN
    used = used if used is not None else set()
    for _ in range(60):
        name = rng.choice(NAME_HEAD) + rng.choice(tails)
        if name not in used:
            used.add(name)
            return name
    return name


def find(race_id, cls, date, **kwargs):
    """id からレースを引き直す。番組表は日付とクラスから決定的に作られる。"""
    for race in offers(cls, date, **kwargs):
        if race['id'] == race_id:
            return race
    return None
