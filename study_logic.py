import os
import json
import random
import math

# プレイヤーのゲームデータを永続化するためのJSONファイル名
PLAYER_DATA_FILE = 'player_data.json'

# 【ボスバトルの定義】
# 基本情報技術者試験やITパスポートの学習進捗（累計回答数）に応じて出現するボスのリスト
BOSS_LIST = [
    {"threshold": 100, "name": "ITパスポートの残影", "hp": 10},
    {"threshold": 300, "name": "令和5年度 過去問の番人", "hp": 60},
    {"threshold": 500, "name": "アルゴリズムの巨像", "hp": 100},
    {"threshold": 1000, "name": "基本情報エンジニアの覇者", "hp": 300},
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

    glossary = []
    if os.path.exists('glossary.json'):
        with open('glossary.json', 'r', encoding='utf-8') as f:
            glossary = json.load(f)

    # 辞書形式で新しいデータを末尾に追加
    glossary.append({"term": term, "desc": desc})

    with open('glossary.json', 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=4)

    return f"✅ 用語「{term}」を登録しました！"

def search_glossary(word):
    """
    登録されている用語集から、指定されたキーワードを部分一致・大文字小文字無視で検索する関数。
    
    Args:
        word (str): 検索したいキーワード
    Returns:
        str: 検索結果一覧（該当がない場合は未検出の案内）
    """
    if not os.path.exists('glossary.json'):
        return "用語データが見つかりません。"
    
    with open('glossary.json', 'r', encoding='utf-8') as f:
        glossary = json.load(f)
    
    # 内包表記を使い、大文字・小文字を区別せず部分一致する用語をリストアップ
    results = [qa for qa in glossary if word.lower() in qa['term'].lower()]
    
    if not results:
        return f"「{word}」に関する用語は見つかりませんでした。"
    
    response = f"🔍 「{word}」の検索結果 ({len(results)}件):\n"
    for qa in results:
        response += f"**【{qa['term']}】**\n{qa['desc']}\n"
    return response


# ==========================================
# 2. RPG・ステータス管理関連のロジック
# ==========================================

def load_player_data():
    """
    JSONファイルからプレイヤーのRPGステータスを読み込む関数。
    ファイルが存在しない場合は、初期状態のステータス（Lv.1）を作成して返します。
    
    Returns:
        dict: プレイヤーの各ステータス値
    """
    if os.path.exists(PLAYER_DATA_FILE):
        with open(PLAYER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 新規開始時の初期値
    return {"level": 1, "exp": 0, "tech": 0, "mgmt": 0, "strat": 0, "bquest": 0}

def save_player_data(data):
    """
    引数で受け取ったプレイヤーのステータスデータをJSONファイルへ上書き保存する関数。
    
    Args:
        data (dict): 更新されたプレイヤーデータの辞書
    """
    with open(PLAYER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_status_summary():
    """
    現在のレベル、次のレベルまでの進捗バー、現在の称号、ボスバトル情報、
    および各分野のステータス数値を美しく整形して返す関数。
    MainMenuViewの「ステータス」ボタンから呼び出されます。
    
    Returns:
        str: 整形されたステータス画面用のテキスト
    """
    data = load_player_data()
    current_exp = data['exp']
    level = data['level']
    next_level = level + 1
    
    # 1. レベルアップに必要な経験値の計算（レベルが上がるごとに必要量が2次関数的に増加）
    exp_for_current_level = ((level - 1) ** 2) * 100
    exp_for_next_level = ((next_level - 1) ** 2) * 100
    
    # 2. 現在のレベル内での進捗率・テキスト進捗バーの計算
    exp_in_level = max(0, current_exp - exp_for_current_level)
    needed_in_level = exp_for_next_level - exp_for_current_level
    progress_percent = min(1.0, exp_in_level / needed_in_level)

    # 称号と、レベルアップのノルマに達しているかの判定を取得
    title = get_title(data)
    is_eligible, diffs, _ = check_level_up(data)

    # 経験値は足りているが個別分野のノルマが足りない場合、バーを99%で止めて可視化
    if not is_eligible and progress_percent >= 1.0:
        progress_percent = 0.99
    
    bar_length = 10
    filled_length = int(bar_length * progress_percent)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    # 3. メッセージの組み立て開始
    msg = f"🏆 **現在のランク: Lv.{level}**\n"
    msg += f"称号: **{title}**\n"
    msg += f"進捗: `{bar}` {int(progress_percent * 100)}%\n\n"
    
    # 4. ボスバトルの状況（ボス戦中か、次の出現まであと何問か）を判定
    current_idx = data.get('current_boss_idx', 0)
    if current_idx < len(BOSS_LIST):
        boss = BOSS_LIST[current_idx]
        if data.get('total_solved', 0) >= boss['threshold']:
            # ボス戦アクティブ状態のHPバー演出
            hp = data.get('boss_hp', boss['hp'])
            max_hp = boss['hp']
            hp_bar = '🟥' * int(10 * (hp/max_hp)) + '⬜' * (10 - int(10 * (hp/max_hp)))
            msg += f"⚠️ **BOSS BATTLE: {boss['name']}**\n"
            msg += f"HP: `{hp_bar}` {hp} / {max_hp}\n\n"
        else:
            # 次のボス出現までの残りカウント
            next_target = boss['threshold'] - data.get('total_solved', 0)
            msg += f"👾 次のボス出現まで: あと {next_target} 問\n\n"

    # 5. レベルアップへの不足ノルマの表示（二段構え判定の可視化）
    if diffs:
        msg += "📝 **レベルアップへの不足分:**\n"
        names = {
            "total_exp": "全体経験値",
            "tech": "テクノロジ",
            "mgmt": "マネジメント",
            "strat": "ストラテジ"
        }
        for cat, val in diffs.items():
            msg += f" ・{names.get(cat, cat)}: あと {val} pt\n"
    else:
        msg += "✨ **ノルマ達成！次のレベルへ昇格可能です**\n"
    
    # 6. 詳細数値の追加
    msg += f"\n📊 **現在の詳細ステータス:**\n"
    msg += f"📚 累計回答数: {data.get('total_solved', 0)} 問\n"
    msg += f" ・累計経験値: {current_exp} EXP\n"
    msg += f" ・テクノロジ: {data['tech']} pt\n"
    msg += f" ・マネジメント: {data['mgmt']} pt\n"
    msg += f" ・ストラテジ: {data['strat']} pt\n"
    msg += f" ・B問題対策: {data['bquest']} pt"
    
    return msg

def add_exp(category, amount=10):
    """
    指定されたカテゴリと経験値をプレイヤーデータに加算し、
    ボス戦の発生、ダメージ計算、撃破判定、レベルアップ判定を統合して実行する関数。
    
    Args:
        category (str): 勉強した分野（tech, mgmt, strat, bquest）
        amount (int): 加算する経験値量（1問につき10pt）
    Returns:
        tuple: (レベルアップしたか[bool], 不足分辞書または新Lv, 発生したボスイベント[str])
    """
    data = load_player_data()
    solved_count = int(amount / 10)  # 経験値から解いた問題数を逆算（10pt = 1問）
    event_type = None
    
    # 1. 基礎データの更新
    data['total_solved'] = data.get('total_solved', 0) + solved_count
    if category in data:
        data[category] += amount
    data['exp'] += amount

    # 2. ボス戦ロジックの実行
    # --- ボスが現在出現していない場合：出現判定 ---
    if not data.get("is_boss_active"):
        data['solved_since_last_boss'] = data.get('solved_since_last_boss', 0) + solved_count
        if data['solved_since_last_boss'] >= 100:
            boss = check_boss_appearance(data)
            if boss:
                event_type = "BOSS_APPEAR"
                
    # --- ボスが出現中の場合：攻撃・撃破判定 ---
    else:
        data["boss_hp"] -= solved_count  # 1問解くごとにボスHPを1減算
        if data["boss_hp"] <= 0:
            # 撃破時のリワード処理
            data["boss_hp"] = 0
            data["is_boss_active"] = False
            data["current_boss_idx"] = data.get("current_boss_idx", 0) + 1  # 次のボスへ
            data['exp'] += 200  # 撃破ボーナス
            event_type = "BOSS_DEFEATED"
        else:
            event_type = "BOSS_DAMAGE"

    # 3. レベルアップ判定
    is_eligible, diffs, next_lv = check_level_up(data)
    if is_eligible:
        data['level'] = next_lv

    # 4. すべての計算結果を1回だけ上書き保存（ファイルI/Oの節約）
    save_player_data(data)

    if is_eligible:
        return True, next_lv, event_type
    else:
        return False, diffs, event_type

def report_study(category, count):
    """
    UI（Modal）から直接呼ばれる、自己申告された問題数を反映するためのラッパー関数。
    
    Args:
        category (str): 学習カテゴリ
        count (int): 解いた問題数
    Returns:
        tuple: add_exp関数からの戻り値（Lvアップ成否、レベルまたは不足分、ボスイベント）
    """
    exp_per_question = 10
    total_earned = count * exp_per_question
    
    # 算出した合計経験値を引き渡して一括処理
    is_up, new_lv, event = add_exp(category, total_earned)
    return is_up, new_lv, total_earned, event

def check_level_up(data):
    """
    プレイヤーが次のレベルに上がれるかをチェックする「二段構え（傾斜配分）」の判定アルゴリズム。
    全体経験値に加え、基本情報技術者試験の出題比率（テクノロジ45:マネジメント5:ストラテジ10）に
    適合した個別ノルマを満たしているかを厳密に判定します。
    
    Args:
        data (dict): プレイヤーのステータスデータ
    Returns:
        tuple: (昇格可能か[bool], 不足している項目と数値の辞書[dict], 次のレベル[int])
    """
    current_lv = data.get('level', 1)
    next_lv = current_lv + 1
    
    # 1. 全体で必要な累計経験値の計算
    required_total = ((next_lv - 1) ** 2) * 100
    
    # 2. 国家試験の出題比率に合わせた、個別カテゴリの必要ノルマ計算（傾斜配分）
    base_for_norma = max(0, required_total - 100)
    targets = {
        'tech': base_for_norma * (45 / 60),   # 午前試験におけるテクノロジの配分比率
        'mgmt': base_for_norma * (5 / 60),    # マネジメントの配分比率
        'strat': base_for_norma * (10 / 60)   # ストラテジの配分比率
    }
    
    diffs = {}
    is_eligible = True
    
    # --- 判定1: 全体経験値のチェック ---
    current_total_exp = data.get('exp', 0)
    if current_total_exp < required_total:
        is_eligible = False
        diffs['total_exp'] = required_total - current_total_exp
    
    # --- 判定2: 個別カテゴリのノルマチェック ---
    for cat, target in targets.items():
        current_val = data.get(cat, 0)
        if current_val < target:
            is_eligible = False
            # math.ceilを用いて切り上げし、整数値として残り必要なポイントを算出
            diffs[cat] = math.ceil(target - current_val)
            
    return is_eligible, diffs, next_lv

def get_title(data):
    """
    プレイヤーの各ステータス値や到達レベルに応じて、最適な「称号」を動的に決定する関数。
    
    Args:
        data (dict): プレイヤーのステータスデータ
    Returns:
        str: 決定された称号名（絵文字付き）
    """
    tech = data.get('tech', 0)
    mgmt = data.get('mgmt', 0)
    strat = data.get('strat', 0)
    bquest = data.get('bquest', 0)
    total_exp = data.get('exp', 0)
    level = data.get('level', 1)

    # 1. 最上位称号（オールラウンダー）の判定
    if tech >= 3000 and mgmt >= 500 and strat >= 1000:
        return "🏆 プロフェッショナル・エンジニア"
    
    # 2. 各分野特化型の称号判定
    if tech >= 2000:
        return "💻 テクノロジの求道者"
    if mgmt >= 500:
        return "📊 チームの守護神（PM）"
    if strat >= 1000:
        return "🏢 経営戦略の军師"
    if bquest >= 1000:
        return "🧩 アルゴリズム・マスター"

    # 3. 到達レベル・累計経験値ベースの称号判定
    if level >= 10:
        return "⚔️ 熟練の学習者"
    if level >= 5:
        return "🛡️ 中級冒険者"
    if total_exp >= 500:
        return "🛡️ 初級冒険者"
    
    # 4. 初心者用初期称号
    return "🐣 ITの卵"

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