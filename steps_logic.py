"""歩数の記録モジュール

日ごとの歩数を保存し、馬の調教（スタミナ・パワー）に反映できる「新しく数えられる歩数」を
返します。換算そのものは horse_logic.log_walking() が行います。

⭕ 入力は「その日の合計歩数」で、足し算ではない。同じ日に何度書き込んでも、調教に入るのは
   前回までに数えた分を超えた差分だけ。朝3,000歩→夜9,000歩なら、2回目は6,000歩ぶん。
   手動入力のほか、将来スマホのヘルスケア等から日次の合計を自動で送ってくる経路が
   増えても、同じ日の合計を繰り返し書き込まれて二重に加算されないようにするため。
"""

import json
import os
from datetime import datetime, timedelta, timezone

STEPS_DATA_FILE = os.path.join('data', 'steps_data.json')
JST = timezone(timedelta(hours=9))

# 調教に数える歩数の1日の上限。それ以上歩いた日も、記録は残るが調教には入らない。
STEPS_DAILY_CAP = 15000

# 明らかな入力ミス（桁の打ち間違い等）だけを弾くための緩い範囲。
STEPS_RANGE = (0, 100000)


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


def load_steps_data():
    """歩数の記録をファイルから読み込みます。"""
    data = _load_json(STEPS_DATA_FILE, {})
    if not isinstance(data.get('days'), dict):
        data['days'] = {}   # {"2026-10-17": {"steps", "credited", "source"}}
    return data


def save_steps_data(data):
    """歩数の記録をファイルへ保存します。"""
    try:
        os.makedirs(os.path.dirname(STEPS_DATA_FILE), exist_ok=True)
        with open(STEPS_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] 歩数の記録の保存に失敗しました: {e}")


def log_steps(steps, now=None, source='manual'):
    """今日の合計歩数を記録します。

    Args:
        steps (int): 今日の合計歩数。
        now (datetime, optional): 基準日時（省略時は現在時刻。テスト用の注入口）。
        source (str): 記録元。手動入力は 'manual'。

    Returns:
        tuple: (メッセージ, 調教に新しく数える歩数)。入力が不正な場合や、前回までに数えた
               分を超えていない場合の歩数は 0。
    """
    lo, hi = STEPS_RANGE
    if not isinstance(steps, int) or isinstance(steps, bool) or not (lo <= steps <= hi):
        return f"❌ 歩数は{lo:,}〜{hi:,}歩の範囲で入力してください（桁の打ち間違いを防ぐための緩いチェックです）。", 0

    now = now or datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')

    data = load_steps_data()
    entry = data['days'].get(today_str, {"steps": 0, "credited": 0})

    countable = min(steps, STEPS_DAILY_CAP)
    credit = max(0, countable - entry.get('credited', 0))

    data['days'][today_str] = {
        "steps": steps,
        # 数えた歩数は減らさない。入力を訂正して減らしても、調教に入った分は取り消さない
        "credited": max(entry.get('credited', 0), countable),
        "source": source,
    }
    save_steps_data(data)

    msg = f"👟 今日の歩数を {steps:,}歩 で記録しました。"
    if steps > STEPS_DAILY_CAP:
        msg += f"\n（調教に反映されるのは1日{STEPS_DAILY_CAP:,}歩までです）"
    return msg, credit


# ====================================================
# 集計
# ====================================================

# 日次メトリクスに載せる日ごとの歩数の期間
METRICS_DAYS = 30


def summarize_period(start, end, data=None):
    """start〜end（両端を含む）の歩数を集計します。

    ⭕ 記録の無い日は0歩ではなく「データ無し」。平均は記録のある日だけで割る
       （端末が未同期の日や、連携が動く前の日を0歩として混ぜると、平均が実態より下がる）。

    Returns:
        dict: {'days': 記録のある日数, 'total': 合計, 'average': 1日平均（記録が無ければ0）,
               'best': (日付文字列, 歩数)。記録が無ければ None}
    """
    data = data if data is not None else load_steps_data()
    rows = []
    day = start
    while day <= end:
        entry = data['days'].get(day.strftime('%Y-%m-%d'))
        if isinstance(entry, dict) and isinstance(entry.get('steps'), int):
            rows.append((day.strftime('%Y-%m-%d'), entry['steps']))
        day += timedelta(days=1)

    total = sum(steps for _, steps in rows)
    return {
        'days': len(rows),
        'total': total,
        'average': round(total / len(rows)) if rows else 0,
        'best': max(rows, key=lambda r: r[1]) if rows else None,
    }


def get_weekly_steps_summary(today=None, data=None):
    """週間サマリーに追記する、先週（直前の7日間）の歩数の文言を返します。

    Args:
        today (date, optional): 基準日（省略時は今日。テスト用の注入口）。月曜の朝に呼ぶ想定で、
            今日を含めない直前の7日間（月〜日）を「先週」とする。

    Returns:
        str: 先頭が改行の文言。先週の記録が1日も無ければ空文字。
    """
    today = today or datetime.now(JST).date()
    data = data if data is not None else load_steps_data()
    last = summarize_period(today - timedelta(days=7), today - timedelta(days=1), data)
    if not last['days']:
        return ""

    best_day, best_steps = last['best']
    best_day = f"{int(best_day[5:7])}/{int(best_day[8:10])}"      # 11/2（ゼロ埋めしない）
    msg = (f"\n👟 先週の歩数: 合計 {last['total']:,}歩 ／ 1日平均 {last['average']:,}歩"
           f"（記録のある{last['days']}日）\n　最多は {best_day} の {best_steps:,}歩")

    prev = summarize_period(today - timedelta(days=14), today - timedelta(days=8), data)
    if prev['average']:
        diff = round((last['average'] - prev['average']) / prev['average'] * 100)
        if diff > 0:
            msg += f"\n📈 1日平均は、前の週より {diff}% 多くなりました。"
        elif diff < 0:
            msg += f"\n📉 1日平均は、前の週より {abs(diff)}% 少なめでした。"
    return msg


def metrics_summary(today=None, data=None):
    """日次メトリクス（進捗ダッシュボード用）に載せる歩数の集計を返します。

    Returns:
        dict: {'asOf': 基準日（YYYY-MM-DD。グラフの右端）,
               'recordedDays': 記録のある日の総数, 'totalAll': 全期間の合計,
               'last7': 直近7日, 'prev7': その前の7日, 'daily': 直近METRICS_DAYS日の記録のある日だけ}
               last7/prev7 は summarize_period と同じ形（best は [日付, 歩数] か None）。
    """
    today = today or datetime.now(JST).date()
    data = data if data is not None else load_steps_data()
    start = today - timedelta(days=METRICS_DAYS - 1)

    def span(first, last):
        s = summarize_period(first, last, data)
        return {**s, 'best': list(s['best']) if s['best'] else None}

    daily = []
    day = start
    while day <= today:
        key = day.strftime('%Y-%m-%d')
        entry = data['days'].get(key)
        if isinstance(entry, dict) and isinstance(entry.get('steps'), int):
            daily.append({'date': key, 'steps': entry['steps']})
        day += timedelta(days=1)

    all_rows = [e['steps'] for e in data['days'].values()
                if isinstance(e, dict) and isinstance(e.get('steps'), int)]
    return {
        'asOf': today.strftime('%Y-%m-%d'),
        'recordedDays': len(all_rows),
        'totalAll': sum(all_rows),
        'last7': span(today - timedelta(days=6), today),
        'prev7': span(today - timedelta(days=13), today - timedelta(days=7)),
        'daily': daily,
    }
