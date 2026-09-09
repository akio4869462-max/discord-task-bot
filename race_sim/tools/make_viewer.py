"""レース結果を埋め込んだ再生ビューアのHTMLを書き出す。

    # その場でレースを走らせて再生用HTMLを作る
    PYTHONIOENCODING=utf-8 python race_sim/tools/make_viewer.py --out race.html \
        --course 中山 --distance 2000 --class G1 --name 有馬記念

    # すでにある結果JSONから作る
    PYTHONIOENCODING=utf-8 python race_sim/tools/make_viewer.py --out race.html --result result.json

⭕ テンプレート（race_sim/viewer.html）は <html> や <head> を持たない断片の形にしてある。
   Artifactとして公開するときはこの形のまま渡す必要があり、ブラウザで直接開くときは
   ここで完全なHTML文書に包む（--fragment を付ければ包まない）。
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from race_sim import engine, rivals  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'viewer.html')

DATA_START = '<script id="race-data" type="application/json">'
DATA_END = '</script>'

DOCUMENT = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 14px system-ui, sans-serif; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
{body}
</head>
<body></body>
</html>
"""


def render(result, template_path=None, fragment=False):
    """テンプレートに結果JSONを差し込んだHTMLを返す。"""
    with open(template_path or TEMPLATE, 'r', encoding='utf-8') as f:
        html = f.read()

    start = html.index(DATA_START) + len(DATA_START)
    end = html.index(DATA_END, start)
    payload = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    # ⭕ </script> が JSON の中に現れると script が途中で閉じてしまう。
    payload = payload.replace('</', '<\\/')

    html = html[:start] + '\n' + payload + '\n' + html[end:]

    # タブとギャラリーに出る名前はレース名にする
    name = result.get('race', {}).get('name')
    if name:
        html = html.replace('<title>レース再生</title>', '<title>' + name + '</title>', 1)

    return html if fragment else DOCUMENT.format(body=html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--result', default=None, help='既存の結果JSON。省略時はその場で走らせる')
    ap.add_argument('--fragment', action='store_true', help='<html>で包まずに断片のまま出す')
    ap.add_argument('--course', default='東京')
    ap.add_argument('--surface', default='芝', choices=['芝', 'ダ'])
    ap.add_argument('--distance', type=int, default=1600)
    ap.add_argument('--cond', default='良', choices=['良', '稍', '重', '不'])
    ap.add_argument('--class', dest='cls', default='2勝', choices=list(engine.CLASS_ORDER))
    ap.add_argument('--field', type=int, default=None)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--name', default='テストステークス')
    ap.add_argument('--my-horse', default=None, help='自分の馬の能力をカンマ区切りで指定する')
    ap.add_argument('--my-style', default='差し', choices=list(engine.STYLES))
    ap.add_argument('--my-condition', type=int, default=0, help='自分の馬の調子（-2〜+2）')
    ap.add_argument('--my-aptitude', default='', help='適性。例: turf=A,mile=A')
    args = ap.parse_args()

    if args.result:
        with open(args.result, 'r', encoding='utf-8') as f:
            result = json.load(f)
    else:
        seed = args.seed if args.seed is not None else random.randrange(10 ** 9)
        race = {'name': args.name, 'course': args.course, 'surface': args.surface,
                'distance': args.distance, 'cond': args.cond, 'class': args.cls}
        player = None
        if args.my_horse:
            values = [int(x) for x in args.my_horse.split(',')]
            aptitude = dict(pair.split('=') for pair in args.my_aptitude.split(',') if '=' in pair)
            player = {'name': 'マイホース', 'style': args.my_style, 'aptitude': aptitude,
                      'condition': args.my_condition,
                      'params': dict(zip(engine.JST_PARAMS, values))}
        entries = rivals.build_field(race, size=args.field, seed=seed, player=player)
        result = engine.simulate(race, entries, seed=seed)

    html = render(result, fragment=args.fragment)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(html)

    winner = result['horses'][0]
    print(f"書き出し: {args.out} ({os.path.getsize(args.out):,} bytes)")
    print(f"  {result['race']['name']} {len(result['horses'])}頭 / "
          f"勝ち馬 {winner['name']} {winner['time']}秒")


if __name__ == '__main__':
    main()
