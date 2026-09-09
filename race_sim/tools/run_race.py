"""コマンドラインでレースを1本走らせて着順を表示する。

    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py
    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py --course 中山 --surface 芝 \
        --distance 2000 --class G1 --seed 123
    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py --my-horse 620,540,500,580,600,660

⭕ ライバル馬はここで仮に作っている。Phase 2 で実データから生成した rivals.json に
   差し替える（docs/RACE_DESIGN.md §9）。それまでの動作確認用。
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from race_sim import engine  # noqa: E402

# 仮の馬名。Phase 2 で実データの傾向から生成した名前に置き換える。
NAME_HEAD = ['サンライズ', 'メイショウ', 'ゴールド', 'キタノ', 'シルバー', 'ダイワ', 'トウカイ',
             'マイネル', 'ヒシ', 'ナリタ', 'エイシン', 'ロード', 'アグネス', 'タニノ',
             'ビワ', 'テイエム', 'コパノ', 'スマート']
NAME_TAIL = ['テイオー', 'ブライアン', 'シチー', 'キング', 'クイーン', 'ホープ', 'ロード',
             'フラッシュ', 'ダンサー', 'アロー', 'ウイナー', 'スター', 'ジャガー', 'ソウル',
             'リュウ', 'グロウ', 'ノヴァ', 'ミラージュ']


def make_rivals(rng, size, cls):
    """指定クラス相当のライバル馬を仮に組む。"""
    mean_z = engine.CLASS_MEAN_Z[cls]
    shares = [('逃げ', 0.07), ('先行', 0.30), ('差し', 0.38), ('追込', 0.25)]
    entries = []
    used = set()
    for i in range(size):
        while True:
            name = rng.choice(NAME_HEAD) + rng.choice(NAME_TAIL)
            if name not in used:
                used.add(name)
                break
        z = rng.gauss(mean_z, engine.FIELD_Z_SD)
        params = {k: round(500 + 200 * (z + rng.gauss(0, 0.35))) for k in engine.JST_PARAMS}
        r, acc, style = rng.random(), 0.0, '差し'
        for s, p in shares:
            acc += p
            if r <= acc:
                style = s
                break
        entries.append({'no': i + 1, 'name': name, 'params': params, 'style': style,
                        'aptitude': {}, 'condition': rng.choice([-1, 0, 0, 0, 1])})
    return entries


def parse_params(text):
    """--my-horse の "スピード,スタミナ,パワー,根性,賢さ,瞬発力" を辞書にする。"""
    values = [int(x) for x in text.split(',')]
    if len(values) != len(engine.JST_PARAMS):
        raise SystemExit(f"能力は{len(engine.JST_PARAMS)}個指定してください: {engine.JST_PARAMS}")
    return dict(zip(engine.JST_PARAMS, values))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--course', default='東京')
    ap.add_argument('--surface', default='芝', choices=['芝', 'ダ'])
    ap.add_argument('--distance', type=int, default=1600)
    ap.add_argument('--cond', default='良', choices=['良', '稍', '重', '不'])
    ap.add_argument('--class', dest='cls', default='1勝', choices=list(engine.CLASS_ORDER))
    ap.add_argument('--field', type=int, default=16)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--name', default='テストステークス')
    ap.add_argument('--my-horse', default=None,
                    help='自分の馬の能力をカンマ区切りで指定する（省略時はライバルのみ）')
    ap.add_argument('--my-style', default='差し', choices=list(engine.STYLES))
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(10 ** 9)
    rng = random.Random(seed)

    race = {'name': args.name, 'course': args.course, 'surface': args.surface,
            'distance': args.distance, 'cond': args.cond, 'class': args.cls}

    entries = make_rivals(rng, args.field, args.cls)
    if args.my_horse:
        entries[0] = {'no': 1, 'name': 'マイホース', 'params': parse_params(args.my_horse),
                      'style': args.my_style, 'aptitude': {}, 'condition': 0, 'is_player': True}

    result = engine.simulate(race, entries, seed=seed)
    print(engine.format_result(result))
    pace_label = 'ハイペース' if result['pace'] > 0.15 else ('スローペース' if result['pace'] < -0.15 else '平均ペース')
    print(f"\nseed={seed}  ペース={pace_label}({result['pace']:+.2f})  基準タイム={result['base_time']}秒")


if __name__ == '__main__':
    main()
