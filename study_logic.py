"""学習タイマーの記録モジュール

25分タイマーで勉強した時間を、内容（任意の一言）つきでためます。応用情報の演習記録
（exam_logic）のような分野分けはしません。何の勉強にも使えるようにするため、分けるのは
「内容」だけで、それも自由な文字列です。

⭕ 馬の育成への反映は、ここではなく呼び出し側（ui_study）が horse_logic で行う。
   このモジュールは Discord にも馬にも依存せず、記録と集計だけを受け持つ。
"""

import json
import os
from datetime import datetime, timedelta, timezone

STUDY_DATA_FILE = os.path.join('data', 'study_data.json')
JST = timezone(timedelta(hours=9))

# 内容の長さの上限。長文を入れられても、集計の表示が崩れないように切る。
TOPIC_MAX = 40

# 1回の記録で受け付ける時間（分）の上限。明らかな間違いを弾くための緩い値。
MINUTES_MAX = 600

# 内容を書かなかった記録の、集計での呼び名
NO_TOPIC_LABEL = '（内容なし）'

# 内容別の集計に出す件数
TOP_TOPICS = 5


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


def load_study_data():
    """学習の記録をファイルから読み込みます。"""
    data = _load_json(STUDY_DATA_FILE, {})
    if not isinstance(data.get('sessions'), list):
        data['sessions'] = []     # [{"date": "2026-11-14", "minutes": 25, "topic": "設計"}]
    return data


def save_study_data(data):
    """学習の記録をファイルへ保存します。"""
    try:
        os.makedirs(os.path.dirname(STUDY_DATA_FILE), exist_ok=True)
        with open(STUDY_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] 学習の記録の保存に失敗しました: {e}")


def normalize_topic(topic):
    """内容を整えます。前後の空白を除き、途中の空白や改行は1つの空白にまとめ、長すぎれば切ります。"""
    if not isinstance(topic, str):
        return ''
    return ' '.join(topic.split())[:TOPIC_MAX]


def _valid_minutes(minutes):
    return isinstance(minutes, int) and not isinstance(minutes, bool) and 0 < minutes <= MINUTES_MAX


def _minutes_of(session):
    m = session.get('minutes')
    return m if _valid_minutes(m) else 0


def _week_start(day):
    """day を含む週の月曜日。週間サマリーと同じく、月曜はじまりで数える。"""
    return day - timedelta(days=day.weekday())


def summarize(now=None, data=None):
    """今日・今週・全期間の合計時間（分）を返します。

    Args:
        now (datetime, optional): 基準日時（テスト用の注入口）。
    """
    now = now or datetime.now(JST)
    data = data if data is not None else load_study_data()
    today = now.strftime('%Y-%m-%d')
    week_from = _week_start(now.date()).strftime('%Y-%m-%d')

    today_minutes = week_minutes = total_minutes = 0
    for s in data['sessions']:
        m = _minutes_of(s)
        date = s.get('date', '')
        total_minutes += m
        if date >= week_from and date <= today:
            week_minutes += m
        if date == today:
            today_minutes += m
    return {'today': today_minutes, 'week': week_minutes, 'total': total_minutes,
            'count': len(data['sessions'])}


def format_minutes(minutes):
    """分を「1時間25分」「25分」のように読みやすくします。"""
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}時間{rest}分"
    if hours:
        return f"{hours}時間"
    return f"{rest}分"


def log_session(minutes, topic='', now=None):
    """学習1回ぶんを記録します。

    Args:
        minutes (int): 学習した時間（分）。
        topic (str): 何を勉強したか（任意の一言）。
        now (datetime, optional): 基準日時（テスト用の注入口）。

    Returns:
        str: 記録結果メッセージ（今日・今週の合計つき）。入力が不正な場合はその旨を返す。
    """
    if not _valid_minutes(minutes):
        return f"❌ 時間は1〜{MINUTES_MAX}分の整数で指定してください。"

    now = now or datetime.now(JST)
    topic = normalize_topic(topic)

    data = load_study_data()
    data['sessions'].append({
        "date": now.strftime('%Y-%m-%d'),
        "minutes": minutes,
        "topic": topic,
    })
    save_study_data(data)

    totals = summarize(now, data)
    msg = "📚 学習を記録しました！\n"
    msg += f"内容: {topic or NO_TOPIC_LABEL}（{format_minutes(minutes)}）\n"
    msg += f"今日の合計: {format_minutes(totals['today'])} ／ 今週の合計: {format_minutes(totals['week'])}"
    return msg


def get_stats_summary(now=None, data=None):
    """今日・今週・累計と、内容別の合計（多い順）を文章にします。"""
    now = now or datetime.now(JST)
    data = data if data is not None else load_study_data()
    if not data['sessions']:
        return "📚 学習の記録はまだありません。「⏱️ 学習タイマー」で、25分から始められます。"

    totals = summarize(now, data)
    msg = "📚 **学習の記録**\n"
    msg += f"今日: {format_minutes(totals['today'])} ／ 今週: {format_minutes(totals['week'])}\n"
    msg += f"累計: {format_minutes(totals['total'])}（{totals['count']}回）\n"

    by_topic = {}
    for s in data['sessions']:
        label = normalize_topic(s.get('topic')) or NO_TOPIC_LABEL
        by_topic[label] = by_topic.get(label, 0) + _minutes_of(s)
    ranked = sorted(by_topic.items(), key=lambda kv: (-kv[1], kv[0]))
    msg += "\n内容別（累計）:\n"
    for label, minutes in ranked[:TOP_TOPICS]:
        msg += f"・{label}: {format_minutes(minutes)}\n"
    if len(ranked) > TOP_TOPICS:
        msg += f"…ほか{len(ranked) - TOP_TOPICS}件\n"
    return msg.rstrip('\n')
