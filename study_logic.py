import os
import json
import random
import math

# プレイヤーのゲームデータを永続化するためのJSONファイル名
PLAYER_DATA_FILE = 'player_data.json'

# 【ボスバトルの定義】
# 累積の「作業時間（分）」に応じて出現する課題ボスのリスト
BOSS_LIST = [
    {"threshold": 120, "name": "職務経歴書の壁", "hp": 30},       # 累計2時間作業で出現
    {"threshold": 300, "name": "魔のコーディングテスト", "hp": 60}, # 累計5時間
    {"threshold": 600, "name": "圧迫面接の幻影", "hp": 120},       # 累計10時間
    {"threshold": 1200, "name": "内定を阻む最終関門", "hp": 300},  # 累計20時間
]


# ==========================================
# 1. クイズ・用語集関連のロジック
# ==========================================

def get_kiso_quiz():
    """
    JSONファイルからランダムに試験用語を1つ抽出し、クイズ形式で返す関数。
    解答（解説）部分はDiscordのネタバレ防止仕様（||で囲む）にして出力します。
    
    Returns:
        str: 用語と、隠された解説文のメッセージ
    """
    if not os.path.exists('glossary.json'):
        return "用語データが見つかりません。"
    
    with open('glossary.json', 'r', encoding='utf-8') as f:
        glossary = json.load(f)
    
    if not glossary:
        return "用語が登録されていません。"

    # random.choiceを使って要素を等確率で1つ選択
    qa = random.choice(glossary)
    return f"**【試験用語】**\n用語: **{qa['term']}**\n解説: ||{qa['desc']}||"

def get_math_quiz():
    """
    基本情報・ITパスポートで必須となる「基数変換（2進数、10進数、16進数）」のクイズを動的に生成する関数。
    問題タイプ（4モード）をランダムに決定し、format関数を用いて自動変換して出題します。
    
    Returns:
        str: 計算問題と、隠された正解のメッセージ
    """
    # 1〜255の間でランダムな数値を1つ生成（8ビットで表現できる範囲）
    target_num = random.randint(1, 255)
    # 出題モードをランダムに決定（0:10→2, 1:2→10, 2:2→16, 3:16→2)
    mode = random.randint(0, 3)
    
    if mode == 0:
        return f"10進数「{target_num}」を 2進数(8bit) に直すと？\n答え: || {format(target_num, '08b')} ||"
    elif mode == 1:
        return f"2進数「{format(target_num, '08b')}」を 10進数 に直すと？\n答え: || {target_num} ||"
    elif mode == 2:
        return f"2進数「{format(target_num, '08b')}」を 16進数 に直すと？\n答え: || {format(target_num, '02X')} ||"
    else:
        return f"16進数「{format(target_num, '02X')}」を 2進数(8bit) に直すと？\n答え: || {format(target_num, '08b')} ||"

def add_kiso(term, desc):
    """
    モーダルフォームから送られてきた新しい用語名と説明文を用語集（JSON）に追記・保存する関数。
    
    Args:
        term (str): 登録する用語名
        desc (str): 用語の解説文
    Returns:
        str: 登録結果のメッセージ
    """
    if not term or not desc:
        return "用語と説明を両方入力してください。"

    # ⭕ 修正ポイント1：初期化をリスト `[]` から辞書 `{}` に変更
    glossary = {}
    if os.path.exists('glossary.json'):
        with open('glossary.json', 'r', encoding='utf-8') as f:
            glossary = json.load(f)

    # 💡 応用ポイント：すでに登録済みの単語なら上書き（または警告）できるようにチェック
    if term in glossary:
        # 上書きしたくない場合はここで return "既に登録されています。" にしてもOK
        pass 

    # ⭕ 修正ポイント2：append ではなく、辞書型への代入（キーと値）に変更
    # term（例: "RAG"）をキーにして、desc（説明文）を保存します
    glossary[term] = desc

    with open('glossary.json', 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=4)

    return f"✅ 用語「{term}」を登録しました！"

def search_glossary(word):
    """
    ユーザーが入力したキーワードで用語集（JSON）を部分一致検索する関数。
    """
    if not word:
        return "検索するキーワードを入力してください。"

    if not os.path.exists('glossary.json'):
        return "用語集がまだ作成されていません。"

    with open('glossary.json', 'r', encoding='utf-8') as f:
        glossary = json.load(f)

    # ⭕ 修正ポイント：辞書型に対応した部分一致検索（大文字小文字を区別しない）
    matched = []
    for term, desc in glossary.items():
        if word.lower() in term.lower():
            matched.append(f"• **{term}**: {desc}")

    if not matched:
        return f"🔍 「{word}」に一致する用語は見つかりませんでした。"

    # 見つかった結果を改行で繋げて返す
    return "🔍 **検索結果:**\n" + "\n".join(matched)


