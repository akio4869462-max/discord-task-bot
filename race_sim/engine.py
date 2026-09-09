"""レースシミュレーションのエンジン本体。

Discord にもファイルI/Oにも依存しない純ロジック。seed を与えれば毎回同じ結果を返す。
標準ライブラリだけで動く（Botの実行環境に pandas/duckdb は入っていない）。

## モデルの考え方

各馬の走破タイムを直接組み立て、そこから区間ラップと通過順を逆算する。

    レース基準タイム = コース基準 + クラス補正 + 馬場補正 + レース単位のブレ
    各馬のタイム     = レース基準タイム - 実力差(秒) + 個体のブレ

⭕ 速度と消耗を1歩ずつ積み上げる物理シミュレーションも検討したが、その形だと
   「走破タイムの分布」「着差の分布」「人気別の勝率」を実測に合わせ込むのが
   非常に難しくなる（パラメータが結果に効く経路が長いため）。タイムを先に決めて
   区間へ配分する形なら、較正目標を直接狙って調整できる。区間ラップは脚質ごとの
   配分テンプレートから作るので、通過順やレース展開は破綻しない。

較正の基準値は race_sim/data/course_baseline.json（実データ2018-2026年、26,052レース）。
"""

import json
import math
import os
import random
import unicodedata

# ====================================================
# ⚙️ 較正パラメータ
# ====================================================
BASELINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'course_baseline.json')

# 実力差1.0（能力zスコア1つ分）が1600mで何秒に相当するか
SEC_PER_Z_1600 = 1.05
# レース単位のブレ（ペース・馬場差など、その日その競走全体に効くもの）の標準偏差[秒]
RACE_NOISE_SD = 0.85
# 馬ごとのブレ（出来・不利・展開のアヤ）の標準偏差[秒]。1600m換算。
HORSE_NOISE_SD = 0.40
# 賢さが最大のとき、馬ごとのブレをどこまで小さくできるか
WIT_NOISE_REDUCTION = 0.30
# 瞬発力が終い3ハロンの配分をどれだけ動かすか（メンバー平均との差1.0あたり）
DASH_SPLIT_SHIFT = 0.012
# 走破タイムの短縮ぶんのうち、上がり3Fに現れる割合。速いレースほど小さくなる。
# ⭕ 実測のクラス別上がり差から求めた（tools/calibrate.py --last3f で確認できる）。
LAST3F_R0 = 0.55
LAST3F_R1 = 0.22
# 上がり3F全体の水準合わせ[秒]。区間テンプレートだけだと一律に速く出るため。
LAST3F_BIAS = 0.45
# 不利・出遅れの発生率と失う秒数
TROUBLE_RATE = 0.06
TROUBLE_LOSS = (0.3, 1.3)

JST_PARAMS = ('speed', 'stamina', 'power', 'guts', 'wit', 'dash')

# 距離区分ごとの能力の重み。合計1.0。
DISTANCE_WEIGHTS = {
    'sprint': {'speed': 0.44, 'stamina': 0.04, 'power': 0.18, 'guts': 0.06, 'wit': 0.06, 'dash': 0.22},
    'mile':   {'speed': 0.36, 'stamina': 0.14, 'power': 0.12, 'guts': 0.10, 'wit': 0.08, 'dash': 0.20},
    'middle': {'speed': 0.26, 'stamina': 0.28, 'power': 0.08, 'guts': 0.14, 'wit': 0.08, 'dash': 0.16},
    'long':   {'speed': 0.20, 'stamina': 0.38, 'power': 0.07, 'guts': 0.16, 'wit': 0.09, 'dash': 0.10},
}
# ダートは前に進める力がより効く。芝の重みにこの係数を掛けて正規化し直す。
DIRT_WEIGHT_SCALE = {'power': 2.0, 'dash': 0.75, 'speed': 0.95}

