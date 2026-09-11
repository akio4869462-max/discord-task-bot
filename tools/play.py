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
    try:
        hl.enter_race(race, style=args.style)
    except ValueError as e:
        print(f"⚠️ {e}")
        return
    print(f"✅ {race['name']}（{race['course']}{race['surface']}{race['distance']}m"
          f" {race['cond']}）に登録しました。脚質 {args.style}{hl.format_travel(race)}")


def cmd_race(args):
    outcomes = hl.run_entries()
    if not outcomes:
        print("⚠️ 出走登録がありません。先に enter してください。")
        return
    for outcome in outcomes:
        print(f"🐎 {outcome['horse_name']}")
        print(hl.format_result(outcome))
        path = os.path.join(tempfile.gettempdir(),
                            f"race_{outcome['race']['id'].replace(':', '-')}.html")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(make_viewer.render(outcome['result']))
        print(f"\n🎬 再生用HTML: {path}\n")
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


def cmd_horses(args):
    data = hl.load_stable()
    for i, h in enumerate(data['horses'], start=1):
        role = '主戦' if hl.is_main(data, h) else '併せ馬'
        sel = '→' if h is data['current'] else ' '
        print(f"{sel}{i}. {h['name']}（{h['sex']}・{h['class']}・{h.get('growth_type', '普通')}・{role}）"
              f" {h['record']['starts']}戦{h['record']['win']}勝" + (f" 📋{h['entry']['name']}" if h.get('entry') else ''))


def cmd_select(args):
    data = hl.load_stable()
    if not 1 <= args.number <= len(data['horses']):
        print(f"⚠️ 1〜{len(data['horses'])} で指定してください。")
        return
    h = data['horses'][args.number - 1]
    if args.main:
        hl.set_main(data, h['id'])
        print(f"⭐ {h['name']} を主戦にしました。")
    else:
        hl.select_horse(data, h['id'])
        print(f"🐎 {h['name']} を選びました。")


def cmd_auction(args):
    data = hl.load_stable()
    if args.buy is None:
        print(hl.format_auction(data))
        print("\n買うには: python tools/play.py auction --buy <番号> [--name 名前]")
        return
    lots = hl.auction(data)
    if not 1 <= args.buy <= len(lots):
        print(f"⚠️ 1〜{len(lots)} で指定してください。")
        return
    try:
        foal, price = hl.buy_foal(lots[args.buy - 1]['key'], name=args.name, data=data)
    except ValueError as e:
        print(f"⚠️ {e}")
        return
    print(f"🐴 {foal['name']} を {price:,}万円で買いました。厩舎 {len(data['horses'])}/{hl.MAX_HORSES}頭")


def cmd_focus(args):
    key = None if args.param in (None, 'none') else args.param
    try:
        hl.set_focus(key)
    except ValueError as e:
        print(f"⚠️ {e}（{' / '.join(hl.PARAMS)} / none）")
        return
    print(f"🎯 今週の重点: {hl.PARAM_NAMES[key] if key else 'なし'}")


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
                # 適性に一番合うレースを選ぶ（遠征費を払えるものの中から）
                affordable = [r for r in races if r.get('travel', 0) <= data.get('funds', 0)]
                race = max(affordable or races, key=lambda r: _fit(horse, r))
                hl.enter_race(race, data=data, save=False)
                out = hl.run_entry(data=data, today=day, save=False)
                if out:
                    finishes.append(out['finish'])

        horse = data['current']
        params = hl.params_of(horse)
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

    sub.add_parser('horses', help='厩舎の馬を一覧する').set_defaults(func=cmd_horses)

    p = sub.add_parser('select', help='見る馬を切り替える（--main で主戦にする）')
    p.add_argument('number', type=int, help='horses で表示された番号')
    p.add_argument('--main', action='store_true')
    p.set_defaults(func=cmd_select)

    p = sub.add_parser('auction', help='セリを見る・仔馬を買う')
    p.add_argument('--buy', type=int, help='auction で表示された番号')
    p.add_argument('--name', help='仔馬の名前')
    p.set_defaults(func=cmd_auction)

    p = sub.add_parser('focus', help='今週の重点を決める')
    p.add_argument('param', nargs='?', help=' / '.join(hl.PARAMS) + ' / none')
    p.set_defaults(func=cmd_focus)

    p = sub.add_parser('sim', help='数週間ぶんを早送りして釣り合いを見る')
    p.add_argument('--weeks', type=int, default=10)
    p.add_argument('--hours', type=float, default=10, help='1週あたりの調教時間')
    p.set_defaults(func=cmd_sim)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
