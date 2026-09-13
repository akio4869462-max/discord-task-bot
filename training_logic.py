"""自宅ダンベルトレーニング記録モジュール

曜日ごとのトレーニングメニュー表示、完了ログ（連続記録つき）、体組成（体重・お腹周り）の
記録を管理します。1セッションは30分相当の調教として馬のスタミナ・パワーに
反映されます（horse_logic.py）。
"""

import json
import os
from datetime import datetime, timedelta, timezone

TRAINING_DATA_FILE = os.path.join('data', 'training_data.json')
JST = timezone(timedelta(hours=9))


# 【毎日のメニューの定義】月〜土は全て同じ内容（お風呂前の脂肪燃焼＆筋力アップ習慣）。
# 曜日ごとに分けていた頃の筋肉部位ローテーションはやめ、毎日続けられる短時間サーキットに統一した。
_DAILY_MENU = {
    "name": "全身サーキット（脂肪燃焼＆筋力アップ）",
    "images": [],  # 旧種目（ダンベル等）の画像しか無く一致しないため、新しい画像ができるまでテキストのみ
    "exercises": [
        "【ウォームアップ】",
        "アームサークル 1分",
        "トルソーツイスト 1分",
        "その場ジョギング 2分",
        "【メインサーキット】休憩60秒で3周",
        "スクワット 15回",
        "フォワードランジ 20回",
        "前腕プランク 45秒",
        "【クールダウン】",
        "アームサークル 2分（深呼吸をしながら）",
    ],
}

# datetime.weekday() は月曜=0〜日曜=6
# 平日勤務・土日休みのため、トレーニングはむしろ休みの土日に行いたい。
# 平日の中で疲労が溜まりやすい月曜を休養日にする。
WEEKLY_MENU = {
    0: None,  # 月曜：休養日
    1: _DAILY_MENU,
    2: _DAILY_MENU,
    3: _DAILY_MENU,
    4: _DAILY_MENU,
    5: _DAILY_MENU,
    6: _DAILY_MENU,
}

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


def is_rest_day(weekday=None):
    """指定した曜日（省略時は今日）が休養日かどうかを返します。"""
    if weekday is None:
        weekday = datetime.now(JST).weekday()
    return WEEKLY_MENU.get(weekday) is None


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
    """指定日の「前回のトレーニング予定日」を求めます（休養日は飛ばす）。"""
    prev_date = from_date - timedelta(days=1)
    if is_rest_day(prev_date.weekday()):
        prev_date -= timedelta(days=1)
    return prev_date


def _update_streak(data, today):
    """トレーニング記録の連続日数を更新します。

    休養日は記録が無くても連続記録を途切れさせません。
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


# 明らかな入力ミス（桁の打ち間違い等）だけを弾くための緩い範囲。
# 実際の値域を厳密に制限する意図はない。
WEIGHT_RANGE_KG = (20, 300)
WAIST_RANGE_CM = (30, 250)


def log_measurement(weight_kg, waist_cm, now=None):
    """体重・お腹周りを記録します。

    Args:
        weight_kg (float): 体重(kg)。
        waist_cm (float): お腹周り(cm)。
        now (datetime, optional): 基準日時（省略時は現在時刻。テスト用の注入口）。

    Returns:
        str: 記録完了メッセージ（前回記録との差分があれば併記）。入力が明らかに
             異常な範囲の場合はその旨のエラーメッセージ。
    """
    if not (WEIGHT_RANGE_KG[0] <= weight_kg <= WEIGHT_RANGE_KG[1]):
        return f"❌ 体重は{WEIGHT_RANGE_KG[0]}〜{WEIGHT_RANGE_KG[1]}kgの範囲で入力してください（桁の打ち間違いを防ぐための緩いチェックです）。"
    if not (WAIST_RANGE_CM[0] <= waist_cm <= WAIST_RANGE_CM[1]):
        return f"❌ お腹周りは{WAIST_RANGE_CM[0]}〜{WAIST_RANGE_CM[1]}cmの範囲で入力してください（桁の打ち間違いを防ぐための緩いチェックです）。"

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
    """直近7日間のトレーニング実施率を算出します（週間サマリー用、休養日は予定日数に含めない）。

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
        if is_rest_day(day.weekday()):
            continue
        scheduled_days += 1
        if day.strftime('%Y-%m-%d') in session_dates:
            completed_days += 1

    return completed_days, scheduled_days
