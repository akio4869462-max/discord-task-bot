"""コマンドラインでレースを1本走らせて着順を表示する。

    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py
    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py --course 中山 --surface 芝 \
        --distance 2000 --class G1 --seed 123
    PYTHONIOENCODING=utf-8 python race_sim/tools/run_race.py --my-horse 620,540,500,580,600,660

ライバル馬は race_sim/data/rivals.json（実データの分布から生成した架空馬）から、
レース条件に合う馬を選んで組む。
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from race_sim import engine, rivals  # noqa: E402


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
    ap.add_argument('--field', type=int, default=None,
                    help='頭数。省略するとそのクラスの実際の分布から引く')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--name', default='テストステークス')
    ap.add_argument('--my-horse', default=None,
                    help='自分の馬の能力をカンマ区切りで指定する（省略時はライバルのみ）')
    ap.add_argument('--my-style', default='差し', choices=list(engine.STYLES))
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(10 ** 9)

    race = {'name': args.name, 'course': args.course, 'surface': args.surface,
            'distance': args.distance, 'cond': args.cond, 'class': args.cls}

    if not rivals.is_supported(race):
        print(f"⚠️ この条件のレースは実際にはほぼ組まれません（{args.cls}の{args.surface}"
              f"{args.distance}m）。出走馬の質が揃わないため結果は参考程度です。\n")

    player = None
    if args.my_horse:
        player = {'name': 'マイホース', 'params': parse_params(args.my_horse),
                  'style': args.my_style, 'aptitude': {}, 'condition': 0}

    entries = rivals.build_field(race, size=args.field, seed=seed, player=player)
    result = engine.simulate(race, entries, seed=seed)
    print(engine.format_result(result))
    pace_label = 'ハイペース' if result['pace'] > 0.15 else ('スローペース' if result['pace'] < -0.15 else '平均ペース')
    print(f"\nseed={seed}  ペース={pace_label}({result['pace']:+.2f})  基準タイム={result['base_time']}秒")


if __name__ == '__main__':
    main()
