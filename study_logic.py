"""就活攻略RPGゲームロジックモジュール

ユーザーの作業時間（ライフログ）を経験値（EXP）に換算し、レベルアップ、
スキル称号の動的決定、および累積時間に応じた課題ボスバトル等のゲーム要素を制御します。
ストックした用語からの試験用語クイズなどの学習支援ロジックも統合しています。
"""

import json
import os
import random
from datetime import datetime, timedelta, timezone

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
PLAYER_DATA_FILE = os.path.join('data', 'player_data.json')
GLOSSARY_FILE = os.path.join('data', 'glossary.json')

JST = timezone(timedelta(hours=9))

# ゲームバランス調整用定数
EXP_PER_MINUTE = 10         # 1分間の作業で獲得できる基礎経験値
BOSS_DEFEAT_BONUS = 200    # ボス撃破時に獲得できるボーナス経験値
EXP_BASE_UNIT = 100         # レベルアップ必要経験値の算出基準値

# 【ボスバトルの定義】
# 累積の「作業時間（分）」に応じて出現する課題ボスのリスト
BOSS_LIST = [
    {"threshold": 120, "name": "職務経歴書の壁", "hp": 30},        # 累計2時間作業で出現
    {"threshold": 300, "name": "魔のコーディングテスト", "hp": 60},  # 累計5時間作業で出現
    {"threshold": 600, "name": "圧迫面接の幻影", "hp": 120},       # 累計10時間作業で出現
    {"threshold": 1200, "name": "内定を阻む最終関門", "hp": 300},   # 累計20時間作業で出現
]

# 【連続記録ボーナスの定義】
# 連続で作業報告をした日数(streak)に応じたEXPボーナス倍率。閾値の大きい順に並べ、
# 最初に条件を満たしたものを採用する
STREAK_BONUS_TIERS = [
    (30, 0.5),
    (14, 0.3),
    (7, 0.2),
    (3, 0.1),
]
# ⭕ 節目に達した「その日」だけ公開告知するための一覧（毎日告知すると煩雑になるため）
STREAK_MILESTONES = [threshold for threshold, _ in STREAK_BONUS_TIERS]

# 【実績バッジの定義】
# 一度条件を満たすと、その後条件を満たさなくなっても記録として残り続ける
BADGE_DEFINITIONS = [
    {"id": "first_boss", "name": "🗡️ 初撃破の証", "condition": lambda d: d.get('current_boss_idx', 0) >= 1},
    {"id": "boss_slayer", "name": "⚔️ ボスハンター", "condition": lambda d: d.get('current_boss_idx', 0) >= len(BOSS_LIST)},
    {"id": "level_5", "name": "🛡️ 実力派の証", "condition": lambda d: d.get('level', 1) >= 5},
    {"id": "level_10", "name": "👑 歴戦の勇者", "condition": lambda d: d.get('level', 1) >= 10},
    {"id": "10_hours", "name": "⏳ 継続の証（10時間）", "condition": lambda d: d.get('total_minutes', 0) >= 600},
    {"id": "100_hours", "name": "💯 継続王（100時間）", "condition": lambda d: d.get('total_minutes', 0) >= 6000},
    {"id": "streak_7", "name": "🔥 週間皆勤賞", "condition": lambda d: d.get('current_streak', 0) >= 7},
    {"id": "streak_30", "name": "🌟 月間皆勤賞", "condition": lambda d: d.get('current_streak', 0) >= 30},
    {
        "id": "balanced_master",
        "name": "🏆 全方位マスター",
        "condition": lambda d: d.get('programming', 0) >= 500 and d.get('document', 0) >= 200 and d.get('reading', 0) >= 200,
    },
]


# ====================================================
# 1. クイズ・用語集関連のロジック
# ====================================================

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


