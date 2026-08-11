"""応用情報技術者試験の演習記録モジュール

過去問演習（過去問道場等）の結果を分野別に記録し、正答率の推移や弱点分野を
可視化します。就活RPG（study_logic.py）のEXP/レベルシステムとは独立して動作します。
"""

import json
import os
from datetime import datetime, timedelta, timezone

EXAM_DATA_FILE = os.path.join('data', 'exam_data.json')
JST = timezone(timedelta(hours=9))

# 【出題分野の定義】応用情報技術者試験のシラバスに沿った分類
# キーが内部保存用のID、値が表示名
EXAM_FIELDS = {
    "basic_theory": "基礎理論（離散数学・アルゴリズム等）",
    "computer_system": "コンピュータシステム（ハードウェア・OS等）",
    "technology": "技術要素（DB・ネットワーク・セキュリティ等）",
    "development": "開発技術（システム開発・ソフトウェア工学）",
    "management": "マネジメント系（プロジェクト・サービス）",
    "strategy": "ストラテジ系（経営戦略・システム戦略）",
}

# 正答率がこの値を下回る分野を「弱点」として強調表示する
WEAK_FIELD_THRESHOLD = 60


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


def load_exam_data():
    """演習記録データをファイルから読み込みます。"""
    return _load_json(EXAM_DATA_FILE, {
        "sessions": [],          # [{"date", "field", "total", "correct"}]
        "weekly_snapshot": {},   # 週間サマリー用の前回時点スナップショット
    })


def save_exam_data(data):
    """演習記録データをファイルへ保存します。"""
    try:
        os.makedirs(os.path.dirname(EXAM_DATA_FILE), exist_ok=True)
        with open(EXAM_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] 演習記録の保存に失敗しました: {e}")


def log_session(field, total, correct, now=None):
    """過去問演習の結果を記録します。

    Args:
        field (str): 分野ID（EXAM_FIELDSのキー）。
        total (int): 解いた問題数。
        correct (int): 正解した問題数。
        now (datetime, optional): 基準日時（テスト用の注入口）。

    Returns:
        str: 記録結果メッセージ。入力が不正な場合はその旨を返す。
    """
    if field not in EXAM_FIELDS:
        return "❌ 不明な分野です。"
    if total <= 0:
        return "❌ 問題数は1以上を指定してください。"
    if correct < 0 or correct > total:
        return f"❌ 正解数は0〜{total}の範囲で指定してください。"

    now = now or datetime.now(JST)
    data = load_exam_data()
    data['sessions'].append({
        "date": now.strftime('%Y-%m-%d'),
        "field": field,
        "total": total,
        "correct": correct,
    })
    save_exam_data(data)

    rate = round(correct / total * 100)
    msg = f"📝 演習を記録しました！\n"
    msg += f"分野: {EXAM_FIELDS[field]}\n"
    msg += f"結果: {correct}/{total}問正解（正答率 {rate}%）\n"

    if rate >= 80:
        msg += "🎉 素晴らしい正答率です！この分野は得意ですね。"
    elif rate >= WEAK_FIELD_THRESHOLD:
        msg += "👍 まずまずです。間違えた問題の復習をしておきましょう。"
    else:
        msg += "💪 伸びしろのある分野です。解説をよく読んで、用語をストックしておきましょう。"

    return msg


def aggregate_by_field(sessions):
    """演習記録を分野別に集計します。

    Args:
        sessions (list[dict]): 演習記録の一覧。

    Returns:
        dict: {分野ID: {"total": 問題数, "correct": 正解数, "rate": 正答率(%)}}
    """
    stats = {}
    for s in sessions:
        field = s.get('field')
        if field not in EXAM_FIELDS:
            continue
        entry = stats.setdefault(field, {"total": 0, "correct": 0})
        entry['total'] += s.get('total', 0)
        entry['correct'] += s.get('correct', 0)

    for entry in stats.values():
        entry['rate'] = round(entry['correct'] / entry['total'] * 100) if entry['total'] else 0

    return stats


def get_stats_summary():
    """分野別の累計成績を整形して返します（弱点分野が一目で分かる形式）。"""
    data = load_exam_data()
    sessions = data.get('sessions', [])
    if not sessions:
        return "まだ演習記録がありません。`/exam log`で過去問の結果を記録してみましょう。"

    stats = aggregate_by_field(sessions)
    total_all = sum(e['total'] for e in stats.values())
    correct_all = sum(e['correct'] for e in stats.values())
    rate_all = round(correct_all / total_all * 100) if total_all else 0

    msg = "📊 **【応用情報 演習成績】**\n"
    msg += f"総演習数: {total_all}問／総合正答率: {rate_all}%\n\n"

    # 正答率の低い順（＝弱点が上）に並べる
    for field, entry in sorted(stats.items(), key=lambda kv: kv[1]['rate']):
        mark = "⚠️ " if entry['rate'] < WEAK_FIELD_THRESHOLD else ""
        bar_filled = int(entry['rate'] / 10)
        bar = '█' * bar_filled + '░' * (10 - bar_filled)
        msg += f"{mark}**{EXAM_FIELDS[field]}**\n"
        msg += f"`{bar}` {entry['rate']}%（{entry['correct']}/{entry['total']}問）\n"

    # まだ一度も手をつけていない分野も可視化する
    untouched = [name for fid, name in EXAM_FIELDS.items() if fid not in stats]
    if untouched:
        msg += f"\n📌 未着手の分野: {', '.join(untouched)}"

    return msg


def get_weekly_exam_summary():
    """前回サマリー時点からの演習量・正答率を算出し、スナップショットを更新します。

    Returns:
        str: 週間サマリーに追記する文言（記録が無い場合は空文字）。
    """
    data = load_exam_data()
    sessions = data.get('sessions', [])
    snapshot = data.get('weekly_snapshot', {})

    total_all = sum(s.get('total', 0) for s in sessions)
    correct_all = sum(s.get('correct', 0) for s in sessions)

    weekly_total = total_all - snapshot.get('total', 0)
    weekly_correct = correct_all - snapshot.get('correct', 0)

    data['weekly_snapshot'] = {"total": total_all, "correct": correct_all}
    save_exam_data(data)

    if weekly_total <= 0:
        return ""

    rate = round(weekly_correct / weekly_total * 100)
    return f"\n📝 今週の過去問演習: {weekly_total}問（正答率 {rate}%）"
