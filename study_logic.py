import os
import json
import random
import math

# 【基本情報用語クイズ】
def get_kiso_quiz():
    if not os.path.exists('glossary.json'):
        return "用語データが見つかりません。"
    
    with open('glossary.json', 'r', encoding='utf-8') as f:
        glossary = json.load(f)
    
    if not glossary:
        return "用語が登録されていません。"

    qa = random.choice(glossary)
    return f"**【試験用語】**\n用語: **{qa['term']}**\n解説: ||{qa['desc']}||"

# 【数値変換クイズ：2進数・10進数・16進数】
# 計算問題のロジック
def get_math_quiz():
    target_num = random.randint(1, 255)
    mode = random.randint(0, 3)
    
    if mode == 0:
        return f"10進数「{target_num}」を 2進数(8bit) に直すと？\n答え: || {format(target_num, '08b')} ||"
    elif mode == 1:
        return f"2進数「{format(target_num, '08b')}」を 10進数 に直すと？\n答え: || {target_num} ||"
    elif mode == 2:
        return f"2進数「{format(target_num, '08b')}」を 16進数 に直すと？\n答え: || {format(target_num, '02X')} ||"
    else:
        return f"16進数「{format(target_num, '02X')}」を 2進数(8bit) に直すと？\n答え: || {format(target_num, '08b')} ||"

def add_kiso(term, desc): # 引数を2つ（term と desc）にする
    # 以前のように split('/') する必要がなくなります
    if not term or not desc:
        return "用語と説明を両方入力してください。"

    glossary = []
    if os.path.exists('glossary.json'):
        with open('glossary.json', 'r', encoding='utf-8') as f:
            glossary = json.load(f)

    # データを追加
    glossary.append({"term": term, "desc": desc})

    with open('glossary.json', 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=4)

    return f"✅ 用語「{term}」を登録しました！"

def search_glossary(word):
    if not os.path.exists('glossary.json'):
        return "用語データが見つかりません。"
    
    with open('glossary.json', 'r', encoding='utf-8') as f:
        glossary = json.load(f)
    
    # 用語集の中から、入力された単語と一致するものを探す
    # 部分一致（その言葉が含まれているか）にするとより便利です
    results = [qa for qa in glossary if word.lower() in qa['term'].lower()]
    
    if not results:
        return f"「{word}」に関する用語は見つかりませんでした。"
    
    # 見つかったものを整形して返す
    response = f"🔍 「{word}」の検索結果 ({len(results)}件):\n"
    for qa in results:
        response += f"**【{qa['term']}】**\n{qa['desc']}\n"
    return response

PLAYER_DATA_FILE = 'player_data.json'

