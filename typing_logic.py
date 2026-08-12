"""C++タイピング訓練モジュール

日次メニューの提示、ドリル本文（monkeytypeへ貼り付ける用）の配布、
ドリルの進行管理（A→B→C→D）、週1回の計測記録と目標対比を扱います。
就活RPG（study_logic.py）のEXP/レベルシステムとは独立して動作します。
"""

import json
import os
from datetime import datetime, timedelta, timezone

TYPING_DATA_FILE = os.path.join('data', 'typing_data.json')
JST = timezone(timedelta(hours=9))

# 訓練の開始日。目標ライン（○週後）の判定はこの日を起点に計算する
START_DATE = datetime(2026, 8, 12, tzinfo=JST).date()

# 開始時の基準値。以降の計測はこの値と対比して伸びを見る
BASELINE = {"wpm": 17, "accuracy": 89, "consistency": 38, "afk": 10}

# 週1回の計測を促す間隔（日数）
MEASUREMENT_INTERVAL_DAYS = 7

# 【大原則】毎日1つずつ日替わりで提示し、意識が薄れるのを防ぐ
PRINCIPLES = [
    "シフトは必ず**反対の手**で押す。`_` `::` `{}` `\"` `|` はすべて「右小指 + 左シフト」。",
    "**速度を捨てて精度100%で打つ。** 遅くていいので正しい指で打つ。誤運指の固定化が一番のコスト。",
    "練習中は**絶対に手元を見ない。** 分からなければ画面の記号を見て、指で探る。",
    "**1回20分を超えない。** 疲労後の練習は崩れたフォームを覚えてしまう。",
]

# 【ドリル定義】textはmonkeytypeのcustom textへそのまま貼り付ける
DRILLS = {
    "A": {
        "name": "右小指の単独ドリル",
        "note": "最初の3日はこれだけでよい",
        "text": "; : ; : ' \" ' \" [ ] { } [ ] { } - _ - _ = + = +\n: : : _ _ _ { { } } \" \" | | : _ { } \" |",
        "next_condition": "手元を見ずに1周、詰まりなし",
    },
    "B": {
        "name": "シフト側の数字（C++頻出のみ）",
        "note": "",
        "text": "& & * * ( ) ( ) # # % % ! !\n&& || (( )) ## (int) (void) &x *p",
        "next_condition": "手元を見ずに1周、詰まりなし",
    },
    "C": {
        "name": "C++二文字連",
        "note": "ここが実効速度を決める",
        "text": ":: -> << >> && || == != <= >= += -= ++ -- /* */ //\n:: :: -> -> << << >> >> && && || || ++ ++ -> ::",
        "next_condition": "`::` `->` `<<` で停止しない",
    },
    "D": {
        "name": "実トークン",
        "note": "Drill A〜C が詰まらなくなってから",
        "text": (
            "std::cout << x << std::endl;\n"
            "std::vector<int> v(10);\n"
            "for (int i = 0; i < n; ++i) {\n"
            "if (a && b) { x = y ? 1 : 0; }\n"
            "auto& ref = *ptr;\n"
            "#include <iostream>\n"
            "my_var_name = other_var + 1;\n"
            "template <typename T>\n"
            "std::unique_ptr<Foo> p = std::make_unique<Foo>();\n"
            "while (it != v.end()) { sum += *it++; }"
        ),
        "next_condition": "accuracy 95% 到達で typing.io へ（およそ3週目）",
    },
}

# 記号ドリルの進行順。Eは英字補強の別枠なのでこの順序には含めない
DRILL_ORDER = ["A", "B", "C", "D"]

# 【目標ライン】(開始からの週数, 各指標の目標値)
TARGET_MILESTONES = [
    (2, {"wpm": 25, "accuracy": 95, "consistency": 55, "afk": 3}),
    (6, {"wpm": 35, "accuracy": 97, "consistency": 70, "afk": 0}),
]

