"""競走馬の育成ロジック。厩舎データの管理・成長・出走・世代交代を担う。

⭕ Discord には一切依存しない。文字列とプリミティブだけを返すので、ネットワーク無しで
   ユニットテストできる。この境界は既存の `*_logic.py` と同じ。

## 成長の考え方

活動の**累積分数を生データのまま持ち**、能力値は読み出すたびに導出する。

    能力 = 140 + 3.5 × (その能力に積んだ分)^0.70   （上限1000）

⭕ 能力値そのものを保存すると、成長カーブを調整したときに過去の記録と辻褄が合わなく
   なる。分数を持っておけば係数を変えるだけで全部が follow する。これは
   CLAUDE.md の「データ形式の移行は読み込み時に行う」と同じ思想。

設計の全体像と数字の根拠は docs/RACE_DESIGN.md を参照。
"""

import json
import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from race_sim import calendar as race_calendar
from race_sim import engine, rivals

STABLE_FILE = os.path.join('data', 'stable.json')
# 旧・就活RPGのデータ。読み込み時に初代馬へ読み替える。
LEGACY_PLAYER_FILE = os.path.join('data', 'player_data.json')

JST = timezone(timedelta(hours=9))

# ====================================================
# ⚙️ 成長と育成の定数
# ====================================================
BASE_ABILITY = 140          # デビュー時の能力（未勝利クラス相当）
# ⭕ 「配合も育成もかなり上手くやって、G1を7勝」になるようシミュレーションで決めた。
#    6.968 だった頃は週4時間でも20戦15勝して無双していた。
#    普通(週4h) 6勝・G1 0勝 ／ 良い(週9h) 8勝・G1 1勝 ／ 最良(週14h＋最良の配合) 14勝・G1 7勝。
GROWTH_K = 3.5
GROWTH_EXP = 0.70           # 逓減の効き。序盤ほど伸びやすい
ABILITY_CAP = 1000          # 「G1を大きく超える怪物」の水準。最良の配合と育成で届く

PARAMS = engine.JST_PARAMS

# 成長型。現役のどの時期かで伸びの係数が変わる（デビュー時 → 引退時）。
# ⭕ 現役平均ではほぼ同じになるようにして、難易度の較正（G1 7勝）を崩さない。
#    早熟は序盤で稼いで海外へ、晩成は15戦目以降に勝負、という枠の使い方が生まれる。
GROWTH_TYPES = ('早熟', '普通', '晩成')
GROWTH_TYPE_WEIGHTS = (25, 50, 25)
GROWTH_TYPE_CURVE = {'早熟': (1.12, 0.92), '普通': (1.0, 1.0), '晩成': (0.90, 1.12)}
GROWTH_TYPE_CAP = {'早熟': 920, '普通': ABILITY_CAP, '晩成': ABILITY_CAP}
GROWTH_TYPE_INHERIT = 0.70   # 両親が同じ型なら、この確率でその型
# 今週の重点。活動の配分のうちこれだけを重点の能力へ寄せる（合計は変えない）
FOCUS_SHIFT = 0.15
PARAM_NAMES = {
    'speed': 'スピード', 'stamina': 'スタミナ', 'power': 'パワー',
    'guts': '根性', 'wit': '賢さ', 'dash': '瞬発力',
}

# 活動 → どの能力に何割入るか
# ⭕ 1つの活動が複数の能力を育てる形にしている。入口は4つしかないので、
#    1活動＝1能力にすると供給源の無い能力が出る（書類を廃止して根性が浮いた）。
ACTIVITY_PARAMS = {
    'programming': {'speed': 0.6, 'guts': 0.4},   # 💻 開発作業・集中タイマー
    'reading': {'wit': 0.7, 'guts': 0.3},         # 📚 インプット・過去問演習
    'training': {'stamina': 0.5, 'power': 0.5},   # 💪 筋トレ
    'typing': {'dash': 0.7, 'speed': 0.3},        # ⌨️ タイピング訓練
    # ⭕ 旧・就活RPGの「書類作成」。UIからは消したが、古いタスクが完了されたときに
    #    落ちないよう対応だけ残す。
    'document': {'guts': 1.0},
}
# ⭕ 筋トレとタイピングは実施日しか記録していない（分を持たない）ので回数で換算する。
# この値は実際の所要時間（どちらも15分程度）とは切り離した「ゲーム上の価値」。
# 開発作業は週1時間単位で記録されるのに対し、筋トレは週5回×15分＝75分しか入らない。
# この5〜10倍の時間差は ACTIVITY_PARAMS の重みをどう配分しても埋まらず、
# 15分のままだとスタミナ・パワーがスピードの1/3で止まる（4週後 372 vs 989）。
# 60分相当にするとこの差が 2.66倍→ 1.46倍まで縮まる。これ以上上げても
# 律速の能力が賢さ（インプット）に移るだけで差は縮まらないので、60で止める。
TRAINING_MINUTES = 60
TYPING_MINUTES = 60

RETIRE_STARTS = 20          # 何戦（出走枠）で引退するか
# ⭕ 多頭化：主戦馬1頭＋併せ馬（最大2頭）。記録は主戦に全部入り、併せ馬には同じ記録の
#    SUB_SHARE が自動で入る（併せ馬効果）。「どの馬を調教するか」は決めなくてよく、
#    決めるのは「誰を主戦にするか」だけ。同じレースへの2頭出しは不可。
MAX_HORSES = 3
SUB_SHARE = 0.5
AUCTION_SIZE = 6            # セリに出る仔馬の頭数
AUCTION_PRICE_RATIO = 0.8   # 仔馬の値段 ＝ 両親のクラスの種付け料の平均 × この倍率
# ⭕ 海外遠征はその週の2開催ぶんを使う。引退は出走枠で数えるので、枠を2つ消費させないと
#    「1走減る週」が費用にならず、むしろ調教の週が増えて得になってしまう。
OVERSEAS_SLOTS = 2
OVERSEAS_REST_DAYS = 5      # 海外遠征のあと、次の開催日（水曜）まで出走できない
OVERSEAS_STUD_BONUS = 0.50  # 海外G1勝ちの種牡馬価値（国内G1勝ちは +0.30）
# 次世代が受け継ぐ、親の積み上げの割合
INHERIT_RATE = 0.10

# 着順 → 賞金の取り分
PRIZE_SHARE = {1: 1.0, 2: 0.40, 3: 0.25, 4: 0.15, 5: 0.10}

APTITUDE_GRADES = ('A', 'B', 'C', 'D')
BANDS = ('sprint', 'mile', 'middle', 'long')
BAND_NAMES = {'sprint': '短距離', 'mile': 'マイル', 'middle': '中距離', 'long': '長距離'}
APTITUDE_KEYS = ('turf', 'dirt') + BANDS

# ====================================================
# 🧬 配合
# ====================================================
# ⭕ 配合の狙いは能力より「適性を血で繋ぐ」こと。数字の根拠は docs/RACE_DESIGN.md §8。
BREEDING_OPEN_STARTS = 15   # 何戦目から次の配合を予約できるか
# 種付け料 ＝ そのクラスの1着賞金 × この倍率。
# ⭕ G1種牡馬（22,500万円）が「良い世代の獲得賞金（約4.5億）の半分」になる値。収入は
#    難易度（GROWTH_K）で変わるので、そちらを動かしたらこの比率を保つように直す。
STUD_FEE_RATIO = 1.5
MARKET_SIZE_PER_TIER = 2    # 市場に出す頭数（下級・中級・上級それぞれ）
MARKET_TIERS = (('未勝利', '1勝', '2勝'), ('3勝', 'OP', 'G3'), ('G2', 'G1'))
APTITUDE_MUTATION = 0.15    # 適性が親から受け継いだ段からずれる確率
PEDIGREE_DEPTH = 4          # 血統表を何代まで保存するか
# 市場の馬の種牡馬価値。成績を持たないのでクラスで決める。
MARKET_STUD_VALUE = {'G1': 1.30, 'G2': 1.20, 'G3': 1.15, 'OP': 1.10}

# 初代馬の名前の候補。実在馬名と衝突しないものだけを使う。
NAME_HEAD = ['ミライ', 'アオゾラ', 'コウテイ', 'シンゲツ', 'ハルカゼ', 'ホシノ', 'トキワ',
             'セイラン', 'ユウヅキ', 'カゲロウ', 'シラユキ', 'アカツキ', 'クロガネ', 'スバル']
NAME_TAIL = ['ドリーム', 'ブレイブ', 'ランナー', 'クラウン', 'フラッグ', 'アロー', 'ノヴァ',
             'グロウ', 'テイオー', 'ジャーニー', 'ソレイユ', 'リベンジ', 'ワルツ', 'ライト']