def get_kiso_quiz():
    """登録されている試験用語集からランダムに1問を抽出し、クイズ形式で取得します。

    解答（解説）部分は、Discord 内でのネタバレ防止（スポイラー表示）に対応するため、
    「||」で囲った文字列として出力されます。

    Returns:
        str: クイズ文、またはデータ未登録の旨を伝えるシステムメッセージ。
    """
    glossary = _load_json(GLOSSARY_FILE, {})
    if not glossary:
        return "用語が登録されていません。先にメニューから用語をストックしてください。"

    # 辞書型構造からランダムに要素を1つ選択
    terms = list(glossary.keys())
    chosen_term = random.choice(terms)
    chosen_desc = glossary[chosen_term]

    return f"**【試験用語クイズ】**\n用語: **{chosen_term}**\n解説: ||{chosen_desc}||"


def add_kiso(term, desc):
    """新規のIT用語とその解説文を、用語集ファイル（glossary.json）に登録・永続化します。

    Args:
        term (str): 登録対象の用語名。
        desc (str): 用語の解説・メモ内容。

    Returns:
        str: 登録処理結果を通知するチャット用メッセージ。
    """
    if not term or not desc:
        return "用語と説明を両方入力してください。"

    glossary = _load_json(GLOSSARY_FILE, {})
    # 用語をキー、解説文を値として辞書に代入（既存の用語は上書き更新）
    glossary[term] = desc

    try:
        os.makedirs(os.path.dirname(GLOSSARY_FILE), exist_ok=True)
        with open(GLOSSARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(glossary, f, ensure_ascii=False, indent=4)
        return f"✅ 用語「{term}」を登録しました！"
    except IOError as e:
        print(f"⚠️ [ERROR] 用語集の保存に失敗しました: {e}")
        return "❌ 用語の保存処理中にエラーが発生しました。"


def search_glossary(word):
    """ユーザー指定のキーワードに基づき、用語集ファイルから部分一致による検索を実行します。

    Args:
        word (str): 検索用キーワード。

    Returns:
        str: 該当した用語の一覧メッセージ、またはヒットなしの通知メッセージ。
    """
    if not word:
        return "検索するキーワードを入力してください。"

    glossary = _load_json(GLOSSARY_FILE, {})
    if not glossary:
        return "用語集がまだ作成されていません。"

    matched = []
    for term, desc in glossary.items():
        # 大文字小文字を区別せずに部分一致検索
        if word.lower() in term.lower():
            matched.append(f"• **{term}**: {desc}")

    if not matched:
        return f"🔍 「{word}」に一致する用語は見つかりませんでした。"

    return "🔍 **検索結果:**\n" + "\n".join(matched)


def get_glossary_list():
    """現在蓄積されているすべてのストック用語のキー（用語名）一覧を取得します。

    Returns:
        str: 箇条書き形式で整形された登録用語一覧のメッセージ。
    """
    glossary = _load_json(GLOSSARY_FILE, {})
    if not glossary:
        return "現在、ストックされている用語はありません。"

    list_msg = "📚 **現在のストック用語一覧:**\n"
    for term in glossary.keys():
        list_msg += f"• {term}\n"
        
    return list_msg


# ====================================================
# 2. RPG・ステータス管理関連のロジック
# ====================================================

def load_player_data():
    """プレイヤーのゲームステータスデータをファイルから読み込みます。

    ファイルが存在しない場合は、標準の初期ステータス構造体を生成して返します。

    Returns:
        dict: プレイヤーの各ステータス値を格納した辞書。
    """
    return _load_json(PLAYER_DATA_FILE, {
        "level": 1,
        "exp": 0,
        "total_minutes": 0,       # 総合累積作業時間（分）
        "programming": 0,         # 開発の累積作業時間（分）
        "document": 0,            # 書類作成の累積作業時間（分）
        "reading": 0,             # インプットの累積作業時間（分）
        "is_boss_active": False,
        "current_boss_idx": 0,
        "boss_hp": 0,
        "minutes_since_last_boss": 0,
        "last_active_date": None,  # 直近で作業報告があった日付（YYYY-MM-DD、JST基準）
        "current_streak": 0,       # 連続で作業報告した日数
        "badges": [],              # 獲得済み実績バッジのID一覧
    })


def save_player_data(data):
    """プレイヤーのゲームステータスデータをファイルへ上書き保存します。

    Args:
        data (dict): 更新されたプレイヤーデータの辞書。
    """
    try:
        os.makedirs(os.path.dirname(PLAYER_DATA_FILE), exist_ok=True)
        with open(PLAYER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] プレイヤーデータの保存に失敗しました: {e}")


def _update_streak(data):
    """今日の活動によって連続記録(streak)を更新します。

    前回の活動日が「今日」ならカウント済みなので変更なし、「昨日」なら+1、
    それ以外（初回・間が空いた）なら1にリセットします。

    Returns:
        int: 更新後の連続日数。
    """
    today_str = datetime.now(JST).strftime('%Y-%m-%d')
    yesterday_str = (datetime.now(JST) - timedelta(days=1)).strftime('%Y-%m-%d')
    last_active = data.get('last_active_date')

    if last_active == today_str:
        pass  # 今日は既にカウント済み
    elif last_active == yesterday_str:
        data['current_streak'] = data.get('current_streak', 0) + 1
    else:
        data['current_streak'] = 1

    data['last_active_date'] = today_str
    return data['current_streak']


def _streak_bonus_rate(streak):
    """連続記録の日数から、EXPボーナス倍率（例: 0.1 = +10%）を返します。"""
    for threshold, bonus in STREAK_BONUS_TIERS:
        if streak >= threshold:
            return bonus
    return 0.0


def check_new_badges(data):
    """未取得の実績バッジのうち、現在のステータスで新たに条件を満たしたものを判定・記録します。

    Returns:
        list: 今回新しく獲得したバッジ定義（{"id": ..., "name": ...}）のリスト。
    """
    earned_ids = set(data.get('badges', []))
    newly_earned = []
    for badge in BADGE_DEFINITIONS:
        if badge['id'] not in earned_ids and badge['condition'](data):
            earned_ids.add(badge['id'])
            newly_earned.append(badge)
    data['badges'] = sorted(earned_ids)
    return newly_earned


def add_exp(category, minutes=25):
    """作業実績（分数）を基に各種ステータスを更新し、レベルアップ・ボス戦・連続記録ボーナス・
    実績バッジの判定を一元的に実行します。

    Args:
        category (str): 作業を行った該当カテゴリ（'programming', 'document', 'reading'）。
        minutes (int): 実績時間（分）。デフォルトは25分。

    Returns:
        dict: {
            "is_level_up": bool,
            "new_level": int/None（レベルアップ時のみ）,
            "event": str/None（'BOSS_APPEAR', 'BOSS_DAMAGE', 'BOSS_DEFEATED' のいずれか）,
            "earned_exp": int（ボーナス適用後の実際の獲得EXP）,
            "streak": int（更新後の連続記録日数）,
            "new_badges": list（今回新しく獲得したバッジ定義のリスト）,
        }
    """
    data = load_player_data()

    streak = _update_streak(data)
    bonus_rate = _streak_bonus_rate(streak)
    earned_exp = int(minutes * EXP_PER_MINUTE * (1 + bonus_rate))

    # 1. 基礎ステータス値の更新
    data['total_minutes'] = data.get('total_minutes', 0) + minutes
    if category in data:
        data[category] += minutes
    data['exp'] = data.get('exp', 0) + earned_exp

    event_type = None

    # 2. ボスバトルエンカウント・交戦ロジック
    if not data.get("is_boss_active"):
        data['minutes_since_last_boss'] = data.get('minutes_since_last_boss', 0) + minutes
        boss = check_boss_appearance(data)
        if boss:
            event_type = "BOSS_APPEAR"
    else:
        # ボス交戦中：1分間の作業につきボスへ 1 ダメージ
        data["boss_hp"] -= minutes
        if data["boss_hp"] <= 0:
            data["boss_hp"] = 0
            data["is_boss_active"] = False
            data["current_boss_idx"] = data.get("current_boss_idx", 0) + 1
            data['exp'] = data.get('exp', 0) + BOSS_DEFEAT_BONUS  # 撃破ボーナス付与
            event_type = "BOSS_DEFEATED"
        else:
            event_type = "BOSS_DAMAGE"

    # 3. レベルアップの自動判定
    is_eligible, diffs, next_lv = check_level_up(data)
    if is_eligible:
        data['level'] = next_lv

    # 4. 実績バッジの判定（レベル・ボス・連続記録が全て確定した後に行う）
    new_badges = check_new_badges(data)

    save_player_data(data)

    return {
        "is_level_up": is_eligible,
        "new_level": next_lv if is_eligible else None,
        "event": event_type,
        "earned_exp": earned_exp,
        "streak": streak,
        "new_badges": new_badges,
    }


def check_level_up(data):
    """累積獲得経験値を基に、次レベルへの昇格条件を満たしているかを判定します。

    必要累計経験値は、2次関数ロジック（(レベル-1)^2 * 100）に基づいて算出されます。

    Args:
        data (dict): プレイヤーのステータスデータ。

    Returns:
        tuple: (
            is_eligible (bool): 昇格要件を満たしているか否か,
            diffs (dict): 不足している経験値情報を格納した辞書,
            next_lv (int): 条件を満たした場合の移行先レベル番号
        )
    """
    current_lv = data.get('level', 1)
    next_lv = current_lv + 1
    
    # 次のレベル到達に必要な累計経験値の計算
    required_total = ((next_lv - 1) ** 2) * EXP_BASE_UNIT
    
    diffs = {}
    is_eligible = True
    
    current_total_exp = data.get('exp', 0)
    if current_total_exp < required_total:
        is_eligible = False
        diffs['total_exp'] = required_total - current_total_exp
            
    return is_eligible, diffs, next_lv


def get_status_summary():
    """現在の全スキル累積時間、経験値進捗、および交戦中のボスHP状況を視覚的に整形して取得します。

    Returns:
        str: Discord埋め込み表示用に完全に整形されたステータスサマリー。
    """
    data = load_player_data()
    current_exp = data.get('exp', 0)
    level = data.get('level', 1)
    next_level = level + 1
    
    # レベル内の経験値進捗算出
    exp_for_current_level = ((level - 1) ** 2) * EXP_BASE_UNIT
    exp_for_next_level = ((next_level - 1) ** 2) * EXP_BASE_UNIT
    
    exp_in_level = max(0, current_exp - exp_for_current_level)
    needed_in_level = exp_for_next_level - exp_for_current_level
    progress_percent = min(1.0, exp_in_level / needed_in_level) if needed_in_level > 0 else 1.0
    
    # 進捗バー（視覚表現）の生成
    bar_length = 10
    filled_length = int(bar_length * progress_percent)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    title = get_title(data)

    msg = f"🏆 **総合プレイヤーランク: Lv.{level}**\n"
    msg += f"称号: **{title}**\n"
    msg += f"次のレベルまで: `{bar}` {int(progress_percent * 100)}%\n\n"
    
    # ボスバトルエンカウント状況の取得
    current_idx = data.get('current_boss_idx', 0)
    if current_idx < len(BOSS_LIST):
        boss = BOSS_LIST[current_idx]
        if data.get('total_minutes', 0) >= boss['threshold']:
            hp = data.get('boss_hp', boss['hp'])
            max_hp = boss['hp']
            
            hp_ratio = max(0.0, min(1.0, hp / max_hp)) if max_hp > 0 else 0
            hp_bar = '🟥' * int(10 * hp_ratio) + '⬜' * (10 - int(10 * hp_ratio))
            msg += f"⚠️ **BOSS BATTLE: {boss['name']}**\n"
            msg += f"HP: `{hp_bar}` {hp} / {max_hp}\n\n"
        else:
            next_target = boss['threshold'] - data.get('total_minutes', 0)
            msg += f"👾 次の強敵（課題）出現まで: あと {next_target} 分の集中\n\n"

    # 詳細ステータステキストの組み立て
    msg += "📊 **現在の詳細ステータス:**\n"
    msg += f"⏳ 総合集中時間: {format_minutes_to_hours(data.get('total_minutes', 0))}\n"
    msg += f"✨ 総合獲得経験値: {current_exp} EXP\n\n"
    msg += f"💻 開発（Programming）: {format_minutes_to_hours(data.get('programming', 0))}\n"
    msg += f"📝 書類・面接（Document）: {format_minutes_to_hours(data.get('document', 0))}\n"
    msg += f"📚 インプット（Reading）: {format_minutes_to_hours(data.get('reading', 0))}\n\n"

    # 連続記録の表示
    streak = data.get('current_streak', 0)
    bonus_rate = _streak_bonus_rate(streak)
    msg += f"🔥 連続記録: {streak}日"
    if bonus_rate > 0:
        msg += f"（EXPボーナス +{int(bonus_rate * 100)}%）"
    msg += "\n"

    # 獲得済みバッジの表示
    earned_ids = set(data.get('badges', []))
    if earned_ids:
        badge_names = [b['name'] for b in BADGE_DEFINITIONS if b['id'] in earned_ids]
        msg += f"🏅 獲得バッジ: {', '.join(badge_names)}"
    else:
        msg += "🏅 獲得バッジ: まだありません"

    return msg


def get_title(data):
    """各カテゴリの累積作業時間およびプレイヤーレベルに基づき、現在の称号を動的に判定します。

    Args:
        data (dict): プレイヤーのステータスデータ。

    Returns:
        str: 決定された称号名。
    """
    prog = data.get('programming', 0)
    doc = data.get('document', 0)
    read = data.get('reading', 0)
    level = data.get('level', 1)

    # バランス特化最上位称号
    if prog >= 500 and doc >= 200 and read >= 200:
        return "🏆 フルスタック・就活マスター"
    
    # 各専門特化型称号
    if prog >= 300:
        return "💻 凄腕インフラ/開発エンジニア"
    if doc >= 150:
        return "📄 自己分析・面接の達人"
    if read >= 150:
        return "📚 技術トレンドの御意見番"

    # レベル依存ベース称号
    if level >= 10:
        return "⚔️ 歴戦の努力家"
    if level >= 5:
        return "🛡️ 実力派プログラマー"
    
    return "🐣 覚醒を待つギーク"


def check_boss_appearance(data):
    """現在の累積作業時間（分）が次なるボスの出現閾値（threshold）を超えているかを判定します。

    条件を満たしている場合、対象ボスのHP情報をプレイヤーデータ内にアクティブ化します。

    Args:
        data (dict): プレイヤーのステータスデータ。

    Returns:
        dict/None: 出現したボスのデータオブジェクト。出現要件を満たさない場合は None。
    """
    current_boss_idx = data.get('current_boss_idx', 0)
    
    if current_boss_idx < len(BOSS_LIST):
        next_boss = BOSS_LIST[current_boss_idx]
        
        if data.get('total_minutes', 0) >= next_boss["threshold"]:
            if not data.get("is_boss_active"):
                data["boss_hp"] = next_boss["hp"]
                data["is_boss_active"] = True
                data["minutes_since_last_boss"] = 0  # 周期判定用の累積カウントを初期化
                return next_boss
    return None


def format_minutes_to_hours(total_minutes):
    """分単位の整数値を、可読性の高い「〇時間〇分」または「〇分」の表記文字列に変換します。

    Args:
        total_minutes (int): 変換対象の分数。

    Returns:
        str: 整形済みの時間表現文字列。
    """
    if total_minutes < 60:
        return f"{total_minutes}分"
    
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    if minutes == 0:
        return f"{hours}時間"
    else:
        return f"{hours}時間{minutes}分"