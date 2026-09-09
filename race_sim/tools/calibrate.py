"""レースエンジンを実データの基準値に合わせ込むための較正ハーネス。

docs/RACE_DESIGN.md §5 に挙げた4つの較正目標を測る。

  1. クラス×コースごとの平均勝ちタイムと標準偏差
  2. 上がり3Fの分布
  3. 1着-2着の着差分布
  4. 能力最上位の馬の勝率が「順当すぎない」こと（実測の1番人気 32.7% を目安にする）

⭕ 目標4について。実際の「1番人気」は市場の推定であって真の実力順ではないので、
   真の実力1位の勝率は本来もう少し高いはずである。しかしプレイヤーから見た体感は
   「自分の馬が最有力＝1番人気」であり、そこを実測の1番人気の勝率に合わせるのが
   ゲームとして自然なので、この目安を採用する。

このスクリプトは標準ライブラリだけで動く（実データそのものは使わず、
build_baseline.py が出力した course_baseline.json だけを見る）。

    PYTHONIOENCODING=utf-8 python race_sim/tools/calibrate.py
    PYTHONIOENCODING=utf-8 python race_sim/tools/calibrate.py --solve
"""

import argparse
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from race_sim import engine  # noqa: E402

# 較正に使う代表コース。芝・ダ、短距離〜長距離を散らす。
SAMPLE_COURSES = [
    ('東京', '芝', 1600), ('東京', '芝', 2400), ('中山', '芝', 1200), ('中山', '芝', 2000),
    ('阪神', '芝', 1800), ('京都', '芝', 3000), ('東京', 'ダ', 1400), ('中山', 'ダ', 1800),
    ('阪神', 'ダ', 1200), ('中京', 'ダ', 1800),
]
PARAM_JITTER = 0.35   # 同じ馬でも能力の内訳はばらつく


def style_shares(baseline, surface):
    """実データの脚質構成比を返す。"""
    items = [(k.split('|')[1], v['n']) for k, v in baseline['style'].items()
             if k.startswith(surface + '|')]
    total = sum(n for _, n in items)
    return [(s, n / total) for s, n in items]


def make_field(rng, size, mean_z, sd_z, shares):
    """指定した能力水準の出走馬を組む。"""
    entries = []
    for i in range(size):
        z = rng.gauss(mean_z, sd_z)
        params = {k: 500 + 200 * (z + rng.gauss(0, PARAM_JITTER)) for k in engine.JST_PARAMS}
        r = rng.random()
        acc = 0.0
        style = shares[-1][0]
        for s, p in shares:
            acc += p
            if r <= acc:
                style = s
                break
        entries.append({
            'no': i + 1, 'name': f"馬{i + 1:02d}", 'params': params,
            'style': style, 'aptitude': {}, 'condition': 0, 'true_z': z,
        })
    return entries