def load_player_data():
    if os.path.exists(PLAYER_DATA_FILE):
        with open(PLAYER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 初期データx
    return {"level": 1, "exp": 0, "tech": 0, "mgmt": 0, "strat": 0, "bquest": 0}

def save_player_data(data):
    """引数で受け取った辞書データをJSONファイルに書き込む"""
    with open(PLAYER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_status_summary():
    data = load_player_data()
    current_exp = data['exp']
    
    # 1. 現在のレベルと次のレベルの境界を計算
    level = data['level']
    next_level = level + 1
    
    # 現在のレベルの開始地点と、次のレベルに必要な累計EXP
    exp_for_current_level = ((level - 1) ** 2) * 100
    exp_for_next_level = ((next_level - 1) ** 2) * 100
    
    # 2. 進捗バーの計算（全体経験値ベース）
    exp_in_level = max(0, current_exp - exp_for_current_level)
    needed_in_level = exp_for_next_level - exp_for_current_level
    # バーが100%を超えないように制御
    progress_percent = min(1.0, exp_in_level / needed_in_level)

    # 3. 称号とノルマ判定の取得
    title = get_title(data)
    is_eligible, diffs, _ = check_level_up(data)

    if not is_eligible and progress_percent >= 1.0:
        progress_percent = 0.99
    
    bar_length = 10
    filled_length = int(bar_length * progress_percent)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)


    
    # 4. メッセージの組み立て
    msg = f"🏆 **現在のランク: Lv.{level}**\n"
    msg += f"称号: **{title}**\n"
    msg += f"進捗: `{bar}` {int(progress_percent * 100)}%\n\n"
    
    # ボス戦の表示
    current_idx = data.get('current_boss_idx', 0)
    if current_idx < len(BOSS_LIST):
        boss = BOSS_LIST[current_idx]
        if data.get('total_solved', 0) >= boss['threshold']:
            # ボス戦中
            hp = data.get('boss_hp', boss['hp'])
            max_hp = boss['hp']
            hp_bar = '🟥' * int(10 * (hp/max_hp)) + '⬜' * (10 - int(10 * (hp/max_hp)))
            msg += f"⚠️ **BOSS BATTLE: {boss['name']}**\n"
            msg += f"HP: `{hp_bar}` {hp} / {max_hp}\n\n"
        else:
            # 次のボスまでのカウントダウン
            next_target = boss['threshold'] - data.get('total_solved', 0)
            msg += f"👾 次のボス出現まで: あと {next_target} 問\n\n"

    # 5. 不足分の表示（二段構え判定）
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
    
    msg += f"\n📊 **現在の詳細ステータス:**\n"
    msg += f"📚 累計回答数: {data.get('total_solved', 0)} 問\n"
    msg += f" ・累計経験値: {current_exp} EXP\n"
    msg += f" ・テクノロジ: {data['tech']} pt\n"
    msg += f" ・マネジメント: {data['mgmt']} pt\n"
    msg += f" ・ストラテジ: {data['strat']} pt\n"
    msg += f" ・B問題対策: {data['bquest']} pt"
    
    return msg

def add_exp(category, amount=10):
    data = load_player_data()
    solved_count = int(amount / 10)
    event_type = None
    
    # 1. 基礎データの更新
    data['total_solved'] = data.get('total_solved', 0) + solved_count
    if category in data:
        data[category] += amount
    data['exp'] += amount

    # 2. ボス戦ロジックの実行
    # --- 1. ボス出現判定 ---
    if not data.get("is_boss_active"):
        data['solved_since_last_boss'] = data.get('solved_since_last_boss', 0) + solved_count
        if data['solved_since_last_boss'] >= 100:
            boss = check_boss_appearance(data)
            if boss:
                event_type = "BOSS_APPEAR" # 出現イベント
    # --- 2. 攻撃・撃破判定 ---
    else:
        data["boss_hp"] -= solved_count
        if data["boss_hp"] <= 0:
            data["boss_hp"] = 0
            data["is_boss_active"] = False
            data["current_boss_idx"] = data.get("current_boss_idx", 0) + 1
            data['exp'] += 200
            event_type = "BOSS_DEFEATED" # 撃破イベント
        else:
            event_type = "BOSS_DAMAGE" # ダメージイベント

    # 3. レベルアップ判定（現在のデータで判定）
    is_eligible, diffs, next_lv = check_level_up(data)
    if is_eligible:
        data['level'] = next_lv

    # 4. 全ての更新が終わってから1回だけ保存する
    save_player_data(data)

    # 5. 結果を返却
    if is_eligible:
        return True, next_lv, event_type
    else:
        return False, diffs, event_type

def report_study(category, count):
    """
    自己申告された問題数に応じて経験値を加算する
    1問 = 10 EXP として計算
    """
    exp_per_question = 10
    total_earned = count * exp_per_question
    
    # 前に作った add_exp を使って加算
    is_up, new_lv, event = add_exp(category, total_earned)
    
    return is_up, new_lv, total_earned, event

def check_level_up(data):
    current_lv = data.get('level', 1)
    next_lv = current_lv + 1
    
    # 1. 全体で必要な累計EXP（ベースライン）
    required_total = ((next_lv - 1) ** 2) * 100
    
    # 2. 各カテゴリで必要な個別ノルマ（required_totalに対する比率）
    base_for_norma = max(0, required_total - 100)
    targets = {
        'tech': base_for_norma * (45 / 60),
        'mgmt': base_for_norma * (5 / 60),
        'strat': base_for_norma * (10 / 60)
    }
    
    diffs = {}
    is_eligible = True
    
    # --- 判定1: 全体経験値のチェック ---
    current_total_exp = data.get('exp', 0)
    if current_total_exp < required_total:
        is_eligible = False
        diffs['total_exp'] = required_total - current_total_exp
    
    # --- 判定2: 個別カテゴリのチェック ---
    for cat, target in targets.items():
        current_val = data.get(cat, 0)
        if current_val < target:
            is_eligible = False
            # すでに total_exp で落ちていても、何が足りないか可視化するために計算を続ける
            diffs[cat] = math.ceil(target - current_val)
            
    # 全体かつ個別の全てを満たした場合のみ is_eligible は True のまま残る
    return is_eligible, diffs, next_lv

def get_title(data):
    """
    プレイヤーのステータスに基づいて称号を決定する
    """
    tech = data.get('tech', 0)
    mgmt = data.get('mgmt', 0)
    strat = data.get('strat', 0)
    bquest = data.get('bquest', 0)
    total_exp = data.get('exp', 0)
    level = data.get('level', 1)

    # 1. 最上位称号（全ての分野で高い実績）
    if tech >= 3000 and mgmt >= 500 and strat >= 1000:
        return "🏆 プロフェッショナル・エンジニア"
    
    # 2. 分野特化型称号
    if tech >= 2000:
        return "💻 テクノロジの求道者"
    if mgmt >= 500:
        return "📊 チームの守護神（PM）"
    if strat >= 1000:
        return "🏢 経営戦略の軍師"
    if bquest >= 1000:
        return "🧩 アルゴリズム・マスター"

    # 3. レベル・累計経験値ベースの称号
    if level >= 10:
        return "⚔️ 熟練の学習者"
    if level >= 5:
        return "🛡️ 中級冒険者"
    if total_exp >= 500:
        return "🛡️ 初級冒険者"
    
    # 4. 初期称号
    return "🐣 ITの卵"

# ボスの定義はそのまま活用！
BOSS_LIST = [
    {"threshold": 100, "name": "ITパスポートの残影", "hp": 10},
    {"threshold": 300, "name": "令和5年度 過去問の番人", "hp": 60},
    {"threshold": 500, "name": "アルゴリズムの巨像", "hp": 100},
    {"threshold": 1000, "name": "基本情報エンジニアの覇者", "hp": 300},
]

def check_boss_appearance(data):
    """ボス出現判定ロジック"""
    # 累計ではなく『前回のボス撃破からの加算分』で判定する
    current_count = data.get('solved_since_last_boss', 0)
    current_boss_idx = data.get('current_boss_idx', 0)
    
    if current_boss_idx < len(BOSS_LIST):
        next_boss = BOSS_LIST[current_boss_idx]
        # 「あと100問」など、各ボスごとの出現条件（threshold）を満たしたか
        if current_count >= 100: # ここを固定値（100）にしても、リストのthresholdにしてもOK
            if not data.get("is_boss_active"):
                data["boss_hp"] = next_boss["hp"]
                data["is_boss_active"] = True
                data["solved_since_last_boss"] = 0 # ここでリセット！
                return next_boss
    return None