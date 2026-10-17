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
