"""自宅ダンベルトレーニング記録モジュール

曜日ごとのトレーニングメニュー表示、完了ログ（連続記録つき）、体組成（体重・お腹周り）の
記録を管理します。就活RPG（study_logic.py）のEXP/レベルシステムとは独立して動作します。
"""

import json
import os
from datetime import datetime, timedelta, timezone

TRAINING_DATA_FILE = os.path.join('data', 'training_data.json')
JST = timezone(timedelta(hours=9))

TRAINING_ASSETS_DIR = os.path.join('assets', 'training')


def _images(prefix, count):
    """指定した接頭辞の分割画像ファイルパスをcount枚分のリストで返します。"""
    return [os.path.join(TRAINING_ASSETS_DIR, f'{prefix}_{i}.png') for i in range(1, count + 1)]


# 【週間メニューの定義】datetime.weekday() は月曜=0〜日曜=6
WEEKLY_MENU = {
    0: {
        "name": "上半身①（胸・肩・二の腕）",
        "images": _images('upper1', 3),
        "exercises": [
            "ダンベルベンチプレス（床でも可） 4×8〜10",
            "ダンベルショルダープレス 3×10",
            "サイドレイズ 3×15",
            "アーノルドプレス 3×10",
            "ダンベルカール 3×12",
            "トライセプスエクステンション 3×12",
        ],
    },
    1: {
        "name": "下半身・臀部",
        "images": _images('lower', 2),
        "exercises": [
            "ダンベルスクワット 4×12",
            "ブルガリアンスクワット（片足、ベンチ使用） 3×10（各脚）",
            "ルーマニアンデッドリフト 4×10",
            "ダンベルランジ 3×12（各脚）",
            "カーフレイズ 3×20",
        ],
    },
    2: {
        "name": "体幹サーキット（脂肪燃焼）",
        "images": _images('circuit', 2),
        "exercises": [
            "【サーキット】休憩30〜45秒で3〜4周（合計20〜25分）",
            "ダンベルスラスター 10回",
            "マウンテンクライマー 30秒",
            "ダンベルスイング（片手ずつ） 15回（各側）",
            "プランク 40秒",
            "バーピー 10回",
        ],
    },
    3: {
        "name": "上半身②（背中・肩）",
        "images": _images('upper2', 2),
        "exercises": [
            "ワンハンドダンベルロウ 4×10（各側）",
            "ダンベルデッドリフト 3×10",
            "リアレイズ 3×15",
            "シュラッグ 3×15",
            "ダンベルプルオーバー 3×12",
        ],
    },
    4: {
        "name": "下半身・臀部",
        "images": _images('lower', 2),
        "exercises": [
            "ダンベルスクワット 4×12",
            "ブルガリアンスクワット（片足、ベンチ使用） 3×10（各脚）",
            "ルーマニアンデッドリフト 4×10",
            "ダンベルランジ 3×12（各脚）",
            "カーフレイズ 3×20",
        ],
    },
    5: {
        "name": "体幹サーキット（脂肪燃焼）",
        "images": _images('circuit', 2),
        "exercises": [
            "【サーキット】休憩30〜45秒で3〜4周（合計20〜25分）",
            "ダンベルスラスター 10回",
            "マウンテンクライマー 30秒",
            "ダンベルスイング（片手ずつ） 15回（各側）",
            "プランク 40秒",
            "バーピー 10回",
        ],
    },
    6: None,  # 日曜：休養日
}

# 休養日以外、毎回のトレーニング後に行う腹筋メニュー
AB_FINISHER = [
    "プランク 40秒 × 2",
    "レッグレイズ 15回 × 2",
    "ロシアンツイスト（ダンベルを持って） 20回 × 2",
]

# 節目に達した「その日」だけ公開告知するための一覧
TRAINING_STREAK_MILESTONES = [3, 7, 14, 30]


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


def load_training_data():
    """トレーニング記録データをファイルから読み込みます。"""
    return _load_json(TRAINING_DATA_FILE, {
        "sessions": [],          # 完了ログの一覧: [{"date", "day_type", "note"}]
        "measurements": [],      # 体組成記録の一覧: [{"date", "weight_kg", "waist_cm"}]
        "current_streak": 0,     # トレーニングの連続記録日数
        "last_active_date": None,
    })


def save_training_data(data):
    """トレーニング記録データをファイルへ保存します。"""
    try:
        os.makedirs(os.path.dirname(TRAINING_DATA_FILE), exist_ok=True)
        with open(TRAINING_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] トレーニングデータの保存に失敗しました: {e}")


def get_today_menu(weekday=None):
    """指定した曜日（0=月〜6=日、省略時は今日）のトレーニングメニューを整形して返します。"""
    if weekday is None:
        weekday = datetime.now(JST).weekday()

    menu = WEEKLY_MENU.get(weekday)
    if menu is None:
        return "🛌 **今日は休養日です。** 完全休養、または軽いストレッチ程度にしましょう。"

    msg = f"💪 **【今日のトレーニング】{menu['name']}**\n"
    for line in menu['exercises']:
        msg += f"・{line}\n"
    msg += "\n🔥 **仕上げ（毎回）**\n"
    for line in AB_FINISHER:
        msg += f"・{line}\n"
    return msg