def run_races(cls, n_races, seed=0, courses=None, mean_z=None):
    """1クラスぶんのレースを回して統計を集める。"""
    baseline = engine.load_baseline()
    rng = random.Random(seed)
    courses = courses or SAMPLE_COURSES
    mean_z = engine.CLASS_MEAN_Z[cls] if mean_z is None else mean_z

    win_dev = []      # 実測基準タイムとの差[秒]
    margins = {2: [], 3: [], 4: [], 5: []}
    top_win = top_show = n_valid = 0
    last3f_dev = []

    for i in range(n_races):
        basho, surface, dist = courses[i % len(courses)]
        race = {'course': basho, 'surface': surface, 'distance': dist, 'cond': '良',
                'class': cls, 'name': '較正'}
        key = f"{basho}|{surface}|{dist}"
        ref = baseline['base'].get(key)
        if not ref:
            continue
        size = rng.choice([12, 13, 14, 15, 16, 16, 18])
        shares = style_shares(baseline, surface)
        entries = make_field(rng, size, mean_z, engine.FIELD_Z_SD, shares)

        result = engine.simulate(race, entries, seed=rng.randrange(10 ** 9), baseline=baseline)

        target = ref['win_time'] + baseline['class_offset'][cls]['offset']
        winner = result['horses'][0]
        win_dev.append(winner['time'] - target)
        l3f_target = ref['last3f'] + baseline.get('last3f_class_offset', {}).get(cls, {}).get('offset', 0.0)
        last3f_dev.append(winner['last3f'] - l3f_target)

        for pos in margins:
            if len(result['horses']) >= pos:
                margins[pos].append(result['horses'][pos - 1]['margin'])

        best_no = max(entries, key=lambda e: e['true_z'])['no']
        placing = {h['no']: h['finish'] for h in result['horses']}
        top_win += 1 if placing[best_no] == 1 else 0
        top_show += 1 if placing[best_no] <= 3 else 0
        n_valid += 1

    return {
        'n': n_valid,
        'win_dev_mean': statistics.fmean(win_dev),
        'win_dev_sd': statistics.stdev(win_dev),
        'last3f_dev': statistics.fmean(last3f_dev),
        'margin_mean': {p: statistics.fmean(v) for p, v in margins.items() if v},
        'margin_q50': {p: statistics.median(v) for p, v in margins.items() if v},
        'margin_q90': {p: sorted(v)[int(len(v) * 0.9)] for p, v in margins.items() if v},
        'top_win': top_win / n_valid,
        'top_show': top_show / n_valid,
    }


def solve_class_mean_z(cls, n_races=600, tol=0.02):
    """そのクラスの平均勝ちタイムが実測と一致する平均能力zを二分法で解く。"""
    lo, hi = -4.0, 6.0
    for _ in range(24):
        mid = (lo + hi) / 2
        dev = run_races(cls, n_races, seed=7, mean_z=mid)['win_dev_mean']
        if abs(dev) < tol:
            return round(mid, 3)
        # 能力が高いほどタイムは速くなる（devが小さくなる）
        if dev > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 3)


def report(n_races):
    baseline = engine.load_baseline()
    tgt = baseline['margin']
    print(f"較正データ: {baseline['meta']['years']} / {baseline['meta']['races']:,}レース")
    print(f"シミュレーション: 各クラス {n_races}レース\n")
    print("クラス  n     勝ち時計差(平均±SD)  上3F差  着差2着 [実測0.24]  中央値[0.20]  90%[0.60]  最上位勝率[0.33]  複勝率[0.64]")
    for cls in engine.CLASS_ORDER:
        s = run_races(cls, n_races, seed=11)
        print(f"{cls:5s} {s['n']:5d}   {s['win_dev_mean']:+6.2f} ± {s['win_dev_sd']:4.2f}秒   "
              f"{s['last3f_dev']:+5.2f}   {s['margin_mean'][2]:6.3f}        "
              f"{s['margin_q50'][2]:6.2f}      {s['margin_q90'][2]:5.2f}    "
              f"{s['top_win']:8.3f}       {s['top_show']:.3f}")
    print(f"\n実測の着差: 2着 平均{tgt['2']['mean']} 中央{tgt['2']['q50']} 90%{tgt['2']['q90']} / "
          f"3着 平均{tgt['3']['mean']} / 4着 平均{tgt['4']['mean']}")
    print(f"実測の勝ち時計SD: 1.06秒（加法モデルの残差RMSE）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--races', type=int, default=800)
    ap.add_argument('--solve', action='store_true', help='CLASS_MEAN_Z を解き直す')
    args = ap.parse_args()

    if args.solve:
        print("クラスごとの平均能力zを解いています...")
        solved = {cls: solve_class_mean_z(cls) for cls in engine.CLASS_ORDER}
        print("CLASS_MEAN_Z = {")
        for cls, z in solved.items():
            print(f"    '{cls}': {z:.2f},")
        print("}")
        return

    report(args.races)


if __name__ == '__main__':
    main()
