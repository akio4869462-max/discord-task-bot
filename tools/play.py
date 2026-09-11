"""Discord を使わずに厩舎を触るCLI。

育成とレースの手触りを確かめたり、成長カーブの釣り合いを見たりするのに使う。
Bot を起動しないので、テスト用のトークンは要らない。

    PYTHONIOENCODING=utf-8 python tools/play.py status
    PYTHONIOENCODING=utf-8 python tools/play.py train programming 60
    PYTHONIOENCODING=utf-8 python tools/play.py races
    PYTHONIOENCODING=utf-8 python tools/play.py enter 2 差し
    PYTHONIOENCODING=utf-8 python tools/play.py race --open
    PYTHONIOENCODING=utf-8 python tools/play.py breed --pick 3 --name ユメノコ
    PYTHONIOENCODING=utf-8 python tools/play.py pedigree
    PYTHONIOENCODING=utf-8 python tools/play.py sim --weeks 10 --hours 10

⭕ sim は本物の厩舎データを触らない。釣り合いを見るためだけの使い捨ての馬で回す。
"""

import argparse
import os
import statistics
import sys
import tempfile
import webbrowser
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import horse_logic as hl                                    # noqa: E402
from race_sim import calendar as race_calendar              # noqa: E402
from race_sim.tools import make_viewer                      # noqa: E402

CATEGORY_HELP = ' / '.join(hl.ACTIVITY_PARAMS)


def cmd_status(args):
    print(hl.format_horse())


def cmd_train(args):
    result = hl.add_growth(args.category, args.minutes)
    if not result['gains']:
        print(f"⚠️ 記録できませんでした。カテゴリは {CATEGORY_HELP} のいずれかです。")
        return
    gains = ' / '.join(f"{hl.PARAM_NAMES[k]} +{v}" for k, v in result['gains'].items())
    print(f"✅ {args.category} {args.minutes}分 → {gains}")
    print(f"   連続{result['streak']}日 ／ 調子 {hl.CONDITION_LABELS[result['condition']]}")


def cmd_races(args):
    data = hl.load_stable()
    day, races = hl.available_races(data)
    print(hl.format_races(day, races))
    if races:
        print("\n出走するには: python tools/play.py enter <番号> <脚質>")


def cmd_enter(args):
    data = hl.load_stable()
    day, races = hl.available_races(data)
    if not 1 <= args.number <= len(races):
        print(f"⚠️ 1〜{len(races)} で指定してください。")
        return
    race = races[args.number - 1]
    hl.enter_race(race, style=args.style)
    print(f"✅ {race['name']}（{race['course']}{race['surface']}{race['distance']}m"
          f" {race['cond']}）に登録しました。脚質 {args.style}")


def cmd_race(args):
    outcome = hl.run_entry()
    if outcome is None:
        print("⚠️ 出走登録がありません。先に enter してください。")
        return
    print(hl.format_result(outcome))

    path = os.path.join(tempfile.gettempdir(),
                        f"race_{outcome['race']['id'].replace(':', '-')}.html")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(make_viewer.render(outcome['result']))
    print(f"\n🎬 再生用HTML: {path}")
    if args.open:
        webbrowser.open('file://' + path.replace('\\', '/'))


def cmd_breed(args):
    data = hl.load_stable()
    if args.cancel:
        plan = hl.cancel_breeding(data)
        print(f"↩️ {plan['partner']['name']} の予約を取り消し、{plan['fee']:,}万円を戻しました。"
              if plan else "予約はありません。")
        return
    if args.pick is None:
        print(hl.format_candidates(data))
        if hl.breeding_status(data['current'])[0]:
            print("\n予約するには: python tools/play.py breed --pick <番号> [--name 仔の名前]")
        return
    cands = hl.breeding_candidates(data)
    if not 1 <= args.pick <= len(cands):
        print(f"⚠️ 1〜{len(cands)} で指定してください。")
        return
    try:
        plan = hl.reserve_breeding(cands[args.pick - 1]['key'], foal_name=args.name, data=data)
    except ValueError as e:
        print(f"⚠️ {e}")
        return
    p = plan['partner']
    print(f"🧬 {p['name']}（{p['class']}）と配合を予約しました。種付け料 {plan['fee']:,}万円"
          f" ／ 残り資金 {data['funds']:,}万円")


def cmd_pedigree(args):
    print(hl.format_pedigree(hl.load_stable()['current']))


def cmd_sim(args):
    """使い捨ての馬で数週間ぶんを早送りし、弧の釣り合いを見る。"""
    tmp = tempfile.mkdtemp()
    real_stable, real_legacy = hl.STABLE_FILE, hl.LEGACY_PLAYER_FILE
    hl.STABLE_FILE = os.path.join(tmp, 'stable.json')
    hl.LEGACY_PLAYER_FILE = os.path.join(tmp, 'none.json')
    try:
        _run_sim(args)
    finally:
        hl.STABLE_FILE, hl.LEGACY_PLAYER_FILE = real_stable, real_legacy