def get_today_menu_image_paths(weekday=None):
    """指定した曜日（省略時は今日）のトレーニングメニュー画像のファイルパス一覧を返します。

    休養日の場合は空リストを返します。存在しない画像ファイルは結果から除外されます。
    """
    if weekday is None:
        weekday = datetime.now(JST).weekday()

    menu = WEEKLY_MENU.get(weekday)
    if menu is None:
        return []

    return [p for p in menu.get('images', []) if os.path.exists(p)]


def _previous_scheduled_date(from_date):
    """指定日の「前回のトレーニング予定日」を求めます（日曜は休養日として飛ばす）。"""
    prev_date = from_date - timedelta(days=1)
    if prev_date.weekday() == 6:
        prev_date -= timedelta(days=1)
    return prev_date


def _update_streak(data, today):
    """トレーニング記録の連続日数を更新します。

    日曜（休養日）は記録が無くても連続記録を途切れさせません。
    """
    today_str = today.strftime('%Y-%m-%d')
    expected_prev_str = _previous_scheduled_date(today).strftime('%Y-%m-%d')
    last_active = data.get('last_active_date')

    if last_active == expected_prev_str:
        data['current_streak'] = data.get('current_streak', 0) + 1
    elif last_active != today_str:
        data['current_streak'] = 1

    data['last_active_date'] = today_str
    return data['current_streak']


def log_session(note=None, now=None):
    """今日のトレーニングを完了として記録し、連続記録を更新します。

    Args:
        note (str, optional): 一言メモ。
        now (datetime, optional): 基準日時（省略時は現在時刻。テスト用の注入口）。

    Returns:
        tuple: (メッセージ, 更新後のstreak または None（休養日/既に記録済みの場合）)
    """
    now = now or datetime.now(JST)
    weekday = now.weekday()

    if WEEKLY_MENU.get(weekday) is None:
        return "今日は休養日です。記録は不要ですが、お疲れ様でした！", None

    data = load_training_data()
    today_str = now.strftime('%Y-%m-%d')

    if any(s['date'] == today_str for s in data['sessions']):
        return "今日の記録は既に完了しています。", None

    data['sessions'].append({
        "date": today_str,
        "day_type": WEEKLY_MENU[weekday]['name'],
        "note": note or "",
    })

    streak = _update_streak(data, now)
    save_training_data(data)

    msg = f"✅ 今日のトレーニング（{WEEKLY_MENU[weekday]['name']}）を記録しました！お疲れ様でした！\n🔥 連続記録: {streak}日"
    return msg, streak


def log_measurement(weight_kg, waist_cm, now=None):
    """体重・お腹周りを記録します。

    Args:
        weight_kg (float): 体重(kg)。
        waist_cm (float): お腹周り(cm)。
        now (datetime, optional): 基準日時（省略時は現在時刻。テスト用の注入口）。

    Returns:
        str: 記録完了メッセージ（前回記録との差分があれば併記）。
    """
    data = load_training_data()
    today_str = (now or datetime.now(JST)).strftime('%Y-%m-%d')

    previous = data['measurements'][-1] if data['measurements'] else None

    data['measurements'].append({
        "date": today_str,
        "weight_kg": weight_kg,
        "waist_cm": waist_cm,
    })
    save_training_data(data)

    msg = f"📏 記録しました！ 体重: {weight_kg}kg / お腹周り: {waist_cm}cm\n"
    if previous:
        weight_diff = weight_kg - previous['weight_kg']
        waist_diff = waist_cm - previous['waist_cm']
        msg += f"前回（{previous['date']}）との差分: 体重 {weight_diff:+.1f}kg / お腹周り {waist_diff:+.1f}cm"
    return msg


def get_measurement_history(limit=10):
    """直近の体組成記録一覧を整形して返します。"""
    data = load_training_data()
    measurements = data.get('measurements', [])
    if not measurements:
        return "まだ記録がありません。`/training measure`で体重・お腹周りを記録してみましょう。"

    msg = "📏 **【体組成の記録】**\n"
    for m in measurements[-limit:]:
        msg += f"{m['date']}: 体重 {m['weight_kg']}kg / お腹周り {m['waist_cm']}cm\n"
    return msg


def get_weekly_training_rate(today=None):
    """直近7日間のトレーニング実施率を算出します（週間サマリー用、日曜は予定日数に含めない）。

    Args:
        today (date, optional): 基準日（省略時は今日。テスト用の注入口）。

    Returns:
        tuple: (完了日数, 予定日数)
    """
    data = load_training_data()
    today = today or datetime.now(JST).date()
    session_dates = {s['date'] for s in data.get('sessions', [])}

    scheduled_days = 0
    completed_days = 0
    for i in range(7):
        day = today - timedelta(days=i)
        if day.weekday() == 6:
            continue
        scheduled_days += 1
        if day.strftime('%Y-%m-%d') in session_dates:
            completed_days += 1

    return completed_days, scheduled_days
