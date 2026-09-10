"""競走馬の育成ロジック。厩舎データの管理・成長・出走・世代交代を担う。

⭕ Discord には一切依存しない。文字列とプリミティブだけを返すので、ネットワーク無しで
   ユニットテストできる。この境界は既存の `*_logic.py` と同じ。

## 成長の考え方

活動の**累積分数を生データのまま持ち**、能力値は読み出すたびに導出する。

    能力 = 140 + 6.968 × (その能力に積んだ分)^0.70   （上限1000）

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
GROWTH_K = 6.968            # 50時間でG1級(680)に届くよう解いた係数
GROWTH_EXP = 0.70           # 逓減の効き。序盤ほど伸びやすい
ABILITY_CAP = 1000          # 「G1を大きく超える怪物」の水準

PARAMS = engine.JST_PARAMS
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

RETIRE_STARTS = 20          # 何戦で引退するか
# 次世代が受け継ぐ、親の積み上げの割合
INHERIT_RATE = 0.10

# 着順 → 賞金の取り分
PRIZE_SHARE = {1: 1.0, 2: 0.40, 3: 0.25, 4: 0.15, 5: 0.10}

APTITUDE_GRADES = ('A', 'B', 'C', 'D')
BANDS = ('sprint', 'mile', 'middle', 'long')
BAND_NAMES = {'sprint': '短距離', 'mile': 'マイル', 'middle': '中距離', 'long': '長距離'}

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
def ability_of(minutes):
    """その能力に積んだ分数から能力値を求めます。"""
    if minutes <= 0:
        return BASE_ABILITY
    return min(ABILITY_CAP, int(round(BASE_ABILITY + GROWTH_K * minutes ** GROWTH_EXP)))


def minutes_for(ability):
    """ある能力値に届くのに必要な分数（表示・テスト用の逆算）。"""
    if ability <= BASE_ABILITY:
        return 0.0
    return ((ability - BASE_ABILITY) / GROWTH_K) ** (1 / GROWTH_EXP)


def derive_params(growth):
    """成長の生データ（分）から6つの能力値を導出します。"""
    return {k: ability_of(growth.get(k, 0)) for k in PARAMS}


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


def new_horse(name=None, growth=None, pedigree=None, sex=None, today=None, rng=None):
    """新しい現役馬を1頭つくります。"""
    rng = rng or random.Random()
    today = today or datetime.now(JST).date()
    return {
        'id': str(uuid.uuid4()),
        'name': name or suggest_name(rng),
        'sex': sex or rng.choice(['牡', '牝']),
        'debut': today.isoformat(),
        'growth': growth or _new_growth(),
        'style': '差し',
        'aptitude': _random_aptitude(rng),
        'class': '未勝利',
        'record': {'starts': 0, 'win': 0, 'place': 0, 'show': 0, 'prize': 0},
        'pedigree': pedigree or {'sire': '－', 'dam': '－'},
        'history': [],
        'entry': None,
    }


def _default_stable(today=None):
    return {
        'generation': 1,
        'current': new_horse(today=today),
        'retired': [],
        'stallions': [],
        'last_active_date': None,
        'current_streak': 0,
    }


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
    horse = data.get('current')
    if horse:
        horse.setdefault('entry', None)
        horse.setdefault('history', [])
        horse.setdefault('record', {'starts': 0, 'win': 0, 'place': 0, 'show': 0, 'prize': 0})
        for k in PARAMS:
            horse.setdefault('growth', {}).setdefault(k, 0.0)
    return data


def save_stable(data):
    try:
        os.makedirs(os.path.dirname(STABLE_FILE), exist_ok=True)
        with open(STABLE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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


def condition_of(data, today=None):
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
    if streak >= 21:
        return 2
    if streak >= 7:
        return 1
    return 0


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
    horse = data['current']

    weights = ACTIVITY_PARAMS.get(category)
    if not weights or minutes <= 0:
        return {'gains': {}, 'streak': data.get('current_streak', 0),
                'condition': condition_of(data, today), 'capped': False, 'horse': horse}

    before = derive_params(horse['growth'])
    for param, share in weights.items():
        horse['growth'][param] = horse['growth'].get(param, 0) + minutes * share
    after = derive_params(horse['growth'])

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
                'horse': data['current'], 'days': 0}

    before = derive_params(data['current']['growth'])
    result = None
    for day in dates[:BACKFILL_MAX_DATES]:
        result = add_growth(category, minutes, today=day, data=data,
                            save=False, update_streak=False)
    after = derive_params(data['current']['growth'])

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
        'params': derive_params(horse['growth']),
        'aptitude': dict(horse['aptitude']),
        'style': horse.get('style', '差し'),
        'condition': condition_of(data, today) if data is not None else 0,
    }


def available_races(data=None, on=None):
    """次の開催日に出走できるレースを返します。"""
    data = data if data is not None else load_stable()
    horse = data['current']
    day = race_calendar.next_race_day(on or datetime.now(JST).date())
    return day, race_calendar.offers(horse['class'], day, aptitude=horse['aptitude'])


def enter_race(race, style=None, data=None, save=True):
    """出走を登録します。脚質はここで宣言します（意思であって確約ではない）。"""
    data = data if data is not None else load_stable()
    horse = data['current']
    if style:
        horse['style'] = style
    horse['entry'] = dict(race)
    if save:
        save_stable(data)
    return horse['entry']


def cancel_entry(data=None, save=True):
    data = data if data is not None else load_stable()
    data['current']['entry'] = None
    if save:
        save_stable(data)


def _race_seed(horse, race):
    """馬とレースから決まるシード。同じ組み合わせなら結果は必ず同じになる。"""
    import zlib
    return zlib.crc32((horse['id'] + '|' + race['id']).encode('utf-8'))


def run_entry(data=None, today=None, save=True):
    """登録したレースを実行し、結果を厩舎に反映します。

    Returns:
        dict/None: {'result': レース結果, 'finish': 着順, 'events': [文言], 'race': race}
            登録が無ければ None。
    """
    data = data if data is not None else load_stable()
    horse = data['current']
    race = horse.get('entry')
    if not race:
        return None

    today = today or datetime.now(JST).date()
    seed = _race_seed(horse, race)
    entries = rivals.build_field(race, seed=seed, player=player_entry(horse, data, today))
    result = engine.simulate(race, entries, seed=seed)

    mine = next(h for h in result['horses'] if h['is_player'])
    events = _apply_result(data, race, mine, today, len(result['horses']))
    horse['entry'] = None
    if save:
        save_stable(data)
    return {'result': result, 'finish': mine['finish'], 'events': events, 'race': race}


def _apply_result(data, race, mine, today, field_size):
    """着順を成績に反映し、昇級と引退を判定します。"""
    horse = data['current']
    rec = horse['record']
    rec['starts'] += 1
    if mine['finish'] == 1:
        rec['win'] += 1
    if mine['finish'] <= 2:
        rec['place'] += 1
    if mine['finish'] <= 3:
        rec['show'] += 1
    rec['prize'] += int(race.get('prize', 0) * PRIZE_SHARE.get(mine['finish'], 0))

    horse['history'].append({
        'date': today.isoformat(), 'race': race['name'],
        'course': race['course'], 'surface': race['surface'], 'distance': race['distance'],
        'cond': race.get('cond', '良'), 'class': race['class'],
        'finish': mine['finish'], 'field': field_size,
        'time': mine['time'], 'last3f': mine['last3f'], 'style': mine['style'],
    })

    events = []
    if mine['finish'] == 1:
        idx = engine.CLASS_ORDER.index(horse['class'])
        if idx < len(engine.CLASS_ORDER) - 1:
            horse['class'] = engine.CLASS_ORDER[idx + 1]
            events.append(f"🏆 勝利！ {horse['class']}クラスへ昇級しました。")
        else:
            events.append("🏆 G1制覇！")

    if rec['starts'] >= RETIRE_STARTS:
        events.append(retire(data, today))
    return events


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
    if horse.get('class') == 'G1' and rec.get('win', 0) >= 1:
        bonus += 0.30
    return bonus


def retire(data, today=None, save=False):
    """現役馬を引退させ、次世代を迎えます。"""
    today = today or datetime.now(JST).date()
    horse = data['current']
    horse['retired_on'] = today.isoformat()
    horse['final_params'] = derive_params(horse['growth'])

    data['retired'].append(horse)
    # ⭕ 配合を後から足せるよう、引退馬は能力・成績・適性を持った実体として残す。
    #    名前だけの飾りにするとデータ構造から作り直すことになる。
    data['stallions'].append({
        'name': horse['name'], 'sex': horse['sex'], 'class': horse['class'],
        'params': horse['final_params'], 'aptitude': dict(horse['aptitude']),
        'record': dict(horse['record']), 'stud_value': round(stud_value(horse), 3),
    })

    rng = random.Random(horse['id'])
    inherited = {k: horse['growth'].get(k, 0) * INHERIT_RATE * stud_value(horse)
                 for k in PARAMS}
    parent = horse['name']
    data['generation'] = data.get('generation', 1) + 1
    data['current'] = new_horse(
        growth=inherited,
        pedigree={'sire': parent if horse['sex'] == '牡' else '－',
                  'dam': parent if horse['sex'] == '牝' else '－'},
        today=today, rng=rng)
    if save:
        save_stable(data)
    return (f"🎓 {parent} が{RETIRE_STARTS}戦を走り切って引退しました。"
            f"第{data['generation']}世代 {data['current']['name']} がデビューします。")


# ====================================================
# 表示
# ====================================================
def format_horse(data=None, today=None):
    """現役馬のステータスを Discord 表示用に整形します。"""
    data = data if data is not None else load_stable()
    horse = data['current']
    params = derive_params(horse['growth'])
    rec = horse['record']
    cond = condition_of(data, today)

    lines = [f"🐎 **第{data.get('generation', 1)}世代 {horse['name']}**（{horse['sex']}）",
             f"クラス: **{horse['class']}** ／ 調子: {CONDITION_LABELS.get(cond, '平常')}"
             f" ／ 脚質: {horse.get('style', '差し')}"]

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
    lines.append(f"残り{max(0, RETIRE_STARTS - rec['starts'])}戦で引退"
                 f" ／ 累計 {total_minutes(horse['growth']) / 60:.1f}時間")

    if horse.get('entry'):
        e = horse['entry']
        lines.append(f"📋 出走登録済み: {e['date']} {e['name']}"
                     f"（{e['course']}{e['surface']}{e['distance']}m）")
    return '\n'.join(lines)


def format_race_day_notice(data=None, today=None):
    """開催日の朝に出す告知。開催日でなければ None を返します。

    ⭕ レースは20:00に自動で走るが、出走登録が無いと何も言われずに開催日が過ぎる。
       朝のうちに気づけるよう、登録の有無で文言を変えて出す。
    """
    today = today or datetime.now(JST).date()
    if not race_calendar.is_race_day(today):
        return None

    data = data if data is not None else load_stable()
    horse = data['current']
    cond = condition_of(data, today)
    entry = horse.get('entry')

    header = f"🏁 **今日は開催日（{today.isoformat()}）**"
    state = (f"🐎 {horse['name']}（{horse['class']}）"
             f" 調子: {CONDITION_LABELS.get(cond, '平常')}"
             f" ／ 脚質: {horse.get('style', '差し')}")

    if entry:
        # ⭕ run_entry() は登録の日付を見ないので、前回走り損なった登録は今夜そのまま走る。
        #    黙って古いレースを走らせると面食らうので、今日のものでなければそう言う。
        if entry.get('date') != today.isoformat():
            return '\n'.join([
                header, state,
                f"📋 登録は **{entry['date']} {entry['name']}** のままです。"
                f"今夜20:00にはこのレースが走ります。"
                f"今日の番組から選び直すなら、厩舎で登録を取り直してください。",
            ])
        grade = f" [{entry['grade']}]" if entry.get('grade') else ''
        return '\n'.join([
            header, state,
            f"📋 **{entry['name']}**{grade} "
            f"{entry['course']}{entry['surface']}{entry['distance']}m {entry['cond']}"
            f" ／ 1着 {entry['prize']:,}万円",
            "→ **20:00に発走**します。それまでに記録した分は調教に間に合います。",
        ])

    day, races = available_races(data=data, on=today)
    lines = [header, state,
             "⚠️ **出走登録がありません。** 20:00までに登録しないと今日は走りません。"]
    if races:
        lines.append('')
        lines.append(format_races(day, races))
    lines.append('')
    lines.append("厩舎メニューの「🏇 出走登録」か `/entry` から登録できます。")
    return '\n'.join(lines)


def get_weekly_summary(data=None, today=None, save=True):
    """週間サマリー。前回からの差分を出し、次回のためのスナップショットを更新します。"""
    data = data if data is not None else load_stable()
    today = today or datetime.now(JST).date()
    horse = data['current']
    snap = data.get('weekly_snapshot') or {}

    minutes = total_minutes(horse['growth'])
    rec = horse['record']
    week_minutes = minutes - snap.get('minutes', 0)
    week_starts = rec['starts'] - snap.get('starts', 0)
    week_wins = rec['win'] - snap.get('wins', 0)

    msg = "📅 **【週間サマリー】**\n"
    msg += f"今週の調教: {week_minutes / 60:.1f}時間\n"
    if week_starts > 0:
        msg += f"今週の出走: {week_starts}戦{week_wins}勝\n"
    msg += f"🐎 {horse['name']}（{horse['class']}） 通算 {rec['starts']}戦{rec['win']}勝"
    msg += f" ／ 残り{max(0, RETIRE_STARTS - rec['starts'])}戦\n"

    prev = snap.get('last_week_minutes')
    if prev:
        diff = int((week_minutes - prev) / prev * 100)
        if diff > 0:
            msg += f"📈 先週より {diff}% 多く積めました。\n"
        elif diff < 0:
            msg += f"📉 先週より {abs(diff)}% 少なめでした。\n"

    # ⭕ 世代交代をまたいでも差分が壊れないよう、スナップショットは撮り直す。
    data['weekly_snapshot'] = {
        'minutes': minutes, 'starts': rec['starts'], 'wins': rec['win'],
        'last_week_minutes': max(0, week_minutes), 'date': today.isoformat(),
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
        lines.append(f"{i}. **{r['name']}**{grade} "
                     f"{r['course']}{r['surface']}{r['distance']}m {r['cond']} "
                     f"／ 1着 {r['prize']:,}万円")
    return '\n'.join(lines)


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