# 【指の担当表】JIS配列（US配列との差分を反映した完全版）
KEY_GUIDE_JIS = [
    ("; ", "そのまま", "右小指"),
    (":", "そのまま（独立キー、`;`の右）", "右小指"),
    ("*", "左シフト + `:`", "右小指"),
    ("+", "左シフト + `;`", "右小指"),
    ("=", "左シフト + `-`", "右小指"),
    ("_", "左シフト + `\\`（右下のろキー）", "右小指"),
    ("'", "左シフト + `7`", "右人差し指"),
    ('"', "右シフト + `2`", "左薬指"),
    ("[ ]", "そのまま", "右小指"),
    ("{ }", "左シフト + `[` `]`", "右小指"),
    ("|", "左シフト + `¥`", "右小指"),
    ("@", "そのまま（独立キー、`P`の右）", "右小指"),
    ("&", "左シフト + `6`", "右人差し指"),
    ("(", "左シフト + `8`", "右中指"),
    (")", "左シフト + `9`", "右薬指"),
    ("!", "右シフト + `1`", "左小指"),
    ("#", "右シフト + `3`", "左中指"),
    ("%", "右シフト + `5`", "左人差し指"),
    ("< >", "左シフト + `,` `.`", "右中指 / 右薬指"),
    ("?", "左シフト + `/`", "右小指"),
]

# 【指の担当表】US配列
KEY_GUIDE_US = [
    (";", "そのまま", "右小指"),
    (":", "左シフト + `;`", "右小指"),
    ("'", "そのまま", "右小指"),
    ('"', "左シフト + `'`", "右小指"),
    ("[ ]", "そのまま", "右小指"),
    ("{ }", "左シフト + `[` `]`", "右小指"),
    ("-", "そのまま", "右小指"),
    ("_", "左シフト + `-`", "右小指"),
    ("=", "そのまま", "右小指"),
    ("+", "左シフト + `=`", "右小指"),
    ("\\", "そのまま", "右小指"),
    ("|", "左シフト + `\\`", "右小指"),
    ("< >", "左シフト + `,` `.`", "右中指 / 右薬指"),
    ("?", "左シフト + `/`", "右小指"),
    ("&", "左シフト + `7`", "右人差し指"),
    ("*", "左シフト + `8`", "右中指"),
    ("(", "左シフト + `9`", "右薬指"),
    (")", "左シフト + `0`", "右小指"),
    ("!", "右シフト + `1`", "左小指"),
    ("#", "右シフト + `3`", "左中指"),
    ("%", "右シフト + `5`", "左人差し指"),
]

KEY_GUIDES = {"jis": KEY_GUIDE_JIS, "us": KEY_GUIDE_US}


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


def load_typing_data():
    """タイピング訓練データを読み込みます。"""
    return _load_json(TYPING_DATA_FILE, {
        "current_drill": "A",   # 現在取り組んでいる記号ドリル
        "measurements": [],     # [{"date", "wpm", "accuracy", "consistency", "afk", "note"}]
    })


def save_typing_data(data):
    """タイピング訓練データを保存します。"""
    try:
        os.makedirs(os.path.dirname(TYPING_DATA_FILE), exist_ok=True)
        with open(TYPING_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] タイピング訓練データの保存に失敗しました: {e}")