def _load_json(path, default):
    """指定したJSONファイルを読み込みます。存在しない・壊れている場合はdefaultを返します。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [ERROR] {path} の読み込みに失敗しました: {e}")
        return default


# ====================================================
# 能力の導出
# ====================================================
def ability_of(minutes, factor=1.0, cap=ABILITY_CAP):
    """その能力に積んだ分数から能力値を求めます。factor は成長型による伸びの係数。"""
    if minutes <= 0:
        return BASE_ABILITY
    return min(cap, int(round(BASE_ABILITY + GROWTH_K * factor * minutes ** GROWTH_EXP)))


def growth_factor(gtype, progress):
    """成長型と現役の進み具合（0=デビュー、1=引退）から伸びの係数を返します。"""
    a, b = GROWTH_TYPE_CURVE.get(gtype, (1.0, 1.0))
    progress = max(0.0, min(1.0, progress))
    return a + (b - a) * progress


def minutes_for(ability):
    """ある能力値に届くのに必要な分数（表示・テスト用の逆算）。"""
    if ability <= BASE_ABILITY:
        return 0.0
    return ((ability - BASE_ABILITY) / GROWTH_K) ** (1 / GROWTH_EXP)


def derive_params(growth, gtype='普通', progress=0.0):
    """成長の生データ（分）から6つの能力値を導出します。"""
    factor = growth_factor(gtype, progress)
    cap = GROWTH_TYPE_CAP.get(gtype, ABILITY_CAP)
    return {k: ability_of(growth.get(k, 0), factor, cap) for k in PARAMS}


def params_of(horse):
    """現役馬の今の能力値（成長型と現役の進み具合を織り込む）。"""
    progress = slots_used(horse) / RETIRE_STARTS
    return derive_params(horse['growth'], horse.get('growth_type', '普通'), progress)


def random_growth_type(rng):
    return rng.choices(GROWTH_TYPES, weights=GROWTH_TYPE_WEIGHTS)[0]


def inherit_growth_type(sire_type, dam_type, rng):
    """両親が同じ型なら7割でその型。違えばどちらか。"""
    if sire_type == dam_type:
        return sire_type if rng.random() < GROWTH_TYPE_INHERIT else random_growth_type(rng)
    return rng.choice([sire_type, dam_type])


def total_minutes(growth):
    return sum(growth.get(k, 0) for k in PARAMS)


# ====================================================
# 厩舎データ
# ====================================================
def _new_growth():
    return {k: 0.0 for k in PARAMS}


def _random_aptitude(rng):
    """得意な馬場と距離を1つずつ持ち、そこから離れるほど苦手になる適性を作ります。"""
    turf_horse = rng.random() < 0.55
    apt = {'turf': 'A' if turf_horse else 'C', 'dirt': 'C' if turf_horse else 'A'}
    main = rng.choice(BANDS)
    order = list(BANDS)
    main_i = order.index(main)
    for i, band in enumerate(order):
        gap = abs(i - main_i)
        apt[band] = APTITUDE_GRADES[min(gap, len(APTITUDE_GRADES) - 1)]
    return apt


def suggest_name(rng=None, pool=None):
    """馬名の候補を1つ返します。ライバル馬と重複しないものを選びます。"""
    rng = rng or random.Random()
    try:
        taken = {h['name'] for h in (pool or rivals.load_pool())['horses']}
    except (IOError, KeyError):
        taken = set()
    for _ in range(80):
        name = rng.choice(NAME_HEAD) + rng.choice(NAME_TAIL)
        if name not in taken:
            return name
    return rng.choice(NAME_HEAD) + rng.choice(NAME_TAIL)


def new_horse(name=None, growth=None, pedigree=None, sex=None, today=None, rng=None, line=None,
              growth_type=None):
    """新しい現役馬を1頭つくります。"""
    rng = rng or random.Random()
    today = today or datetime.now(JST).date()
    name = name or suggest_name(rng)
    return {
        'id': str(uuid.uuid4()),
        'name': name,
        'growth_type': growth_type or random_growth_type(rng),
        'line': line or name,                    # 系統。父から受け継ぐ。初代馬は自分が祖
        'blood': {'nick': False, 'temper': False, 'tags': []},   # 配合で決まる血の効き目
        'sex': sex or rng.choice(['牡', '牝']),
        'debut': today.isoformat(),
        'growth': growth or _new_growth(),
        # 生まれたときに持っていた積み上げ（配合で受け継いだ分）。週の調教量から除くために持つ
        'birth_minutes': total_minutes(growth) if growth else 0.0,
        'style': '差し',
        'aptitude': _random_aptitude(rng),
        'class': '未勝利',
        'record': {'starts': 0, 'win': 0, 'place': 0, 'show': 0, 'prize': 0},
        'slots': 0,                      # 引退までの出走枠の消費（海外遠征は2）
        'rest_until': None,
        # ⭕ 血統表は再帰ノード {'name', 'sire': node|None, 'dam': node|None} で持つ。
        #    名前の平面だとインブリードやニックスを見るときに作り直しになる。
        'pedigree': pedigree or {'sire': None, 'dam': None},
        'history': [],
        'entry': None,
        'breeding_plan': None,
    }


def _default_stable(today=None):
    # ⭕ 最初から3頭。能力は低くていいから頭数が欲しい、という要望。主戦は1頭目
    horses = [new_horse(today=today) for _ in range(MAX_HORSES)]
    return _bind({
        'generation': 1,
        'horses': horses,
        'main': horses[0]['id'],
        'selected': horses[0]['id'],
        'retired': [],
        'stallions': [],
        'funds': 0,
        'last_active_date': None,
        'current_streak': 0,
        'stable_filled': True,
    })


def fill_stable(data, today=None):
    """厩舎を MAX_HORSES 頭まで埋めます（一度だけ）。多頭化前のデータの読み替え用。"""
    if data.get('stable_filled'):
        return []
    added = []
    while len(data['horses']) < MAX_HORSES:
        h = new_horse(today=today)
        data['horses'].append(h)
        added.append(h)
    data['stable_filled'] = True
    return added


def _bind(data):
    """data['current'] を「いま選んでいる馬」（horses の中の同じ dict）に向けます。

    ⭕ 既存のロジックと UI は data['current'] を前提に書かれている。多頭化しても
       「選んでいる馬」をここに束ねておけば、ステータス・出走登録・配合はそのまま動く。
       保存時には落とす（save_stable）。
    """
    horses = data.get('horses') or []
    if not horses:
        horse = new_horse()
        data['horses'] = horses = [horse]
        data['main'] = data['selected'] = horse['id']
    ids = {h['id'] for h in horses}
    if data.get('main') not in ids:
        data['main'] = horses[0]['id']
    if data.get('selected') not in ids:
        data['selected'] = data['main']
    data['current'] = next(h for h in horses if h['id'] == data['selected'])
    return data


def horse_by_id(data, horse_id):
    return next((h for h in data['horses'] if h['id'] == horse_id), None)


def main_horse(data):
    return horse_by_id(data, data['main']) or data['horses'][0]


def is_main(data, horse):
    return horse['id'] == data.get('main')


def select_horse(data, horse_id, save=True):
    """厩舎メニューで見る馬を切り替えます。"""
    if horse_by_id(data, horse_id) is None:
        raise ValueError('その馬はいません')
    data['selected'] = horse_id
    _bind(data)
    if save:
        save_stable(data)
    return data['current']


def set_main(data, horse_id, save=True):
    """主戦馬を切り替えます。記録の全部が入る馬。"""
    if horse_by_id(data, horse_id) is None:
        raise ValueError('その馬はいません')
    data['main'] = horse_id
    if save:
        save_stable(data)
    return horse_by_id(data, horse_id)


def _pedigree_node(name, sire=None, dam=None, line=None):
    if not name or name == '－':
        return None
    node = {'name': name, 'sire': sire, 'dam': dam}
    if line:
        node['line'] = line                       # 系統（ニックスの判定に使う）
    return node


def _trim_pedigree(node, depth=PEDIGREE_DEPTH):
    """血統表を depth 代で打ち切ります（世代を重ねると指数的に膨らむ）。"""
    if node is None or depth <= 0:
        return None
    out = {'name': node['name'],
           'sire': _trim_pedigree(node.get('sire'), depth - 1),
           'dam': _trim_pedigree(node.get('dam'), depth - 1)}
    if node.get('line'):
        out['line'] = node['line']
    return out


def _migrate_pedigree(pedigree):
    """旧形式 {'sire': '名前', 'dam': '－'} を再帰ノードへ読み替えます。"""
    fixed = {}
    for side in ('sire', 'dam'):
        value = (pedigree or {}).get(side)
        fixed[side] = _pedigree_node(value) if isinstance(value, str) else value
    return fixed


def _migrate_legacy(stable, legacy):
    """旧・就活RPGの累積時間を初代馬の成長へ読み替えます。

    ⭕ 移行スクリプトは書かない。読み込み関数の中で旧形式を検出して補完するのが
       このリポジトリの流儀（CLAUDE.md「データ形式の移行は読み込み時に行う」）。
       レベル・EXP・バッジは競走馬の育成に対応するものが無いので引き継がない。
    """
    growth = stable['current']['growth']
    growth['speed'] += legacy.get('programming', 0)
    growth['guts'] += legacy.get('document', 0)
    growth['wit'] += legacy.get('reading', 0)
    stable['last_active_date'] = legacy.get('last_active_date')
    stable['current_streak'] = legacy.get('current_streak', 0)
    stable['migrated_from_rpg'] = True
    return stable


def load_stable(today=None):
    """厩舎データを読み込みます。初回は旧RPGのデータから初代馬を作ります。"""
    data = _load_json(STABLE_FILE, None)
    if data is None:
        data = _default_stable(today)
        legacy = _load_json(LEGACY_PLAYER_FILE, None)
        if legacy:
            data = _migrate_legacy(data, legacy)
        return data

    # 古い厩舎データに新しいキーが足りなければ補う
    data.setdefault('retired', [])
    data.setdefault('stallions', [])
    data.setdefault('current_streak', 0)
    data.setdefault('last_active_date', None)
    # ⭕ 1頭だった頃のデータ（current）を horses に読み替える
    if 'horses' not in data:
        data['horses'] = [data['current']] if data.get('current') else []
        if data['horses']:
            data['main'] = data['selected'] = data['horses'][0]['id']
    data.pop('current', None)
    fill_stable(data, today)                  # 多頭化前のデータは3頭まで埋める（一度だけ）
    for horse in data['horses']:
        horse.setdefault('generation', data.get('generation', 1))
        horse.setdefault('entry', None)
        horse.setdefault('history', [])
        horse.setdefault('breeding_plan', None)
        horse.setdefault('rest_until', None)
        horse.setdefault('slots', horse.get('record', {}).get('starts', 0))
        horse.setdefault('blood', {'nick': False, 'temper': False, 'tags': []})
        horse.setdefault('line', line_of(horse))
        horse.setdefault('growth_type', '普通')   # ⭕ 途中の馬の能力を急に変えないので普通
        horse.setdefault('record', {'starts': 0, 'win': 0, 'place': 0, 'show': 0, 'prize': 0})
        horse['pedigree'] = _migrate_pedigree(horse.get('pedigree'))
        for k in PARAMS:
            horse.setdefault('growth', {}).setdefault(k, 0.0)
    data.setdefault('focus', None)

    # ⭕ 資金は配合で初めて使い道ができた。それまでの賞金は成績にしか残っていないので、
    #    現役馬と引退馬の賞金の合計で補う（読み込み時移行の流儀）。
    if 'funds' not in data:
        data['funds'] = sum(h.get('record', {}).get('prize', 0)
                            for h in data['horses'] + data['retired'] if h)

    # 引退馬は配合の相手になるので、選ぶためのidと血統表を持たせる
    retired_by_name = {h['name']: h for h in data['retired']}
    for s in data['stallions']:
        source = retired_by_name.get(s['name'], {})
        s.setdefault('id', source.get('id') or str(uuid.uuid4()))
        s['pedigree'] = _migrate_pedigree(s.get('pedigree') or source.get('pedigree'))
        s.setdefault('line', source.get('line') or line_of(s))
    return _bind(data)


def save_stable(data):
    try:
        os.makedirs(os.path.dirname(STABLE_FILE), exist_ok=True)
        payload = {k: v for k, v in data.items() if k != 'current'}   # current は horses の別名
        with open(STABLE_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"⚠️ [ERROR] 厩舎データの保存に失敗しました: {e}")


# ====================================================
# 調子と連続記録
# ====================================================
def _update_streak(data, today):
    """今日の活動で連続記録を更新します。"""
    today_str = today.isoformat()
    last = data.get('last_active_date')
    if last == today_str:
        return data['current_streak']
    yesterday = (today - timedelta(days=1)).isoformat()
    data['current_streak'] = data.get('current_streak', 0) + 1 if last == yesterday else 1
    data['last_active_date'] = today_str
    return data['current_streak']


def condition_of(data, today=None, horse=None):
    """調子（-2〜+2）。連続記録が伸びるほど良く、間が空くほど落ちます。"""
    today = today or datetime.now(JST).date()
    last = data.get('last_active_date')
    if not last:
        return 0
    gap = (today - date.fromisoformat(last)).days
    if gap >= 4:
        return -2
    if gap >= 2:
        return -1
    streak = data.get('current_streak', 0)
    cond = 2 if streak >= 21 else (1 if streak >= 7 else 0)
    horse = horse or data.get('current') or {}
    if horse.get('blood', {}).get('temper'):
        # ⭕ 気性難は日によって調子が荒れる（3日に1日ほど1段落ちる）。日付と馬で決まる
        import zlib
        if zlib.crc32(f"{today.isoformat()}|{horse.get('id', '')}".encode('utf-8')) % 3 == 0:
            cond -= 1
    return max(-2, cond)


CONDITION_LABELS = {2: '絶好調', 1: '好調', 0: '平常', -1: 'やや不調', -2: '不調'}


# ====================================================
# 成長
# ====================================================
def add_growth(category, minutes, today=None, data=None, save=True, update_streak=True):
    """活動を記録して馬を成長させます。

    Args:
        category (str): ACTIVITY_PARAMS のキー。
        minutes (float): 活動時間（分）。
        today (date): 基準日（省略時は今日。テスト用の注入口）。
        update_streak (bool): 連続記録を更新するか。
            ⭕ 過去の日をあとから記録するとき（backfill）は False。連続記録は
               「今日やったか」の指標なので、昔の日を足しても伸ばしてはいけないし、
               last_active_date を過去に巻き戻してもいけない。

    Returns:
        dict: {'gains': {能力: 上がった値}, 'streak': int, 'condition': int,
               'capped': bool, 'horse': 現役馬}
    """
    today = today or datetime.now(JST).date()
    data = data if data is not None else load_stable(today)
    horse = main_horse(data)

    weights = ACTIVITY_PARAMS.get(category)
    if not weights or minutes <= 0:
        return {'gains': {}, 'streak': data.get('current_streak', 0),
                'condition': condition_of(data, today), 'capped': False, 'horse': horse}
    weights = weights_with_focus(weights, focus_param(data, today))

    before = params_of(horse)
    for h in data['horses']:
        share_of = 1.0 if h is horse else SUB_SHARE          # 併せ馬には半分
        for param, share in weights.items():
            h['growth'][param] = h['growth'].get(param, 0) + minutes * share * share_of
    after = params_of(horse)

    gains = {p: after[p] - before[p] for p in PARAMS if after[p] != before[p]}
    streak = _update_streak(data, today) if update_streak else data.get('current_streak', 0)
    capped = any(after[p] >= ABILITY_CAP for p in weights)

    if save:
        save_stable(data)
    return {'gains': gains, 'streak': streak, 'condition': condition_of(data, today),
            'capped': capped, 'horse': horse}


def log_training(today=None, data=None, save=True, update_streak=True):
    """筋トレ1セッション。⭕ 時間を記録していないので回数で換算する。"""
    return add_growth('training', TRAINING_MINUTES, today=today, data=data,
                      save=save, update_streak=update_streak)


def log_typing(today=None, data=None, save=True, update_streak=True):
    """タイピング1ドリル。同じく回数で換算する。"""
    return add_growth('typing', TYPING_MINUTES, today=today, data=data,
                      save=save, update_streak=update_streak)


# 1回の「あとから記録」で受け付ける日付の数
BACKFILL_MAX_DATES = 14


def backfill(category, dates, minutes=None, data=None, save=True):
    """過去の日ぶんの活動をまとめて記録します。

    ⭕ やっているのに記録が残っていない、という状態を後から埋められるようにする。
       タイピングは機能追加から18日で記録1件、筋トレは0件だった。ボタンを押し忘れる
       だけで能力が育たないのでは、育成として成立しない。

    Args:
        category (str): ACTIVITY_PARAMS のキー。
        dates (list): 対象の日付（date のリスト）。
        minutes (float): 1日あたりの分数。筋トレ・タイピングは省略時に既定値を使う。

    Returns:
        dict: add_growth と同じ形。gains は全日ぶんの合計。
    """
    data = data if data is not None else load_stable()
    if minutes is None:
        minutes = {'training': TRAINING_MINUTES, 'typing': TYPING_MINUTES}.get(category)
    if not minutes or not dates:
        return {'gains': {}, 'streak': data.get('current_streak', 0),
                'condition': condition_of(data), 'capped': False,
                'horse': main_horse(data), 'days': 0}

    before = params_of(main_horse(data))
    result = None
    for day in dates[:BACKFILL_MAX_DATES]:
        result = add_growth(category, minutes, today=day, data=data,
                            save=False, update_streak=False)
    after = params_of(main_horse(data))

    if save:
        save_stable(data)
    result = result or {}
    result['gains'] = {p: after[p] - before[p] for p in PARAMS if after[p] != before[p]}
    result['days'] = len(dates[:BACKFILL_MAX_DATES])
    return result


# ====================================================
# 出走
# ====================================================
def player_entry(horse, data=None, today=None):
    """自分の馬を rivals.build_field() に渡せる形にします。"""
    return {
        'name': horse['name'],
        'params': params_of(horse),
        'aptitude': dict(horse['aptitude']),
        'style': horse.get('style', '差し'),
        'condition': condition_of(data, today, horse) if data is not None else 0,
        # 気性難（濃いインブリード）は不利を受けやすい
        'trouble_scale': TEMPER_TROUBLE_SCALE if horse.get('blood', {}).get('temper') else 1.0,
    }


RACE_HOUR = 20              # 開催日にレースが走る時刻（main.py の夜の分岐と同じ）


def available_races(data=None, on=None, now=None, horse=None):
    """次の開催日に出走できるレースを返します。

    ⭕ 開催日の20:00を過ぎていたら、その日の番組はもう走っているので次の開催日を出す。
       そうしないと当日の日付で登録され、次の開催日に「古いレース」として走ってしまう。
    ⭕ 他の馬が登録済みのレースは出さない（同じレースへの2頭出しは不可）。
    """
    data = data if data is not None else load_stable()
    horse = horse or data['current']
    if on is None:
        now = now or datetime.now(JST)
        on = now.date()
        if race_calendar.is_race_day(on) and now.hour >= RACE_HOUR:
            on += timedelta(days=1)
    day = race_calendar.next_race_day(on)
    if rest_reason(horse, day):
        return day, []
    taken = {h['entry']['id'] for h in data.get('horses', []) if h is not horse and h.get('entry')}
    # ⭕ 同じクラスの馬が同じ日の番組を取り合って地元（遠征費0）が残っていなければ、
    #    別の番組（variant）を出す。1頭なら variant 0 のまま。
    races = []
    for variant in range(MAX_HORSES):
        races = [r for r in race_calendar.offers(horse['class'], day, aptitude=horse['aptitude'], variant=variant)
                 if r['id'] not in taken]
        if any(r.get('travel', 0) == 0 for r in races):
            break
    if overseas_eligible(horse):
        races = races + [r for r in race_calendar.overseas_offers(day) if r['id'] not in taken]
    return day, races


def enter_race(race, style=None, data=None, save=True, horse=None):
    """出走を登録します。脚質はここで宣言します（意思であって確約ではない）。

    遠征費（race['travel']）は登録時に資金から引きます。番組表には遠征費0の地元レースが
    必ず1本あるので、資金が無くても出走はできる。

    Raises:
        ValueError: 遠征費を払えない
    """
    data = data if data is not None else load_stable()
    horse = horse or data['current']
    travel = race.get('travel', 0)
    if any(h is not horse and h.get('entry') and h['entry']['id'] == race['id'] for h in data['horses']):
        raise ValueError("そのレースには別の馬を登録しています（同じレースへの2頭出しはできません）。")
    if travel > data.get('funds', 0):
        raise ValueError(f"遠征費が払えません（{travel:,}万円 ／ 手元 {data.get('funds', 0):,}万円）。"
                         f"地元（東京・中山）のレースなら遠征費はかかりません。")
    if horse.get('entry'):
        data['funds'] = data.get('funds', 0) + horse['entry'].get('travel', 0)   # 取り直しなら戻す
    data['funds'] = data.get('funds', 0) - travel
    if style:
        horse['style'] = style
    horse['entry'] = dict(race)
    if save:
        save_stable(data)
    return horse['entry']


def cancel_entry(data=None, save=True, horse=None):
    """出走登録を取り消し、遠征費を戻します。"""
    data = data if data is not None else load_stable()
    horse = horse or data['current']
    entry = horse.get('entry')
    if entry:
        data['funds'] = data.get('funds', 0) + entry.get('travel', 0)
    horse['entry'] = None
    if save:
        save_stable(data)


def _race_seed(horse, race):
    """馬とレースから決まるシード。同じ組み合わせなら結果は必ず同じになる。"""
    import zlib
    return zlib.crc32((horse['id'] + '|' + race['id']).encode('utf-8'))


def run_entry(data=None, today=None, save=True, horse=None):
    """登録したレースを実行し、結果を厩舎に反映します。

    Returns:
        dict/None: {'result': レース結果, 'finish': 着順, 'events': [文言], 'race': race}
            登録が無ければ None。
    """
    data = data if data is not None else load_stable()
    horse = horse or data['current']
    race = horse.get('entry')
    if not race:
        return None

    today = today or datetime.now(JST).date()
    seed = _race_seed(horse, race)
    entries = rivals.build_field(race, seed=seed, player=player_entry(horse, data, today))
    result = engine.simulate(race, entries, seed=seed)

    mine = next(h for h in result['horses'] if h['is_player'])
    horse['entry'] = None
    events = _apply_result(data, race, mine, today, len(result['horses']), horse)
    if save:
        save_stable(data)
    return {'result': result, 'finish': mine['finish'], 'events': events, 'race': race,
            'horse_name': horse['name']}


def run_entries(data=None, today=None, save=True):
    """登録されている全馬のレースを、主戦から順に実行します。

    Returns:
        list: run_entry() の結果のリスト（登録が無い馬は含まない）
    """
    data = data if data is not None else load_stable()
    order = sorted(list(data['horses']), key=lambda h: 0 if is_main(data, h) else 1)
    outcomes = []
    for horse in order:
        if horse.get('entry'):
            outcomes.append(run_entry(data=data, today=today, save=False, horse=horse))
    if save and outcomes:
        save_stable(data)
    return outcomes


def _apply_result(data, race, mine, today, field_size, horse=None):
    """着順を成績に反映し、昇級と引退を判定します。"""
    horse = horse or data['current']
    rec = horse['record']
    before = slots_used(horse)          # ⭕ starts を足す前に取る（古いデータは starts で補うため）
    rec['starts'] += 1
    if mine['finish'] == 1:
        rec['win'] += 1
    if mine['finish'] <= 2:
        rec['place'] += 1
    if mine['finish'] <= 3:
        rec['show'] += 1
    prize = int(race.get('prize', 0) * PRIZE_SHARE.get(mine['finish'], 0))
    rec['prize'] += prize
    data['funds'] = data.get('funds', 0) + prize     # 種付け料の原資

    overseas = bool(race.get('overseas'))
    horse['history'].append({
        'date': today.isoformat(), 'race': race['name'],
        'course': race['course'], 'surface': race['surface'], 'distance': race['distance'],
        'cond': race.get('cond', '良'), 'class': race['class'],
        'finish': mine['finish'], 'field': field_size,
        'time': mine['time'], 'last3f': mine['last3f'], 'style': mine['style'],
        'overseas': overseas,
    })

    # ⭕ 引退は「出走枠」で数える。海外遠征はその週の2開催ぶんを使うので2枠。
    #    成績（starts）は実際に走った数のまま。
    horse['slots'] = before + (OVERSEAS_SLOTS if overseas else 1)
    if overseas:
        horse['rest_until'] = (today + timedelta(days=OVERSEAS_REST_DAYS)).isoformat()

    events = []
    if mine['finish'] == 1:
        if overseas:
            events.append(f"🌏 海外G1制覇！ {race['course']}で勝ちました。")
        else:
            idx = engine.CLASS_ORDER.index(horse['class'])
            if idx < len(engine.CLASS_ORDER) - 1:
                horse['class'] = engine.CLASS_ORDER[idx + 1]
                events.append(f"🏆 勝利！ {horse['class']}クラスへ昇級しました。")
            else:
                events.append("🏆 G1制覇！")
        if not overseas and g1_wins(horse) == race_calendar.OVERSEAS_G1_WINS:
            events.append(f"🌏 G1を{g1_wins(horse)}勝。海外遠征（毎月最初の土曜）に出られるようになりました。")

    if before < BREEDING_OPEN_STARTS <= slots_used(horse):
        events.append(f"🧬 {BREEDING_OPEN_STARTS}戦目。次の世代の配合を予約できるようになりました。"
                      f"（残り{slots_left(horse)}戦）")
    if slots_used(horse) >= RETIRE_STARTS:
        events.append(retire(data, today, horse=horse))
    return events


def slots_used(horse):
    """引退までの出走枠をいくつ使ったか。

    ⭕ 枠は出走数を下回らない（海外遠征で上回ることはある）。古いデータや手で出走数を
       いじったデータでも辻褄が合うよう、大きいほうを取る。
    """
    return max(horse.get('slots', 0), horse['record']['starts'])


def slots_left(horse):
    return max(0, RETIRE_STARTS - slots_used(horse))


def g1_wins(horse):
    return sum(1 for h in horse.get('history', []) if h.get('class') == 'G1' and h.get('finish') == 1)


def overseas_eligible(horse):
    return g1_wins(horse) >= race_calendar.OVERSEAS_G1_WINS


def rest_reason(horse, day):
    """海外遠征の帯同で出走できない日なら、その理由を返します。"""
    until = horse.get('rest_until')
    if until and day.isoformat() <= until:
        return f"海外遠征から戻る途中です（{until} まで出走できません）。"
    return None


# ====================================================
# 引退と世代交代
# ====================================================
def stud_value(horse):
    """引退後の種牡馬・繁殖牝馬としての価値。次世代の初期能力に効きます。

    ⭕ 能力の上限に達したあとに積んだ時間を捨てないための受け皿。走り切った馬に
       注いだ時間が次の代に残るので、早々に上限へ達しても手が止まらない。
    """
    rec = horse.get('record', {})
    bonus = 1.0 + 0.05 * rec.get('win', 0)
    # ⭕ 「G1クラスで勝ち≧1」だと、G1に上がった馬は必ず7勝しているので全員が該当する。
    #    G1を勝った馬に限る。
    g1 = [h for h in horse.get('history', []) if h.get('class') == 'G1' and h.get('finish') == 1]
    if any(h.get('overseas') for h in g1):
        bonus += OVERSEAS_STUD_BONUS
    elif g1:
        bonus += 0.30
    return bonus


def retire(data, today=None, save=False, horse=None):
    """現役馬を引退させ、その馬の枠に仔を置きます。主戦が引退すれば仔が主戦を継ぎます。"""
    today = today or datetime.now(JST).date()
    horse = horse or data['current']
    horse['retired_on'] = today.isoformat()
    horse['final_params'] = params_of(horse)

    data['retired'].append(horse)
    # ⭕ 引退馬は配合の相手になるので、能力・成績・適性・血統を持った実体として残す。
    #    名前だけの飾りにするとデータ構造から作り直すことになる。
    data['stallions'].append({
        'id': horse['id'], 'name': horse['name'], 'sex': horse['sex'],
        'class': horse['class'], 'generation': horse.get('generation', 1),
        'params': horse['final_params'], 'growth': dict(horse['growth']),
        'aptitude': dict(horse['aptitude']), 'record': dict(horse['record']),
        'stud_value': round(stud_value(horse), 3),
        'pedigree': horse.get('pedigree') or {'sire': None, 'dam': None},
        'line': line_of(horse),
        'growth_type': horse.get('growth_type', '普通'),
    })

    rng = random.Random(horse['id'])
    plan = horse.get('breeding_plan')
    parent = horse['name']
    generation = horse.get('generation', 1) + 1
    data['generation'] = max(data.get('generation', 1), generation)

    # ⭕ 配合予約の無い併せ馬は、引退したら枠が空く。全部に仔を置くとセリの出番が来ない。
    #    主戦だけは（予約が無くても）必ず仔が継ぐ。
    if not plan and not is_main(data, horse):
        data['horses'] = [h for h in data['horses'] if h['id'] != horse['id']]
        if data.get('selected') == horse['id']:
            data['selected'] = data['main']
        _bind(data)
        if save:
            save_stable(data)
        return (f"🎓 {parent} が{RETIRE_STARTS}戦を走り切って引退しました。"
                f"配合の予約が無かったので枠が空きました（{len(data['horses'])}/{MAX_HORSES}頭）。"
                f"セリか配合で補充できます。")

    if plan:
        foal = breed(horse, plan['partner'], name=plan.get('foal_name'), today=today, rng=rng)
        tags = foal.get('blood', {}).get('tags', [])
        born = (f"🧬 {_sire_dam(horse, plan['partner'])} の仔、"
                f"第{generation}世代 {foal['name']} がデビューします。"
                + (f"（{' '.join(tags)}）" if tags else ''))
    else:
        inherited = {k: horse['growth'].get(k, 0) * INHERIT_RATE * stud_value(horse)
                     for k in PARAMS}
        foal = new_horse(
            growth=inherited,
            pedigree={'sire': pedigree_of(horse) if horse['sex'] == '牡' else None,
                      'dam': pedigree_of(horse) if horse['sex'] == '牝' else None},
            today=today, rng=rng)
        born = f"第{generation}世代 {foal['name']} がデビューします。"
    foal['generation'] = generation

    # ⭕ 引退した馬の枠に仔を置く。主戦・選択がその馬を指していれば仔が引き継ぐ
    idx = next((i for i, h in enumerate(data['horses']) if h['id'] == horse['id']), None)
    if idx is None:
        data['horses'].append(foal)
    else:
        data['horses'][idx] = foal
    if data.get('main') == horse['id']:
        data['main'] = foal['id']
    if data.get('selected') == horse['id']:
        data['selected'] = foal['id']
    _bind(data)
    if save:
        save_stable(data)
    return f"🎓 {parent} が{RETIRE_STARTS}戦を走り切って引退しました。{born}"


# ====================================================
# 配合
# ====================================================
def pedigree_of(parent):
    """親（現役馬・引退馬・市場馬）を血統表のノードにします。"""
    ped = parent.get('pedigree')
    if ped is None and 'sire' in parent:
        # 市場馬はプールの父(sire)と母父(bms)しか持たない。母は名無しなので「○○の母」。
        ped = {'sire': _pedigree_node(parent.get('sire')),
               'dam': _pedigree_node(f"{parent['name']}の母" if parent.get('bms') else None,
                                     sire=_pedigree_node(parent.get('bms')))}
    ped = _migrate_pedigree(ped)
    return _trim_pedigree(_pedigree_node(parent['name'], ped.get('sire'), ped.get('dam'), line=line_of(parent)))


def _sire_dam(a, b):
    sire, dam = (a, b) if a['sex'] == '牡' else (b, a)
    return f"{sire['name']} × {dam['name']}"


def parent_minutes(parent):
    """親の積み上げ（分）。市場馬は能力値しか持たないので逆算します。"""
    if parent.get('growth'):
        return {k: parent['growth'].get(k, 0) for k in PARAMS}
    return {k: minutes_for(parent.get('params', {}).get(k, BASE_ABILITY)) for k in PARAMS}


def parent_stud_value(parent):
    if 'stud_value' in parent:
        return parent['stud_value']
    if 'record' in parent:
        return stud_value(parent)
    return MARKET_STUD_VALUE.get(parent.get('class'), 1.0)


def inherit_aptitude(sire_apt, dam_apt, rng):
    """適性を項目ごとに父か母から受け継ぎ、ときどき1段ずらします。"""
    apt = {}
    for key in APTITUDE_KEYS:
        grade = rng.choice([sire_apt.get(key, 'B'), dam_apt.get(key, 'B')])
        if rng.random() < APTITUDE_MUTATION:
            i = APTITUDE_GRADES.index(grade) if grade in APTITUDE_GRADES else 1
            # ⭕ 端（A/D）では内側にしかずれない。端で押し戻すと変異の半分が消える。
            steps = [d for d in (-1, 1) if 0 <= i + d < len(APTITUDE_GRADES)]
            grade = APTITUDE_GRADES[i + rng.choice(steps)]
        apt[key] = grade
    return apt


def breed(a, b, name=None, today=None, rng=None):
    """2頭から仔を1頭つくります。どちらが父でも構いません。

    能力の初期値 ＝ 両親の積み上げの平均 × INHERIT_RATE × 両親の種牡馬価値の平均
    """
    rng = rng or random.Random()
    sire, dam = (a, b) if a['sex'] == '牡' else (b, a)
    ma, mb = parent_minutes(sire), parent_minutes(dam)
    value = (parent_stud_value(sire) + parent_stud_value(dam)) / 2
    fx = blood_effects(sire, dam)
    growth = {k: (ma[k] + mb[k]) / 2 * INHERIT_RATE * value * (1 + fx['bonus']) for k in PARAMS}
    foal = new_horse(name=name, growth=growth,
                     pedigree={'sire': pedigree_of(sire), 'dam': pedigree_of(dam)},
                     today=today, rng=rng, line=line_of(sire),
                     growth_type=inherit_growth_type(growth_type_of(sire), growth_type_of(dam), rng))
    foal['aptitude'] = inherit_aptitude(sire['aptitude'], dam['aptitude'], rng)
    if fx['nick']:
        # ⭕ ニックスは適性でも効く：親で一番差のある項目を、良いほうで確定させる
        def grade(apt, k):
            return APTITUDE_GRADES.index(apt.get(k, 'B')) if apt.get(k, 'B') in APTITUDE_GRADES else 1
        gap, key = max((abs(grade(sire['aptitude'], k) - grade(dam['aptitude'], k)), k) for k in APTITUDE_KEYS)
        if gap > 0:
            foal['aptitude'][key] = APTITUDE_GRADES[min(grade(sire['aptitude'], key), grade(dam['aptitude'], key))]
    foal['blood'] = {'nick': fx['nick'], 'temper': fx['temper'], 'tags': fx['tags']}
    return foal



# ====================================================
# 🎯 今週の重点（調教メニュー）
# ====================================================
# ⭕ 活動と能力の対応は固定だが、週に1回だけ「重点」を選べる。その週の記録は活動の配分の
#    うち FOCUS_SHIFT ぶんを重点の能力へ寄せる。合計は変えないので総量は同じで、
#    振り先だけが動く。「今週は何をやるか」が育成と直結する。
def week_key(day):
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def focus_param(data, today=None):
    """今週の重点の能力。指定が無い・先週のものなら None。"""
    today = today or datetime.now(JST).date()
    focus = data.get('focus')
    if focus and focus.get('week') == week_key(today) and focus.get('param') in PARAMS:
        return focus['param']
    return None


def set_focus(param, data=None, today=None, save=True):
    """今週の重点を決めます。param が None なら解除。"""
    today = today or datetime.now(JST).date()
    data = data if data is not None else load_stable(today)
    if param is not None and param not in PARAMS:
        raise ValueError('不明な能力です')
    data['focus'] = {'param': param, 'week': week_key(today)} if param else None
    if save:
        save_stable(data)
    return param


def weights_with_focus(weights, focus):
    """活動の配分に重点を効かせる。重点の能力へ FOCUS_SHIFT を寄せ、残りは比例で削る。"""
    if not focus:
        return dict(weights)
    others = {k: v for k, v in weights.items() if k != focus}
    total_others = sum(others.values())
    if total_others <= 0:
        return dict(weights)
    shift = min(FOCUS_SHIFT, total_others)
    out = {k: v * (1 - shift / total_others) for k, v in others.items()}
    out[focus] = weights.get(focus, 0.0) + shift
    return out


def growth_type_of(parent):
    """成長型。市場馬は持っていないので名前から決定的に決める。"""
    if parent.get('growth_type'):
        return parent['growth_type']
    import zlib
    rng = random.Random(zlib.crc32(parent['name'].encode('utf-8')))
    return random_growth_type(rng)


# ====================================================
# 血の重なり（インブリード）と相性（ニックス）
# ====================================================
# ⭕ 血統表4代の中で同じ馬が2回以上出たらインブリード。血量は世代ごとに 1/2^n
#    （父母50%・祖父母25%・3代12.5%・4代6.25%）を足す。3×4＝18.75%が「奇跡の血量」。
#    ニックスは「父の系統×母父の系統」で決まる。系統は父から受け継ぐ名前で、
#    組み合わせの相性は名前のハッシュで決定的に決める（手で相性表を持つと、系統が
#    自家の馬名で増えていって破綻する）。同じ系統同士なら必ず同じ結果になる。
NICK_RATE = 12              # 系統の組み合わせのうちニックスになる割合[%]
NICK_BONUS = 0.10           # 受け継ぐ能力の上積み
INBREED_MIRACLE = 0.1875    # 奇跡の血量（3×4・4×3）
INBREED_MIRACLE_BONUS = 0.20
INBREED_BONUS = 0.10        # 12.5%以上（奇跡以外）
INBREED_MIN = 0.125         # これ未満は効かない（4×4で12.5%）
INBREED_TEMPER = 0.25       # これ以上は気性難（2×3・2×2）
BLOOD_BONUS_CAP = 0.30      # 上積みの合計の上限
TEMPER_TROUBLE_SCALE = 2.0  # 気性難の馬が不利を受ける確率の倍率


def line_of(parent):
    """系統。自家の馬は父の系統、市場馬は父の名前、初代馬は自分の名前が系統の祖。"""
    if parent.get('line'):
        return parent['line']
    ped = parent.get('pedigree') or {}
    sire = ped.get('sire')
    if isinstance(sire, dict) and sire.get('line'):
        return sire['line']
    if parent.get('sire'):                       # 市場馬（プールの父）
        return parent['sire']
    return parent['name']


def is_nick(sire_line, dam_line):
    import zlib
    return zlib.crc32(f"{sire_line}|{dam_line}".encode('utf-8')) % 100 < NICK_RATE


def _ancestors(node, depth, out):
    """血統表を歩いて {名前: [世代, ...]} を集める。父母が1代。"""
    if node is None or depth > PEDIGREE_DEPTH:
        return
    name = node.get('name')
    if name and not name.endswith('の母'):        # 市場馬の名無しの母は数えない
        out.setdefault(name, []).append(depth)
    _ancestors(node.get('sire'), depth + 1, out)
    _ancestors(node.get('dam'), depth + 1, out)


def inbreeding(pedigree):
    """血統表の中で2回以上出る馬を [(名前, [世代...], 血量)] で返す（血量の大きい順）。"""
    found = {}
    _ancestors((pedigree or {}).get('sire'), 1, found)
    _ancestors((pedigree or {}).get('dam'), 1, found)
    crosses = []
    for name, gens in found.items():
        if len(gens) >= 2:
            blood = sum(0.5 ** g for g in gens)
            crosses.append((name, sorted(gens), blood))
    return sorted(crosses, key=lambda c: -c[2])


def cross_label(gens):
    return '×'.join(str(g) for g in gens)


def blood_effects(sire, dam):
    """配合の血の効き目。予約前の表示と、誕生時の両方で使う。

    Returns:
        dict: nick(bool), inbreed([(name, gens, blood)]), bonus(倍率の上積み), temper(bool), tags([表示用])
    """
    ped = {'sire': pedigree_of(sire), 'dam': pedigree_of(dam)}
    crosses = inbreeding(ped)
    nick = is_nick(line_of(sire), line_of(dam))
    bonus, temper, tags = 0.0, False, []
    if nick:
        bonus += NICK_BONUS
        tags.append('◎ニックス')
    if crosses:
        name, gens, blood = crosses[0]
        if abs(blood - INBREED_MIRACLE) < 1e-9:
            bonus += INBREED_MIRACLE_BONUS
            tags.append(f"★{name} {cross_label(gens)}（奇跡の血量）")
        elif blood >= INBREED_TEMPER:
            bonus += INBREED_BONUS
            temper = True
            tags.append(f"⚠{name} {cross_label(gens)}（濃すぎ・気性難）")
        elif blood >= INBREED_MIN:
            bonus += INBREED_BONUS
            tags.append(f"★{name} {cross_label(gens)}")
    return {'nick': nick, 'inbreed': crosses, 'bonus': min(BLOOD_BONUS_CAP, bonus),
            'temper': temper, 'tags': tags}


def stud_fee(cls):
    """市場の馬の種付け料（万円）。そのクラスの1着賞金に連動させます。"""
    return int(race_calendar.CLASS_INFO.get(cls, race_calendar.CLASS_INFO['1勝'])['prize'] * STUD_FEE_RATIO)


def _market_seed(horse):
    import zlib
    return zlib.crc32((horse['id'] + '|market').encode('utf-8'))


def market(data, pool=None):
    """現役馬と異性の市場の馬を、下級・中級・上級から2頭ずつ出します。

    ⭕ 現役馬のidをシードにするので、同じ世代のあいだ市場は変わらない。
       見るたびに入れ替わると比較できない。
    """
    horse = data['current']
    want = '牝' if horse['sex'] == '牡' else '牡'
    try:
        horses = (pool or rivals.load_pool())['horses']
    except (IOError, KeyError):
        return []
    rng = random.Random(_market_seed(horse))
    picked = []
    for tier in MARKET_TIERS:
        pool_tier = sorted((h for h in horses if h['sex'] == want and h['class'] in tier),
                           key=lambda h: h['name'])
        picked.extend(rng.sample(pool_tier, min(MARKET_SIZE_PER_TIER, len(pool_tier))))
    out = []
    for i, h in enumerate(picked):
        out.append({
            'key': f'market:{i}', 'source': 'market',
            'name': h['name'], 'sex': h['sex'], 'class': h['class'],
            'params': dict(h['params']), 'aptitude': dict(h['aptitude']),
            'sire': h.get('sire'), 'bms': h.get('bms'),
            'growth_type': growth_type_of(h),
            'fee': stud_fee(h['class']),
        })
    return out


def breeding_candidates(data, pool=None):
    """配合の相手の一覧。自分の引退馬（無料）と市場の馬（有料）。"""
    horse = data['current']
    want = '牝' if horse['sex'] == '牡' else '牡'
    own = [dict(s, key=f"own:{s['id']}", source='own', fee=0)
           for s in data['stallions'] if s['sex'] == want]
    cands = own + market(data, pool)
    for c in cands:                               # 予約前に血の効き目を見せる（狙って選べる）
        c['blood_tags'] = blood_effects(horse, c)['tags']
    return cands


def breeding_status(horse):
    """配合を予約できるか。(bool, 理由) を返します。"""
    used = slots_used(horse)
    if horse.get('breeding_plan'):
        return False, '予約済み'
    if used < BREEDING_OPEN_STARTS:
        return False, f"あと{BREEDING_OPEN_STARTS - used}戦で予約できます"
    return True, ''


def reserve_breeding(key, foal_name=None, data=None, save=True, pool=None):
    """配合を予約し、種付け料を資金から引きます。

    Raises:
        ValueError: 予約できない状態・相手が見つからない・資金不足
    """
    data = data if data is not None else load_stable()
    horse = data['current']
    ok, reason = breeding_status(horse)
    if not ok:
        raise ValueError(reason)
    partner = next((c for c in breeding_candidates(data, pool) if c['key'] == key), None)
    if partner is None:
        raise ValueError('その相手は選べません')
    if partner['fee'] > data.get('funds', 0):
        raise ValueError(f"資金が足りません（{partner['fee']:,}万円 ／ 手元 {data.get('funds', 0):,}万円）")

    data['funds'] = data.get('funds', 0) - partner['fee']
    horse['breeding_plan'] = {
        'partner': partner, 'fee': partner['fee'],
        'foal_name': (foal_name or '').strip() or None,
    }
    if save:
        save_stable(data)
    return horse['breeding_plan']


def cancel_breeding(data=None, save=True):
    """配合の予約を取り消し、種付け料を戻します。"""
    data = data if data is not None else load_stable()
    horse = data['current']
    plan = horse.get('breeding_plan')
    if plan:
        data['funds'] = data.get('funds', 0) + plan.get('fee', 0)
        horse['breeding_plan'] = None
        if save:
            save_stable(data)
    return plan



# ====================================================
# 🐴 セリ（仔馬を買って厩舎を増やす）
# ====================================================
# ⭕ 配合だけでは頭数が増えない（引退1頭に仔1頭）。資金の出口にもなる。
#    週ごとに6頭。両親は市場の馬から組み、血統と成長型を見て選ぶ。
def _auction_seed(data, today):
    import zlib
    return zlib.crc32(f"{main_horse(data)['id']}|auction|{week_key(today)}".encode('utf-8'))


def auction(data, today=None, pool=None):
    """今週のセリに出ている仔馬の一覧。"""
    today = today or datetime.now(JST).date()
    try:
        horses = (pool or rivals.load_pool())['horses']
    except (IOError, KeyError):
        return []
    rng = random.Random(_auction_seed(data, today))
    sires = [h for h in horses if h['sex'] == '牡']
    dams = [h for h in horses if h['sex'] == '牝']
    if not sires or not dams:
        return []
    foals = []
    for i in range(AUCTION_SIZE):
        sire, dam = rng.choice(sires), rng.choice(dams)
        foal = breed(sire, dam, today=today, rng=rng)
        foal['generation'] = 1
        price = int((stud_fee(sire['class']) + stud_fee(dam['class'])) / 2 * AUCTION_PRICE_RATIO)
        foals.append({'key': f'auction:{i}', 'foal': foal, 'price': price,
                      'sire': sire['name'], 'dam': dam['name'],
                      'sire_class': sire['class'], 'dam_class': dam['class']})
    return foals


def buy_foal(key, name=None, data=None, today=None, save=True, pool=None):
    """セリで仔馬を買い、厩舎に加えます（併せ馬として）。

    Raises:
        ValueError: 満杯・見つからない・資金不足
    """
    data = data if data is not None else load_stable()
    today = today or datetime.now(JST).date()
    if len(data['horses']) >= MAX_HORSES:
        raise ValueError(f"厩舎は{MAX_HORSES}頭までです。")
    lot = next((f for f in auction(data, today, pool) if f['key'] == key), None)
    if lot is None:
        raise ValueError('その仔馬はもうセリにいません。')
    if lot['price'] > data.get('funds', 0):
        raise ValueError(f"資金が足りません（{lot['price']:,}万円 ／ 手元 {data.get('funds', 0):,}万円）")
    foal = lot['foal']
    if name and name.strip():
        foal['name'] = name.strip()
    data['funds'] -= lot['price']
    data['horses'].append(foal)
    data['auction_bought'] = data.get('auction_bought', []) + [key + '|' + week_key(today)]
    _bind(data)
    if save:
        save_stable(data)
    return foal, lot['price']


def format_auction(data, today=None, pool=None):
    today = today or datetime.now(JST).date()
    lots = auction(data, today, pool)
    head = (f"🐴 **今週のセリ** ／ 厩舎資金 {data.get('funds', 0):,}万円"
            f" ／ 厩舎 {len(data['horses'])}/{MAX_HORSES}頭")
    if not lots:
        return head + "\n出品がありません。"
    lines = [head, '']
    for i, lot in enumerate(lots, start=1):
        f = lot['foal']
        lines.append(f"{i}. **{f['name']}**（{f['sex']}・{f['growth_type']}） 父 {lot['sire']}（{lot['sire_class']}）"
                     f" × 母 {lot['dam']}（{lot['dam_class']}） ／ {format_aptitude(f['aptitude'])}"
                     + (f" ／ {' '.join(f['blood']['tags'])}" if f.get('blood', {}).get('tags') else '')
                     + f" ／ {lot['price']:,}万円")
    return '\n'.join(lines)


# ====================================================
# 表示
# ====================================================
def format_horse(data=None, today=None):
    """現役馬のステータスを Discord 表示用に整形します。"""
    data = data if data is not None else load_stable()
    horse = data['current']
    params = params_of(horse)
    rec = horse['record']
    cond = condition_of(data, today, horse)

    role = '主戦' if is_main(data, horse) else '併せ馬'
    lines = [f"🐎 **第{horse.get('generation', 1)}世代 {horse['name']}**（{horse['sex']}・{horse.get('growth_type', '普通')}・{role}）",
             f"クラス: **{horse['class']}** ／ 調子: {CONDITION_LABELS.get(cond, '平常')}"
             f" ／ 脚質: {horse.get('style', '差し')}"]
    focus = focus_param(data, today)
    if focus:
        lines.append(f"🎯 今週の重点: {PARAM_NAMES[focus]}")

    for key in PARAMS:
        value = params[key]
        bar = '█' * int(value / 100) + '░' * (10 - int(value / 100))
        lines.append(f"{PARAM_NAMES[key]:>5s} {bar} {value:4d}")

    apt = horse['aptitude']
    lines.append(f"適性: 芝{apt.get('turf', 'B')} ダ{apt.get('dirt', 'B')} ／ "
                 + ' '.join(f"{BAND_NAMES[b]}{apt.get(b, 'B')}" for b in BANDS))
    lines.append(f"成績: {rec['starts']}戦{rec['win']}勝"
                 f"（2着{rec['place'] - rec['win']} 3着{rec['show'] - rec['place']}）"
                 f" 獲得賞金 {rec['prize']:,}万円")
    lines.append(f"残り{slots_left(horse)}戦で引退"
                 f" ／ 累計 {total_minutes(horse['growth']) / 60:.1f}時間"
                 f" ／ 厩舎資金 {data.get('funds', 0):,}万円")

    ped = horse.get('pedigree') or {}
    if ped.get('sire') or ped.get('dam'):
        lines.append(f"血統: 父 {_ped_name(ped.get('sire'))} ／ 母 {_ped_name(ped.get('dam'))}")

    if horse.get('entry'):
        e = horse['entry']
        lines.append(f"📋 出走登録済み: {e['date']} {e['name']}"
                     f"（{e['course']}{e['surface']}{e['distance']}m）")
    plan = horse.get('breeding_plan')
    if plan:
        p = plan['partner']
        lines.append(f"🧬 配合予約: {p['name']}（{p['class']}）"
                     + (f" 仔の名前 {plan['foal_name']}" if plan.get('foal_name') else ''))
    others = [h for h in data['horses'] if h is not horse]
    if others:
        lines.append('— 他の馬 —')
        for h in others:
            mark = '主戦' if is_main(data, h) else '併せ馬'
            lines.append(f"　{h['name']}（{h['class']}・{mark}）{h['record']['starts']}戦{h['record']['win']}勝"
                         + (f" 📋{h['entry']['name']}" if h.get('entry') else ''))
    return '\n'.join(lines)


def _ped_name(node):
    return node['name'] if node else '－'


def format_pedigree(horse):
    """3代血統表を整形します。"""
    ped = horse.get('pedigree') or {}
    lines = [f"🧬 **{horse['name']} の血統**（{line_of(horse)}系）"]
    for side, label in (('sire', '父'), ('dam', '母')):
        node = ped.get(side)
        lines.append(f"{label}: {_ped_name(node)}")
        if node:
            lines.append(f"　├ {label}父: {_ped_name(node.get('sire'))}")
            lines.append(f"　└ {label}母: {_ped_name(node.get('dam'))}")
    blood = horse.get('blood') or {}
    if blood.get('tags'):
        lines.append('　'.join(blood['tags']))
    crosses = inbreeding(ped)
    if crosses and not blood.get('tags'):
        lines.append('インブリード: ' + '、'.join(f"{n} {cross_label(g)}" for n, g, _ in crosses[:3]))
    return '\n'.join(lines)


def format_aptitude(apt):
    return (f"芝{apt.get('turf', 'B')} ダ{apt.get('dirt', 'B')} "
            + ' '.join(f"{BAND_NAMES[b]}{apt.get(b, 'B')}" for b in BANDS))


def format_candidate(c):
    """配合の相手1頭を1行にします。"""
    avg = int(sum(c['params'].get(k, BASE_ABILITY) for k in PARAMS) / len(PARAMS))
    fee = '無料' if c['fee'] == 0 else f"{c['fee']:,}万円"
    origin = '自家' if c['source'] == 'own' else '市場'
    return (f"[{origin}] **{c['name']}**（{c['sex']}・{c['class']}・{growth_type_of(c)}）能力平均 {avg}"
            f" ／ {format_aptitude(c['aptitude'])} ／ {fee}"
            + (f" ／ {' '.join(c['blood_tags'])}" if c.get('blood_tags') else ''))


def format_candidates(data, pool=None):
    """配合の相手一覧を整形します。"""
    horse = data['current']
    ok, reason = breeding_status(horse)
    head = (f"🧬 **{horse['name']}（{horse['sex']}）の配合相手** ／ "
            f"厩舎資金 {data.get('funds', 0):,}万円")
    if not ok:
        return f"{head}\n{reason}"
    cands = breeding_candidates(data, pool)
    if not cands:
        return f"{head}\n相手がいません。"
    lines = [head, f"現在の適性: {format_aptitude(horse['aptitude'])}", '']
    lines += [f"{i}. {format_candidate(c)}" for i, c in enumerate(cands, start=1)]
    return '\n'.join(lines)


def format_race_day_notice(data=None, today=None):
    """開催日の朝に出す告知。開催日でなければ None を返します。

    ⭕ レースは20:00に自動で走るが、出走登録が無いと何も言われずに開催日が過ぎる。
       朝のうちに気づけるよう、馬ごとに登録の有無で文言を変えて出す。
    """
    today = today or datetime.now(JST).date()
    if not race_calendar.is_race_day(today):
        return None

    data = data if data is not None else load_stable()
    lines = [f"🏁 **今日は開催日（{today.isoformat()}）**"]

    # ⭕ 海外遠征は月1回なので、当日と1週間前に知らせる（厩舎に1回だけ）
    if race_calendar.is_overseas_day(today):
        dest = race_calendar.overseas_destination(today)
        lines.append(f"🌏 今日は海外遠征日（{dest['venue']}）。G1 {race_calendar.OVERSEAS_G1_WINS}勝以上の馬が出られます。"
                     f"出走枠を2つ使い、次の開催日は休みになります。")
    elif race_calendar.is_overseas_day(today + timedelta(days=7)) and any(overseas_eligible(h) for h in data['horses']):
        dest = race_calendar.overseas_destination(today + timedelta(days=7))
        lines.append(f"🌏 来週の土曜は海外遠征日（{dest['venue']}）。遠征費 {dest['travel']:,}万円。")

    missing = []
    for horse in sorted(data['horses'], key=lambda h: 0 if is_main(data, h) else 1):
        cond = condition_of(data, today, horse)
        role = '主戦' if is_main(data, horse) else '併せ馬'
        head = (f"🐎 **{horse['name']}**（{horse['class']}・{role}） 調子: {CONDITION_LABELS.get(cond, '平常')}"
                f" ／ 脚質: {horse.get('style', '差し')}")
        ok, _ = breeding_status(horse)
        if ok:
            head += f"\n　🧬 配合を予約できます（残り{slots_left(horse)}戦）"
        resting = rest_reason(horse, today)
        if resting:
            lines.append(head + f"\n　✈️ {resting}")
            continue
        entry = horse.get('entry')
        if entry:
            if entry.get('date') != today.isoformat():
                # ⭕ run_entry() は登録の日付を見ないので、前回走り損なった登録は今夜そのまま走る
                lines.append(head + f"\n　📋 登録は **{entry['date']} {entry['name']}** のままです。"
                             f"今夜20:00にはこのレースが走ります。今日の番組から選び直すなら取り直してください。")
            else:
                grade = f" [{entry['grade']}]" if entry.get('grade') else ''
                lines.append(head + f"\n　📋 **{entry['name']}**{grade} "
                             f"{entry['course']}{entry['surface']}{entry['distance']}m {entry['cond']}"
                             f" ／ 1着 {entry['prize']:,}万円 → **20:00に発走**")
            continue
        lines.append(head + "\n　⚠️ **出走登録がありません。**")
        missing.append(horse)

    if missing:
        lines.append('')
        lines.append("20:00までに登録しないと今日は走りません。厩舎メニューの「🏇 出走登録」か `/entry` から。")
        if len(data['horses']) == 1:
            day, races = available_races(data=data, on=today)
            if races:
                lines.append('')
                lines.append(format_races(day, races))
    else:
        lines.append("それまでに記録した分は調教に間に合います。")
    return '\n'.join(lines)


def get_weekly_summary(data=None, today=None, save=True):
    """週間サマリー。主戦の調教量の差分と、全馬の今週のレースを出します。"""
    data = data if data is not None else load_stable()
    today = today or datetime.now(JST).date()
    main = main_horse(data)
    snap = data.get('weekly_snapshot') or {}

    # ⭕ 調教量は主戦で数える（記録は全部主戦に入る）。主戦が替わった週は、その馬が
    #    生まれてから（配合で受け継いだ分を除く）を今週分とみなす。
    trained = total_minutes(main['growth']) - main.get('birth_minutes', 0)
    if snap.get('horse_id') == main['id']:
        week_minutes = trained - snap.get('minutes', 0)
    else:
        prev = next((h for h in data['retired'] if h['id'] == snap.get('horse_id')), None)
        carry = (total_minutes(prev['growth']) - prev.get('birth_minutes', 0) - snap.get('minutes', 0)) if prev else 0
        week_minutes = max(0, carry) + trained
    week_minutes = max(0.0, week_minutes)

    # 今週のレースは日付で拾う（全馬＋今週引退した馬）
    since = (today - timedelta(days=7)).isoformat()
    races = []
    for h in data['horses'] + data['retired']:
        for r in h.get('history', []):
            if r['date'] >= since:
                races.append(dict(r, horse=h['name']))
    races.sort(key=lambda r: r['date'])

    msg = "📅 **【週間サマリー】**\n"
    msg += f"今週の調教: {week_minutes / 60:.1f}時間\n"
    if races:
        wins = sum(1 for r in races if r['finish'] == 1)
        msg += f"今週の出走: {len(races)}戦{wins}勝\n"
        for r in races:
            who = f"{r['horse']} " if len(data['horses']) > 1 or data['retired'] else ''
            msg += (f"　{r['date'][5:]} {who}{r['race']} {r['course']}{r['surface']}{r['distance']}m"
                    f" → **{r['finish']}着**/{r['field']}頭\n")
    retired_this_week = [h for h in data['retired'] if h.get('retired_on', '') >= since]
    for h in retired_this_week:
        msg += f"🎓 {h['name']} が引退しました。\n"
    for h in sorted(data['horses'], key=lambda x: 0 if is_main(data, x) else 1):
        role = '主戦' if is_main(data, h) else '併せ馬'
        msg += (f"🐎 {h['name']}（{h['class']}・{role}） 通算 {h['record']['starts']}戦{h['record']['win']}勝"
                f" ／ 残り{slots_left(h)}戦\n")

    prev_week = snap.get('last_week_minutes')
    if prev_week:
        diff = int((week_minutes - prev_week) / prev_week * 100)
        if diff > 0:
            msg += f"📈 先週より {diff}% 多く積めました。\n"
        elif diff < 0:
            msg += f"📉 先週より {abs(diff)}% 少なめでした。\n"

    data['weekly_snapshot'] = {
        'horse_id': main['id'], 'minutes': trained,
        'last_week_minutes': week_minutes, 'date': today.isoformat(),
    }
    if save:
        save_stable(data)
    return msg


def format_races(day, races):
    """出走できるレースの一覧を整形します。"""
    if not races:
        return f"{day.isoformat()} に出走できるレースがありません。"
    lines = [f"📅 **{day.isoformat()} の出走可能レース**"]
    for i, r in enumerate(races, start=1):
        grade = f" [{r['grade']}]" if r.get('grade') else ''
        mark = '🌏 ' if r.get('overseas') else ''
        lines.append(f"{i}. {mark}**{r['name']}**{grade} "
                     f"{r['course']}{r['surface']}{r['distance']}m {r['cond']} "
                     f"／ 1着 {r['prize']:,}万円{format_travel(r)}")
    return '\n'.join(lines)


def format_travel(race):
    travel = race.get('travel', 0)
    return f" ／ 遠征費 {travel:,}万円" if travel else ' ／ 地元'


RESULT_ROWS = 5     # 着順表に載せる上位の頭数


def format_result(entry_result, rows=RESULT_ROWS, spoiler=False):
    """レース結果を整形します。

    ⭕ メッセージ単体で何が起きたか分かるようにする。再生用HTMLは添付するが、
       スマホのDiscordでは添付を開くのが面倒なうえ、開かないと着順が分からない
       のでは結果を伝えたことにならない。

    Args:
        spoiler (bool): 結果の部分を Discord のネタバレ（||…||）で伏せるか。
            ⭕ 本文に着順を出すと、メッセージを開いた瞬間に結果が見えてしまう。
               再生を先に楽しみたいので、レース名だけ見せて中身は伏せる。
               CLIから呼ぶときは伏せない（ターミナルでは `||` がただの文字になる）。
    """
    head, body = format_result_parts(entry_result, rows)
    if spoiler:
        return head + '\n' + f"||{body}||"
    return head + '\n' + body


def format_result_parts(entry_result, rows=RESULT_ROWS):
    """レース結果を「見せる部分」と「伏せてよい部分」に分けて返します。

    Returns:
        tuple: (head: レース名など結果を含まない見出し, body: 着順とイベント)
    """
    race, mine = entry_result['race'], entry_result['finish']
    result = entry_result['result']
    horses = result['horses']
    me = next(h for h in horses if h['is_player'])

    grade = f" [{race['grade']}]" if race.get('grade') else ''
    head = (f"🏁 **{race['name']}**{grade} "
            f"{race['course']}{race['surface']}{race['distance']}m "
            f"{race['cond']} {len(horses)}頭")

    verdict = '🥇 勝ちました！' if mine == 1 else ('🥈 惜しい2着' if mine == 2
              else ('🥉 3着' if mine == 3 else f"{mine}着"))
    lines = [f"{verdict} ／ タイム {_mmss(me['time'])} ／ 上がり3F {me['last3f']:.1f}"
             f" ／ 通過 {'-'.join(str(p) for p in me['passing'])} ／ {me['style']}"]

    # ⭕ 自分の馬が上位に入らなかったときは、上位に加えて自分の行も必ず出す。
    shown = horses[:rows]
    if me not in shown:
        shown = shown + [me]

    lines.append('```')
    lines.append('着 馬番 馬名                 タイム   着差')
    for h in shown:
        mark = '★' if h['is_player'] else ' '
        margin = '  --  ' if h['finish'] == 1 else f"{h['margin']:+5.1f} "
        lines.append(f"{h['finish']:2d} {h['no']:3d} {mark}{_pad(h['name'], 16)}"
                     f" {_mmss(h['time'])} {margin}")
    lines.append('```')

    if entry_result['events']:
        lines.extend(entry_result['events'])
    return head, '\n'.join(lines)


def _pad(text, width):
    """全角を2桁と数えて右を詰めます（Discordのコードブロックは等幅）。"""
    return engine.pad_display(text, width)


def _mmss(sec):
    return engine.format_time(sec).strip()