# 適性グレード → 実力への上乗せ（zスコア）
APTITUDE_BONUS = {'A': 0.18, 'B': 0.0, 'C': -0.20, 'D': -0.45, 'E': -0.80}
# 調子(-2〜+2) 1段階あたりのzスコア
CONDITION_STEP = 0.10

# 脚質。前半をどれだけ飛ばすか（1.0が平均的な配分）
STYLES = ('逃げ', '先行', '差し', '追込')
STYLE_PACE = {'逃げ': 1.06, '先行': 1.02, '差し': 0.97, '追込': 0.93}
# ペースが速い/遅いときに脚質が受ける恩恵（zスコア）。ハイペースなら差し・追込が有利。
STYLE_PACE_SENSITIVITY = {'逃げ': -0.55, '先行': -0.20, '差し': 0.25, '追込': 0.45}

CLASS_ORDER = ('未勝利', '1勝', '2勝', '3勝', 'OP', 'G3', 'G2', 'G1')

# クラスごとの出走馬の平均能力z と、同一クラス内でのばらつき。
# ⭕ tools/calibrate.py が「そのクラスの平均勝ちタイムが実測と一致するz」を
#    二分法で解いた結果。数字を手で書き換えず、較正をやり直して差し替えること。
CLASS_MEAN_Z = {
    '未勝利': -1.81, '1勝': -0.95, '2勝': -0.48, '3勝': -0.02,
    'OP': -0.02, 'G3': 0.14, 'G2': 0.38, 'G1': 0.88,
}
FIELD_Z_SD = 0.34


def _distance_band(distance):
    if distance <= 1400:
        return 'sprint'
    if distance <= 1800:
        return 'mile'
    if distance <= 2400:
        return 'middle'
    return 'long'


def _aptitude_key(distance):
    """適性辞書の引き方。距離区分と同じ区切りを使う。"""
    return _distance_band(distance)


# ====================================================
# 較正データの読み込み
# ====================================================
_baseline_cache = {}


def load_baseline(path=None):
    """較正データを読み込む。パスごとに1度だけ読んで使い回す。"""
    path = path or BASELINE_FILE
    if path not in _baseline_cache:
        with open(path, 'r', encoding='utf-8') as f:
            _baseline_cache[path] = json.load(f)
    return _baseline_cache[path]


def clear_baseline_cache():
    """テストで較正データを差し替えるときに呼ぶ。"""
    _baseline_cache.clear()


def base_time(race, baseline=None):
    """コースと馬場から、そのレースの基準タイム[秒]を求める。

    返すのは「1勝クラス相当の面々が走ったときの勝ちタイム」。

    ⭕ クラスの差はここには入れない。クラス補正（未勝利+0.96秒〜G1-2.01秒）と
       「上のクラスほど強い馬が集まる」ことを両方タイムに効かせると二重計上になる。
       クラスの差は出走馬の能力水準（CLASS_MEAN_Z）だけで表現する。実測のクラス差
       2.98秒（未勝利→G1）は能力zで約2.8ぶんに相当し、この設計と整合する。

    ⭕ 実データに無いコース（該当条件のレースが年に数回しかない距離など）でも
       レースを開催できるよう、同じ場所・同じ芝ダの近い距離から比例で補う。
    """
    baseline = baseline or load_baseline()
    base = baseline['base']
    key = f"{race['course']}|{race['surface']}|{race['distance']}"

    entry = base.get(key)
    t = entry['win_time'] if entry else _interpolate_base(base, race)

    cond_key = f"{race['surface']}|{race.get('cond', '良')}"
    t += baseline['cond_offset'].get(cond_key, {}).get('offset', 0.0)
    return t


