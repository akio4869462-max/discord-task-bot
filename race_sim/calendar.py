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

# 遠征費（万円）。美浦（関東）所属の想定で、東京・中山が地元。
# ⭕ クラスに関わらず一定にする（実態どおり）。未勝利の4着賞金(78万)より高いので
#    序盤は行き先で損得が出るが、G1級になれば誤差になる。
HOME_COURSES = {'東京', '中山'}
TRAVEL_COST = {
    '東京': 0, '中山': 0,
    '福島': 80, '新潟': 80,
    '中京': 150, '京都': 200, '阪神': 200,
    '小倉': 300, '函館': 300, '札幌': 300,
}

# ====================================================
# 🌏 海外遠征
# ====================================================
# ⭕ 月に1回（その月の最初の土曜）、国内G1の上に乗る目標として出す。実在のレース名は
#    使わず「場所＋条件」で呼ぶ。較正データは JRA のものしか無いので、基準タイムと
#    ビューアの形状は近い国内コース（proxy）から借りる。嘘にならない範囲の近似。
OVERSEAS_G1_WINS = 2        # 現役馬のG1勝利がこれ以上で海外の番組が出る
OVERSEAS_RIVAL_BOOST = 60   # 海外の出走馬は国内G1より一段強い（能力+60 ≒ z+0.3）
OVERSEAS = [
    {'venue': '香港', 'travel': 1500, 'prize': 30000,
     'races': [('芝', 1200, '東京'), ('芝', 1600, '東京'), ('芝', 2000, '東京')]},
    {'venue': 'ドバイ', 'travel': 3000, 'prize': 60000,
     'races': [('芝', 1800, '東京'), ('ダ', 2000, '東京')]},
    {'venue': 'フランス', 'travel': 3000, 'prize': 50000,
     'races': [('芝', 2400, '東京')]},
    {'venue': 'アメリカ', 'travel': 3000, 'prize': 60000,
     'races': [('ダ', 2000, '東京'), ('芝', 2400, '東京')]},
]


def is_overseas_day(date):
    """その月の最初の土曜が海外遠征日。"""
    return date.weekday() == 5 and date.day <= 7


def overseas_destination(date):
    return OVERSEAS[(date.year * 12 + date.month) % len(OVERSEAS)]


def overseas_offers(date):
    """海外遠征日の番組。G1の上に乗る1〜3本。遠征日でなければ空。"""
    if not is_overseas_day(date):
        return []
    dest = overseas_destination(date)
    rng = random.Random(_date_seed(date, f"海外:{dest['venue']}"))
    races = []
    for i, (surface, distance, proxy) in enumerate(dest['races']):
        races.append({
            'id': f"{date.isoformat()}-overseas-{i}",
            'name': f"{dest['venue']}国際招待 {surface}{distance}m",
            'date': date.isoformat(),
            'course': dest['venue'],
            'proxy_course': proxy,          # 基準タイムとビューアの形状を借りる国内コース
            'surface': surface,
            'distance': distance,
            'cond': rng.choice(COND_CHOICES),
            'class': 'G1',
            'grade': 'G1',
            'prize': dest['prize'],
            'travel': dest['travel'],
            'overseas': True,
            'rival_boost': OVERSEAS_RIVAL_BOOST,
            'course_config': None,
        })
    return races


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


def offers(cls, date, count=OFFER_COUNT, baseline=None, pool=None, aptitude=None, variant=0):
    """その日にそのクラスで出走できるレースを count 本組む。

    Args:
        cls (str): 馬のクラス。
        date (datetime.date): 開催日。
        aptitude (dict): 馬の適性。あれば得意な条件を優先して提示する。
        variant (int): 同じ日・同じクラスの別の番組。⭕ 多頭で同じクラスの馬が同じ日の
            番組を取り合ったとき（2頭出しは不可）に、2組目・3組目を出すために使う。

    Returns:
        list: race 辞書のリスト。engine.simulate() にそのまま渡せる形。
    """
    rng = random.Random(_date_seed(date, cls if variant == 0 else f"{cls}#{variant}"))
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
        picked.append(_weighted_pop(rng, items))

    # ⭕ 資金が無くても必ず出走できるよう、地元（遠征費0）のレースを1本は入れる。
    #    地元が1本も無ければ、残りの候補から地元を1本引いて最後の1本と入れ替える。
    if not any(c[0] in HOME_COURSES for c in picked):
        home = [(c, w) for c, w in items if c[0] in HOME_COURSES]
        if home:
            picked[-1] = _weighted_pop(rng, home)

    info = CLASS_INFO.get(cls, CLASS_INFO['1勝'])
    races, used_names = [], set()
    suffix = f"-v{variant}" if variant else ''
    for i, (course, surface, distance) in enumerate(picked):
        races.append({
            # ⭕ id は条件で決める。番号だと、適性で並び替えた別のレースが同じidになり、
            #    多頭のとき「同じレースか」の判定（2頭出し不可）が狂う。
            'id': f"{date.isoformat()}-{cls}-{course}{surface}{distance}{suffix}",
            'name': _race_name(rng, cls, used_names),
            'date': date.isoformat(),
            'course': course,
            'surface': surface,
            'distance': distance,
            'cond': rng.choice(COND_CHOICES),
            'class': cls,
            'grade': info['grade'],
            'prize': info['prize'],
            'travel': TRAVEL_COST.get(course, 0),
            # ⭕ ビューアが内回り・外回りを描き分けられるように持たせる。
            #    いまは距離で決めているだけの目安。
            'course_config': _config_of(course, distance),
        })
    return races


def _weighted_pop(rng, items):
    """(候補, 重み) のリストから重みつきで1つ引き、リストから取り除く。"""
    total = sum(w for _, w in items)
    r = rng.random() * total
    acc = 0.0
    for i, (c, w) in enumerate(items):
        acc += w
        if r <= acc:
            items.pop(i)
            return c
    return items.pop()[0]


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