# ==========================================
# 2. RPG・ステータス管理関連のロジック
# ==========================================

def load_player_data():
    if os.path.exists(PLAYER_DATA_FILE):
        with open(PLAYER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 【変更！】汎用作業ライフログ用の初期構造
    return {
        "level": 1, 
        "exp": 0, 
        "total_minutes": 0,       # 累計の作業時間（分）
        "programming": 0,         # 開発の累計作業時間（分）
        "document": 0,            # 書類の累計作業時間（分）
        "reading": 0              # インプットの累計作業時間（分）
    }

def save_player_data(data):
    """
    引数で受け取ったプレイヤーのステータスデータをJSONファイルへ上書き保存する関数。
    
    Args:
        data (dict): 更新されたプレイヤーデータの辞書
    """
    with open(PLAYER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_exp(category, minutes=25):
    """
    指定されたカテゴリと作業時間（分）をプレイヤーデータに加算し、
    ボス戦の発生、ダメージ計算、撃破判定、レベルアップ判定を統合して実行する関数。
    """
    data = load_player_data()
    
    # 1分につき10 EXP獲得とする
    earned_exp = minutes * 10
    
    # 1. 基礎データの更新
    data['total_minutes'] = data.get('total_minutes', 0) + minutes
    if category in data:
        data[category] += minutes # カテゴリごとの累積時間を増やす
    data['exp'] += earned_exp      # 全体経験値を増やす

    event_type = None
    
    # 2. ボス戦ロジック（問題数をそのまま「累積時間（分）」に置き換えるわ！）
    if not data.get("is_boss_active"):
        data['minutes_since_last_boss'] = data.get('minutes_since_last_boss', 0) + minutes
        # 例: 100分作業するたび、または特定の累積時間（threshold）でボス出現
        boss = check_boss_appearance(data)
        if boss:
            event_type = "BOSS_APPEAR"
    else:
        # ボスへのダメージ（1分集中するごとにボスHPを1減算）
        data["boss_hp"] -= minutes  
        if data["boss_hp"] <= 0:
            data["boss_hp"] = 0
            data["is_boss_active"] = False
            data["current_boss_idx"] = data.get("current_boss_idx", 0) + 1
            data['exp'] += 200  # 撃破ボーナスEXP
            event_type = "BOSS_DEFEATED"
        else:
            event_type = "BOSS_DAMAGE"

    # 3. レベルアップ判定
    is_eligible, diffs, next_lv = check_level_up(data)
    if is_eligible:
        data['level'] = next_lv

    save_player_data(data)

    if is_eligible:
        return True, next_lv, event_type
    else:
        return False, diffs, event_type

def report_study(category, minutes):
    """
    UI（Modalやタイマー）から送られた「作業時間（分）」を反映するためのラッパー。
    """
    # 直接分数を渡して、add_exp側で1分=10EXPの計算を行う
    is_up, new_lv, event = add_exp(category, minutes)
    
    total_earned = minutes * 10  # メッセージ表示用に獲得EXPを計算
    return is_up, new_lv, total_earned, event

def check_level_up(data):
    """
    【プランA】全体経験値のみでシンプルにレベルアップを判定する関数。
    個別カテゴリのノルマ縛りを無くし、純粋な努力の積み重ねで昇格します。
    """
    current_lv = data.get('level', 1)
    next_lv = current_lv + 1
    
    # 全体で必要な累計経験値の計算（美しい2次関数ロジックを継承！）
    required_total = ((next_lv - 1) ** 2) * 100
    
    diffs = {}
    is_eligible = True
    
    current_total_exp = data.get('exp', 0)
    if current_total_exp < required_total:
        is_eligible = False
        diffs['total_exp'] = required_total - current_total_exp
            
    return is_eligible, diffs, next_lv


def get_status_summary():
    """
    新しい3つのスキル（開発・書類・インプット）の累積時間と、
    全体経験値のプログレスバー、現在のボス状況を美しく整形して返す関数。
    """
    data = load_player_data()
    current_exp = data.get('exp', 0)
    level = data.get('level', 1)
    next_level = level + 1
    
    # 必要経験値の計算
    exp_for_current_level = ((level - 1) ** 2) * 100
    exp_for_next_level = ((next_level - 1) ** 2) * 100
    
    # 現在のレベル内での進捗率・テキスト進捗バーの計算
    exp_in_level = max(0, current_exp - exp_for_current_level)
    needed_in_level = exp_for_next_level - exp_for_current_level
    progress_percent = min(1.0, exp_in_level / needed_in_level) if needed_in_level > 0 else 1.0
    
    bar_length = 10
    filled_length = int(bar_length * progress_percent)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    # タイトル（称号）の取得
    title = get_title(data)

    # 3. メッセージの組み立て開始
    msg = f"🏆 **総合プレイヤーランク: Lv.{level}**\n"
    msg += f"称号: **{title}**\n"
    msg += f"次のレベルまで: `{bar}` {int(progress_percent * 100)}%\n\n"
    
    # 4. ボスバトルの状況（問題数から「累積作業時間」の判定に変更）
    current_idx = data.get('current_boss_idx', 0)
    if current_idx < len(BOSS_LIST):
        boss = BOSS_LIST[current_idx]
        if data.get('total_minutes', 0) >= boss['threshold']:
            # ボス戦アクティブ状態
            hp = data.get('boss_hp', boss['hp'])
            max_hp = boss['hp']
            # 安全なHPバー計算（0除算防止）
            hp_ratio = max(0.0, min(1.0, hp / max_hp)) if max_hp > 0 else 0
            hp_bar = '🟥' * int(10 * hp_ratio) + '⬜' * (10 - int(10 * hp_ratio))
            msg += f"⚠️ **BOSS BATTLE: {boss['name']}**\n"
            msg += f"HP: `{hp_bar}` {hp} / {max_hp}\n\n"
        else:
            # 次のボス出現までの残り時間（分）
            next_target = boss['threshold'] - data.get('total_minutes', 0)
            msg += f"👾 次の強敵（課題）出現まで: あと {next_target} 分の集中\n\n"

    # 【変更箇所】5. 詳細数値の追加（時間をすべてヘルパー関数で変換！）
    msg += f"📊 **現在の詳細ステータス:**\n"
    msg += f"⏳ 総合集中時間: {format_minutes_to_hours(data.get('total_minutes', 0))}\n"
    msg += f"✨ 総合獲得経験値: {current_exp} EXP\n\n"
    msg += f"💻 開発（Programming）: {format_minutes_to_hours(data.get('programming', 0))}\n"
    msg += f"📝 書類・面接（Document）: {format_minutes_to_hours(data.get('document', 0))}\n"
    msg += f"📚 インプット（Reading）: {format_minutes_to_hours(data.get('reading', 0))}"
    
    return msg


def get_title(data):
    """
    新しい3カテゴリの作業時間や総合レベルに応じて、
    就活・開発状況にぴったりな格好いい称号を動的に決定します。
    """
    prog = data.get('programming', 0)
    doc = data.get('document', 0)
    read = data.get('reading', 0)
    level = data.get('level', 1)

    # 1. 最上位称号（バランスよく極めたマスター）
    if prog >= 500 and doc >= 200 and read >= 200:
        return "🏆 フルスタック・就活マスター"
    
    # 2. 各分野特化型の称号判定（分単位の基準ね）
    if prog >= 300:
        return "💻 凄腕インフラ/開発エンジニア"
    if doc >= 150:
        return "📄 自己分析・面接の達人"
    if read >= 150:
        return "📚 技術トレンドの御意見番"

    # 3. 到達レベルベースの称号判定
    if level >= 10:
        return "⚔️ 歴戦の努力家"
    if level >= 5:
        return "🛡️ 実力派プログラマー"
    
    return "🐣 覚醒を待つギーク"

def check_boss_appearance(data):
    """
    現在の累計回答数がボスの出現閾値に達しているかをチェックし、出現させるかを判定する関数。
    
    Args:
        data (dict): プレイヤーのステータスデータ
    Returns:
        dict/None: 出現したボスのデータ（出現しない場合はNone）
    """
    current_boss_idx = data.get('current_boss_idx', 0)
    
    # まだ倒していないボスがリストに残っているかチェック
    if current_boss_idx < len(BOSS_LIST):
        next_boss = BOSS_LIST[current_boss_idx]
        # 累計回答数が、現在のボスの出現条件（threshold）を満たしたか判定
        if data.get('total_solved', 0) >= next_boss["threshold"]:
            if not data.get("is_boss_active"):
                # ボス戦情報をアクティブにセット
                data["boss_hp"] = next_boss["hp"]
                data["is_boss_active"] = True
                data["solved_since_last_boss"] = 0  # 周期判定用の回答数をリセット
                return next_boss
    return None

def format_minutes_to_hours(total_minutes):
    """
    分単位の数値を「〇時間〇分」または「〇分」の読みやすい形式に変換するヘルパー関数
    """
    if total_minutes < 60:
        return f"{total_minutes}分"
    
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    if minutes == 0:
        return f"{hours}時間"
    else:
        return f"{hours}時間{minutes}分"