def _interpolate_base(base, race):
    """同一コースの他距離から速度を借りて基準タイムを推定する。"""
    prefix = f"{race['course']}|{race['surface']}|"
    same = [(int(k.rsplit('|', 1)[1]), v['win_time']) for k, v in base.items() if k.startswith(prefix)]
    if not same:
        # 場所すら無ければ、同じ芝ダの全コースの平均速度で代用する
        same = [(int(k.rsplit('|', 1)[1]), v['win_time'])
                for k, v in base.items() if f"|{race['surface']}|" in k]
    if not same:
        raise ValueError(f"較正データにコースがありません: {race}")

    same.sort()
    d = race['distance']
    nearest = min(same, key=lambda x: abs(x[0] - d))
    # 最寄り距離の平均速度をそのまま延長する（長い距離ほど1mあたりは遅くなるので微補正）
    speed = nearest[0] / nearest[1]
    stretch = 1.0 + 0.00002 * (d - nearest[0])
    return d / speed * stretch


# ====================================================
# 能力 → 実力（秒）
# ====================================================
def ability_z(entry, race):
    """出走馬1頭の実力を、平均を0とするzスコアで返す。大きいほど強い。"""
    params = entry['params']
    band = _distance_band(race['distance'])
    weights = dict(DISTANCE_WEIGHTS[band])

    if race['surface'] == 'ダ':
        weights = {k: v * DIRT_WEIGHT_SCALE.get(k, 1.0) for k, v in weights.items()}
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

    raw = sum(weights[k] * params.get(k, 500) for k in weights)
    z = (raw - 500.0) / 200.0

    apt = entry.get('aptitude') or {}
    surface_key = 'turf' if race['surface'] == '芝' else 'dirt'
    z += APTITUDE_BONUS.get(apt.get(surface_key, 'B'), 0.0)
    z += APTITUDE_BONUS.get(apt.get(_aptitude_key(race['distance']), 'B'), 0.0)
    z += CONDITION_STEP * entry.get('condition', 0)
    return z


def race_pace(entries):
    """出走馬の脚質構成からペースを決める。正なら速い（ハイペース）。"""
    if not entries:
        return 0.0
    load = sum(STYLE_PACE.get(e.get('style', '先行'), 1.0) for e in entries) / len(entries)
    front = sum(1 for e in entries if e.get('style') == '逃げ')
    # 逃げ馬が複数いると競り合ってペースが上がる
    return (load - 1.0) * 6.0 + max(0, front - 1) * 0.35


# ====================================================
# 区間ラップの生成
# ====================================================
def _section_template(style, n_sections, pace):
    """脚質ごとの「どの区間にどれだけ時間を使うか」の重み配分を作る。

    重みが小さい区間ほど速く走る。合計が n_sections になるよう正規化して返す。
    """
    weights = []
    for i in range(n_sections):
        pos = i / max(1, n_sections - 1)      # 0.0=スタート直後, 1.0=ゴール前
        if style == '逃げ':
            w = 0.955 + 0.13 * pos
        elif style == '先行':
            w = 0.970 + 0.075 * pos
        elif style == '差し':
            w = 1.030 - 0.075 * pos
        else:  # 追込
            w = 1.055 - 0.130 * pos
        # スタート直後の1ハロンは加速に使うぶん必ず遅い
        if i == 0:
            w += 0.085
        # ペースが速いレースでは前半がさらに速くなる
        w -= 0.012 * pace * (1.0 - pos)
        weights.append(w)

    total = sum(weights)
    return [w * n_sections / total for w in weights]