def weeks_elapsed(today=None):
    """訓練開始からの経過週数を返します（開始週は0）。"""
    today = today or datetime.now(JST).date()
    return max(0, (today - START_DATE).days // 7)


def get_current_target(today=None):
    """現時点で目指すべき目標ラインを返します。

    Returns:
        tuple: (目標週, 目標値dict)。全マイルストーン到達後は最終目標を返す。
    """
    weeks = weeks_elapsed(today)
    for milestone_week, target in TARGET_MILESTONES:
        if weeks < milestone_week:
            return milestone_week, target
    return TARGET_MILESTONES[-1]


def days_since_last_measurement(today=None):
    """最後の計測からの経過日数を返します。一度も計測していなければNone。"""
    data = load_typing_data()
    measurements = data.get('measurements', [])
    if not measurements:
        return None

    today = today or datetime.now(JST).date()
    last_date = datetime.strptime(measurements[-1]['date'], '%Y-%m-%d').date()
    return (today - last_date).days


def is_measurement_due(today=None):
    """今日が週1回の計測タイミングかどうかを判定します。

    曜日を固定するのではなく「前回計測から7日以上経過したか」で判定することで、
    実際の practice のリズムに合わせて促せるようにしています。
    """
    days = days_since_last_measurement(today)
    return days is None or days >= MEASUREMENT_INTERVAL_DAYS


def get_daily_menu(today=None):
    """その日の15〜20分メニューを、現在のドリル進行状況を反映して組み立てます。"""
    today = today or datetime.now(JST).date()
    data = load_typing_data()
    current = data.get('current_drill', 'A')
    drill = DRILLS.get(current, DRILLS['A'])

    msg = "⌨️ **【今日のタイピング訓練】**（15〜20分）\n"
    msg += "① 2分 ウォームアップ（monkeytype 通常モード・記号なし）\n"
    msg += f"② 8分 記号ドリル **Drill {current}**（{drill['name']}）\n"
    msg += "③ 5分 Drill E（keybr.com で英字の弱点補強）\n"

    # 最後の枠は、週1回の計測が溜まっていれば計測、そうでなければDrill D
    if is_measurement_due(today):
        msg += "④ 5分 🎯 **計測**（60s / english / punctuation ON / numbers ON）\n"
    else:
        msg += "④ 5分 Drill D（実トークン）\n"

    # 大原則を日替わりで1つだけ提示する（毎日全部出すと読み飛ばされるため）
    principle = PRINCIPLES[(today - START_DATE).days % len(PRINCIPLES)]
    msg += f"\n📌 **今日の心得**: {principle}"

    return msg


def get_drill_text(drill_id):
    """monkeytypeのcustom textへ貼り付けるドリル本文を返します。

    Discordのコードブロックで囲むことで、そのままコピーできる形にしています。
    """
    drill_id = (drill_id or "").upper()

    if drill_id == "E":
        return (
            "⌨️ **Drill E — 英字の弱点補強**\n"
            "keybr.com はタイプミスの実データから弱いキーを自動抽出するため、"
            "`q x z w j` のようなローマ字入力では鍛えられない低頻度文字を狙い撃ちできます。\n\n"
            "・<https://www.keybr.com/> を開き、ログインなしでそのまま開始\n"
            "・レッスンは自動生成されるので貼り付け不要（1レッスン約5分）\n"
            "・週1回、プロフィール画面の heatmap で弱点キーの推移を確認する"
        )

    drill = DRILLS.get(drill_id)
    if not drill:
        return "そのドリルは見つかりません。A〜E で指定してください。"

    note = f"（{drill['note']}）" if drill['note'] else ""
    msg = f"⌨️ **Drill {drill_id} — {drill['name']}**{note}\n"
    msg += "monkeytype → 右上の歯車 → `custom` に貼り付け（`repeat` をオンにすると繰り返せます）\n"
    msg += f"```\n{drill['text']}\n```"
    msg += f"\n次に進む条件: {drill['next_condition']}"
    return msg


def advance_drill():
    """記号ドリルを次の段階へ進めます（A→B→C→D）。

    Returns:
        str: 進行結果のメッセージ。
    """
    data = load_typing_data()
    current = data.get('current_drill', 'A')

    if current not in DRILL_ORDER:
        current = 'A'

    idx = DRILL_ORDER.index(current)
    if idx >= len(DRILL_ORDER) - 1:
        return (
            f"🎉 既に最終段階の Drill {current} です。\n"
            f"次のステップ: {DRILLS[current]['next_condition']}"
        )

    next_drill = DRILL_ORDER[idx + 1]
    data['current_drill'] = next_drill
    save_typing_data(data)

    return (
        f"🎉 Drill {current} クリア！ **Drill {next_drill}（{DRILLS[next_drill]['name']}）** に進みます。\n"
        f"次に進む条件: {DRILLS[next_drill]['next_condition']}"
    )


def log_measurement(wpm, accuracy, consistency, afk, note=None, today=None):
    """週1回の計測結果を記録し、開始時からの伸びと目標との差を返します。

    Args:
        wpm (int): net WPM。
        accuracy (int): 正確率(%)。
        consistency (int): consistency(%)。
        afk (float): afk(%)。
        note (str, optional): メモ。
        today (date, optional): 基準日（テスト用の注入口）。

    Returns:
        str: 記録結果メッセージ。入力が不正な場合はその旨を返す。
    """
    if not (0 <= accuracy <= 100 and 0 <= consistency <= 100 and 0 <= afk <= 100):
        return "❌ accuracy / consistency / afk は 0〜100 の範囲で入力してください。"
    if wpm <= 0:
        return "❌ WPM は1以上を指定してください。"

    today = today or datetime.now(JST).date()
    data = load_typing_data()
    data['measurements'].append({
        "date": today.strftime('%Y-%m-%d'),
        "wpm": wpm,
        "accuracy": accuracy,
        "consistency": consistency,
        "afk": afk,
        "note": note or "",
    })
    save_typing_data(data)

    msg = f"🎯 計測を記録しました（{today.strftime('%Y-%m-%d')}）\n"
    msg += f"net {wpm} WPM / acc {accuracy}% / consistency {consistency}% / afk {afk}%\n\n"

    # 開始時の基準値からの伸び
    msg += "**開始時からの変化**\n"
    msg += f"WPM {wpm - BASELINE['wpm']:+d} / acc {accuracy - BASELINE['accuracy']:+d}pt / "
    msg += f"consistency {consistency - BASELINE['consistency']:+d}pt / afk {afk - BASELINE['afk']:+.1f}pt\n\n"

    # 次の目標ラインとの差
    target_week, target = get_current_target(today)
    msg += f"**{target_week}週後の目標まで**\n"
    gaps = []
    if wpm < target['wpm']:
        gaps.append(f"WPM あと{target['wpm'] - wpm}")
    if accuracy < target['accuracy']:
        gaps.append(f"acc あと{target['accuracy'] - accuracy}pt")
    if consistency < target['consistency']:
        gaps.append(f"consistency あと{target['consistency'] - consistency}pt")
    if afk > target['afk']:
        gaps.append(f"afk あと{afk - target['afk']:.1f}pt削減")

    msg += "、".join(gaps) if gaps else "✅ 全指標クリア！素晴らしいです。"

    # consistency と afk を最優先指標として扱う（速度は結果としてついてくる）
    if consistency < target['consistency'] or afk > target['afk']:
        msg += "\n\n💡 consistency と afk が最優先の指標です。止まらずに打つことを意識しましょう。"

    return msg


def get_progress_summary(today=None, limit=10):
    """計測履歴と、現在地・目標ラインをまとめて返します。"""
    today = today or datetime.now(JST).date()
    data = load_typing_data()
    measurements = data.get('measurements', [])
    current = data.get('current_drill', 'A')
    weeks = weeks_elapsed(today)

    msg = "⌨️ **【タイピング訓練の進捗】**\n"
    msg += f"開始から {weeks} 週目／現在の記号ドリル: **Drill {current}**\n\n"

    msg += f"**基準値（{START_DATE}）**\n"
    msg += f"net {BASELINE['wpm']} WPM / acc {BASELINE['accuracy']}% / "
    msg += f"consistency {BASELINE['consistency']}% / afk {BASELINE['afk']}%\n\n"

    if not measurements:
        msg += "まだ計測記録がありません。週1回の計測を記録していきましょう。"
        return msg

    msg += "**計測履歴**\n"
    for m in measurements[-limit:]:
        line = f"{m['date']}: {m['wpm']} WPM / acc {m['accuracy']}% / "
        line += f"cons {m['consistency']}% / afk {m['afk']}%"
        if m.get('note'):
            line += f" — {m['note']}"
        msg += line + "\n"

    target_week, target = get_current_target(today)
    msg += f"\n**{target_week}週後の目標**: {target['wpm']} WPM / acc {target['accuracy']}% / "
    msg += f"consistency {target['consistency']}% / afk {target['afk']}%以下"

    return msg


def get_key_guide(layout="jis"):
    """記号の指の担当表を返します。"""
    layout = (layout or "jis").lower()
    guide = KEY_GUIDES.get(layout)
    if not guide:
        return "配列は jis / us のいずれかを指定してください。"

    label = "JIS配列（日本語配列）" if layout == "jis" else "US配列（英語配列）"
    msg = f"⌨️ **【記号の指の担当表】{label}**\n"
    msg += "⚠️ シフトは必ず**反対の手**で押すこと。右シフトを使うと右小指が2役になり崩壊します。\n\n"
    for symbol, how, finger in guide:
        msg += f"`{symbol}` … {how} → {finger}\n"
    return msg


def get_weekly_typing_summary(today=None):
    """週間サマリーに追記するタイピング訓練の文言を返します。

    Returns:
        str: 追記する文言（計測記録が無ければ促しの一文）。
    """
    today = today or datetime.now(JST).date()
    data = load_typing_data()
    measurements = data.get('measurements', [])
    current = data.get('current_drill', 'A')

    if not measurements:
        return f"\n⌨️ タイピング訓練: Drill {current} 進行中（計測はまだ未実施）"

    latest = measurements[-1]
    line = f"\n⌨️ タイピング訓練: Drill {current} 進行中"
    line += f"／最新計測 {latest['wpm']} WPM（acc {latest['accuracy']}%）"

    days = days_since_last_measurement(today)
    if days is not None and days >= MEASUREMENT_INTERVAL_DAYS:
        line += f"\n　🎯 前回の計測から{days}日経過。今週の計測をしましょう。"

    return line
