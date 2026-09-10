"""複数のui_*.pyモジュールから共有される、Discord応答まわりの共通ヘルパー

main.pyが1,300行を超え機能追加のたびに肥大化していたため、機能別のui_*.pyへ
分割した。このファイルにはどのドメイン（task/horse/exam/...）にも属さない、
横断的に使われる関数だけを置く。
"""

import asyncio

import calendar_logic
import horse_logic
import task_logic
from bot_state import TASK_COMPLETE_MINUTES, EXAM_MINUTES_PER_QUESTION


def parse_positive_int(text):
    """モーダルの入力文字列を整数に変換します。全角数字も受け付けます。

    str.isdigit()は「²」のような文字にもTrueを返す一方でint()は失敗するため、
    判定に頼らず実際にint()を試して例外を捕まえる方式にしています。

    Returns:
        int/None: 変換できた整数。数値として解釈できない場合はNone。
    """
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


def parse_float(text):
    """モーダルの入力文字列を小数に変換します（afk% のように小数を取りうる項目用）。

    Returns:
        float/None: 変換できた小数。数値として解釈できない場合はNone。
    """
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


# 公開告知する連続記録の節目。毎日告知すると煩雑になるため、ここに達した日だけ。
STREAK_MILESTONES = (3, 7, 14, 30, 60, 100)


def build_growth_message(result):
    """horse_logic.add_growth() の返り値から、成長のイベント文言を組み立てます。

    どの能力がいくつ上がったかは毎回起きる細かい進捗なので本人向けだけに出し、
    昇級・引退・連続記録の節目・能力の上限到達といった「節目」を公開告知にします。

    Returns:
        tuple: (detail_msg: 本人向けの詳細文言, public_msg: 公開告知文言 または None)
    """
    detail_msg = ""
    announcements = []

    gains = result.get("gains") or {}
    if gains:
        parts = [f"{horse_logic.PARAM_NAMES.get(k, k)} +{v}" for k, v in gains.items()]
        detail_msg += "\n📈 " + " ／ ".join(parts)

    if result.get("capped"):
        capped_msg = "🔝 能力が上限に達しました。以降のぶんは引退後の種牡馬価値に回ります。"
        detail_msg += f"\n{capped_msg}"
        announcements.append(capped_msg)

    streak = result.get("streak", 0)
    if streak in STREAK_MILESTONES:
        streak_msg = f"🔥 {streak}日連続で調教できています！"
        detail_msg += f"\n{streak_msg}"
        announcements.append(streak_msg)

    for event in result.get("events", []):
        detail_msg += f"\n{event}"
        announcements.append(event)

    public_msg = "\n".join(announcements) if announcements else None
    return detail_msg, public_msg


def process_task_completion(category):
    """タスク完了時に、カテゴリに応じて馬を成長させます。

    Returns:
        tuple: (detail_msg: 本人向けの詳細文言, public_msg: 公開告知文言 または None)
    """
    if not category:
        return "", None

    result = horse_logic.add_growth(category, TASK_COMPLETE_MINUTES)
    cat_name = task_logic.CATEGORY_MAP.get(category, "開発")
    detail_msg = f"\n✨ タスク完了！ 【{cat_name}】{TASK_COMPLETE_MINUTES}分の調教になりました"

    event_detail, public_msg = build_growth_message(result)
    detail_msg += event_detail

    return detail_msg, public_msg


def process_exam_completion(total):
    """過去問演習の記録を、目安時間ぶんの調教（賢さ）に自動で振り替えます。

    ⭕ 演習記録（exam_logic）と育成が独立していると、同じ勉強内容を「📚インプットを報告」で
       二重入力する必要が出る。ここで自動連携させ、演習の記録だけで両方が揃うようにする。

    Returns:
        tuple: (detail_msg: 本人向けの追記文言, public_msg: 公開告知文言 または None)
    """
    minutes = round(total * EXAM_MINUTES_PER_QUESTION)
    if minutes <= 0:
        return "", None

    result = horse_logic.add_growth("reading", minutes)
    detail_msg = f"\n✨ 賢さの調教にもなりました（目安{minutes}分相当）"

    event_detail, public_msg = build_growth_message(result)
    detail_msg += event_detail

    return detail_msg, public_msg


def process_session(kind):
    """筋トレ・タイピングの1セッションを調教として記録します。

    ⭕ この2つは旧RPGでは記録が独立していて、ゲームに繋がっていなかった。時間を
       持たないので回数で換算する（horse_logic の TRAINING_MINUTES / TYPING_MINUTES）。

    Returns:
        tuple: (detail_msg, public_msg)
    """
    result = horse_logic.log_training() if kind == "training" else horse_logic.log_typing()
    return build_growth_message(result)


async def try_sync_to_calendar(task_text, category, deadline_str):
    """期限が指定されていれば、Googleカレンダーにも予定を同期します。

    カレンダー連携が未設定の場合や、期限が指定されていない場合は何もしません。
    Google Calendar APIへの通信は同期処理なので、asyncio.to_threadで別スレッド
    実行し、Bot全体がブロックされないようにしています。

    Returns:
        str: 案内文言（登録できなかった場合は空文字）。
    """
    formatted_deadline = task_logic.parse_deadline(deadline_str)
    if not formatted_deadline:
        return ""

    category_name = task_logic.CATEGORY_MAP.get(category, "開発")
    event_link = await asyncio.to_thread(
        calendar_logic.create_deadline_event, task_text, category_name, formatted_deadline
    )
    return "\n📅 Googleカレンダーにも登録しました。" if event_link else ""