def _splits_for(total_time, style, distance, pace, dash_z, level_dev=0.0):
    """1頭ぶんの200m区間ラップを作る。合計は必ず total_time に一致する。

    Args:
        level_dev (float): 1勝クラスの基準タイムより何秒速いか。速いレースほど
            短縮ぶんが前半に回る性質（下の LAST3F_R を参照）を再現するために使う。
    """
    n_sections = max(1, int(round(distance / 200.0)))
    tmpl = _section_template(style, n_sections, pace)

    # 瞬発力は終いの3ハロンを速くし、そのぶん道中で帳尻を合わせる
    if n_sections >= 4:
        shift = DASH_SPLIT_SHIFT * dash_z
        for i in range(n_sections):
            if i >= n_sections - 3:
                tmpl[i] -= shift
            else:
                tmpl[i] += shift * 3.0 / (n_sections - 3)

    unit = total_time / n_sections
    splits = [round(w * unit, 2) for w in tmpl]

    # ⭕ 実データでは、上のクラスほど上がり3Fが速い……という単純な話にならない。
    #    1勝クラスとの上がりの差は 3勝 -0.48秒、G3 -0.24秒、G1 -0.24秒で、走破タイムの
    #    短縮幅（G1は-2.01秒）ほどには速くならない。速いレースほどペースが上がり、
    #    短縮ぶんが前半に回って終いは相対的にかかるためである。区間へ一律比例で
    #    配分するとこの性質が消え、G1の上がりが実測より1秒以上速くなった。
    if n_sections >= 5:
        share_proportional = 3.0 / n_sections
        share_actual = max(0.05, min(0.9, LAST3F_R0 - LAST3F_R1 * level_dev))
        extra = (share_proportional - share_actual) * level_dev + LAST3F_BIAS
        for i in range(n_sections):
            if i >= n_sections - 3:
                splits[i] = round(splits[i] + extra / 3.0, 2)
            else:
                splits[i] = round(splits[i] - extra / (n_sections - 3), 2)

    # 丸め誤差を最終区間で吸収し、合計を total_time に揃える
    splits[-1] = round(splits[-1] + (total_time - sum(splits)), 2)
    return splits


def _passing_positions(all_splits):
    """各コーナー相当地点の通過順を、区間ラップの累積から求める。"""
    n_horses = len(all_splits)
    n_sections = len(all_splits[0])
    cum = [[0.0] * n_sections for _ in range(n_horses)]
    for i, splits in enumerate(all_splits):
        acc = 0.0
        for j, s in enumerate(splits):
            acc += s
            cum[i][j] = acc

    # 4地点（おおむね1コーナー〜4コーナー）を等間隔に取る
    points = sorted({max(0, min(n_sections - 2, int(n_sections * f) - 1))
                     for f in (0.25, 0.5, 0.7, 0.88)})
    positions = []
    for i in range(n_horses):
        row = []
        for p in points:
            rank = 1 + sum(1 for k in range(n_horses) if cum[k][p] < cum[i][p])
            row.append(rank)
        positions.append(row)
    return positions