def _run_sim(args):
    today = date(2026, 9, 14)          # 月曜から始める
    data = hl.load_stable(today)
    per_day = args.hours * 60 / 5      # 平日に5日ぶん均等に積む前提
    finishes, weeks_done = [], 0

    print(f"週{args.hours}時間・{args.weeks}週ぶんを早送りします（20戦で引退）。\n")
    print("週  クラス   能力(平均)  出走  着順")

    for week in range(args.weeks):
        for d in range(7):
            day = today + timedelta(days=week * 7 + d)
            if day.weekday() < 5:                      # 平日に調教する
                share = per_day / len(hl.ACTIVITY_PARAMS)
                for category, weights in hl.ACTIVITY_PARAMS.items():
                    hl.add_growth(category, share * len(weights) / sum(weights.values()),
                                  today=day, data=data, save=False)
            if race_calendar.is_race_day(day):
                horse = data['current']
                _, races = hl.available_races(data, on=day)
                if not races:
                    continue
                # 適性に一番合うレースを選ぶ
                race = max(races, key=lambda r: _fit(horse, r))
                hl.enter_race(race, data=data, save=False)
                out = hl.run_entry(data=data, today=day, save=False)
                if out:
                    finishes.append(out['finish'])

        horse = data['current']
        params = hl.derive_params(horse['growth'])
        avg = int(statistics.fmean(params.values()))
        rec = horse['record']
        weeks_done = week + 1
        print(f"{weeks_done:2d}  {horse['class']:6s} {avg:6d}      "
              f"{rec['starts']:2d}戦{rec['win']}勝  "
              f"{'/'.join(str(f) for f in finishes[-2:]) if finishes else '-'}")

    print()
    print(f"世代: {data['generation']} ／ 引退馬 {len(data['retired'])}頭")
    for r in data['retired']:
        rec = r['record']
        print(f"  {r['name']}（{r['class']}）{rec['starts']}戦{rec['win']}勝"
              f" 獲得{rec['prize']:,}万円")
    if finishes:
        print(f"平均着順 {statistics.fmean(finishes):.1f} ／ "
              f"勝率 {finishes.count(1) / len(finishes):.0%} ／ "
              f"複勝率 {sum(1 for f in finishes if f <= 3) / len(finishes):.0%}")


def _fit(horse, race):
    """その馬にとってのレースの噛み合い具合（適性の高さ）。"""
    apt = horse['aptitude']
    score = {'A': 3, 'B': 2, 'C': 1, 'D': 0}
    surface = 'turf' if race['surface'] == '芝' else 'dirt'
    band = race_calendar.rivals.distance_band(race['distance'])
    return score.get(apt.get(surface, 'B'), 1) + score.get(apt.get(band, 'B'), 1)


def main():
    ap = argparse.ArgumentParser(description='Discordを使わずに厩舎を触る')
    sub = ap.add_subparsers(dest='command', required=True)

    sub.add_parser('status', help='現役馬のステータスを表示する').set_defaults(func=cmd_status)

    p = sub.add_parser('train', help='調教を記録する')
    p.add_argument('category', help=CATEGORY_HELP)
    p.add_argument('minutes', type=float)
    p.set_defaults(func=cmd_train)

    sub.add_parser('races', help='出走できるレースを見る').set_defaults(func=cmd_races)

    p = sub.add_parser('enter', help='出走を登録する')
    p.add_argument('number', type=int, help='races で表示された番号')
    p.add_argument('style', nargs='?', default='差し', choices=['逃げ', '先行', '差し', '追込'])
    p.set_defaults(func=cmd_enter)

    p = sub.add_parser('race', help='登録したレースを走らせる')
    p.add_argument('--open', action='store_true', help='再生用HTMLをブラウザで開く')
    p.set_defaults(func=cmd_race)

    p = sub.add_parser('breed', help='配合の相手を見る・予約する')
    p.add_argument('--pick', type=int, help='breed で表示された番号')
    p.add_argument('--name', help='仔の名前（省略すると自動）')
    p.add_argument('--cancel', action='store_true', help='予約を取り消して種付け料を戻す')
    p.set_defaults(func=cmd_breed)

    sub.add_parser('pedigree', help='現役馬の血統表を見る').set_defaults(func=cmd_pedigree)

    p = sub.add_parser('sim', help='数週間ぶんを早送りして釣り合いを見る')
    p.add_argument('--weeks', type=int, default=10)
    p.add_argument('--hours', type=float, default=10, help='1週あたりの調教時間')
    p.set_defaults(func=cmd_sim)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