# ====================================================
# レース実行
# ====================================================
def simulate(race, entries, seed=None, baseline=None):
    """レースを1本走らせて結果を返す。

    Args:
        race (dict): course/surface/distance/cond/class/name を持つレース条件。
        entries (list): 出走馬のリスト。no/name/params/style/aptitude/condition。
        seed (int): 乱数シード。同じ seed なら必ず同じ結果になる。
        baseline (dict): 較正データ。省略時はファイルから読む。

    Returns:
        dict: docs/RACE_DESIGN.md §3.3 の形式のレース結果。
    """
    rng = random.Random(seed)
    baseline = baseline or load_baseline()

    t_base = base_time(race, baseline) + rng.gauss(0.0, RACE_NOISE_SD)
    pace = race_pace(entries)
    dist_scale = race['distance'] / 1600.0

    # ⭕ 賢さと瞬発力は「メンバー内でどれだけ抜けているか」で効かせる。絶対値で効かせると
    #    クラスが上がるだけで全馬のブレが消え、上位クラスほど堅くなる／上がり3Fが際限なく
    #    速くなるという歪みが出た（較正で発覚）。実力そのものは絶対値で見る必要があるが、
    #    この2つは相対値が正しい。
    mean_wit = sum(e['params'].get('wit', 500) for e in entries) / len(entries)
    mean_dash = sum(e['params'].get('dash', 500) for e in entries) / len(entries)

    results = []
    for e in entries:
        z = ability_z(e, race)
        z += STYLE_PACE_SENSITIVITY.get(e.get('style', '先行'), 0.0) * pace

        wit_z = (e['params'].get('wit', 500) - mean_wit) / 200.0
        sigma = HORSE_NOISE_SD * dist_scale * (1.0 - WIT_NOISE_REDUCTION * max(-1.0, min(1.0, wit_z)))

        # 賢い馬ほど不利を受けにくい
        trouble = None
        loss = 0.0
        if rng.random() < TROUBLE_RATE * (1.0 - 0.25 * max(-1.0, min(1.0, wit_z))):
            loss = rng.uniform(*TROUBLE_LOSS) * dist_scale
            trouble = '不利'

        total = t_base - SEC_PER_Z_1600 * dist_scale * z + rng.gauss(0.0, sigma) + loss
        dash_z = (e['params'].get('dash', 500) - mean_dash) / 200.0
        results.append({'entry': e, 'time': total, 'trouble': trouble, 'dash_z': dash_z})

    all_splits = [
        _splits_for(r['time'], r['entry'].get('style', '先行'), race['distance'], pace,
                    r['dash_z'], level_dev=t_base - r['time'])
        for r in results
    ]
    passings = _passing_positions(all_splits)

    order = sorted(range(len(results)), key=lambda i: results[i]['time'])
    finish_of = {idx: pos + 1 for pos, idx in enumerate(order)}
    winner_time = results[order[0]]['time']

    horses = []
    for i, r in enumerate(results):
        splits = all_splits[i]
        horses.append({
            'no': r['entry'].get('no', i + 1),
            'name': r['entry'].get('name', f"馬{i + 1}"),
            'style': r['entry'].get('style', '先行'),
            'is_player': bool(r['entry'].get('is_player')),
            'finish': finish_of[i],
            'time': round(r['time'], 2),
            'margin': round(r['time'] - winner_time, 2),
            'last3f': round(sum(splits[-3:]), 2) if len(splits) >= 3 else round(sum(splits), 2),
            'splits': splits,
            'passing': passings[i],
            'trouble': r['trouble'],
        })
    horses.sort(key=lambda h: h['finish'])

    return {
        'race': dict(race),
        'seed': seed,
        'pace': round(pace, 3),
        'base_time': round(t_base, 2),
        'horses': horses,
    }


def format_result(result):
    """結果を人が読める着順表に整形する（CLI・Discord投稿の両方から使う）。"""
    r = result['race']
    head = (f"{r.get('name', '')} {r['course']}{r['surface']}{r['distance']}m "
            f"{r.get('cond', '良')} [{r.get('class', '')}] {len(result['horses'])}頭")
    lines = [head, '着 馬番 馬名                   タイム  着差  上3F 通過        脚質']
    for h in result['horses']:
        mark = '★' if h['is_player'] else ' '
        margin = '  --  ' if h['finish'] == 1 else f"{h['margin']:+5.1f} "
        passing = '-'.join(str(p) for p in h['passing'])
        lines.append(f"{h['finish']:2d} {h['no']:3d} {mark}{_pad(h['name'], 20)} "
                     f"{_mmss(h['time'])} {margin}{h['last3f']:4.1f} {_pad(passing, 11)} {h['style']}")
    return '\n'.join(lines)


def _pad(text, width):
    """全角を2桁と数えて、等幅フォントで桁が揃うように右を詰める。

    ⭕ str.ljust は文字数で数えるため、馬名（全角）と数字が混ざると列が崩れる。
       CLIもDiscordのコードブロックも等幅前提なので、表示幅で揃える必要がある。
    """
    w = 0
    out = []
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F', 'A') else 1
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return ''.join(out) + ' ' * (width - w)


def _mmss(sec):
    """秒を m:ss.s 形式にする。

    ⭕ 先に丸めてから分と秒に分ける。順序が逆だと 119.96秒が「1:60.0」になる。
    """
    total = round(sec, 1)
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:04.1f}" if m else f"  {s:04.1f}"
