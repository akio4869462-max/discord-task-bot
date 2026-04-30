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
    # 初期データ
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
    
    bar_length = 10
    filled_length = int(bar_length * progress_percent)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # 3. 称号とノルマ判定の取得
    # title = get_title(data)
    is_eligible, diffs, _ = check_level_up(data)
    
    # 4. メッセージの組み立て
    msg = f"🏆 **現在のランク: Lv.{level}**\n"
    # msg += f"称号: **{title}**\n"
    msg += f"進捗: `{bar}` {int(progress_percent * 100)}%\n\n"
    
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
    msg += f" ・累計経験値: {current_exp} EXP\n"
    msg += f" ・テクノロジ: {data['tech']} pt\n"
    msg += f" ・マネジメント: {data['mgmt']} pt\n"
    msg += f" ・ストラテジ: {data['strat']} pt\n"
    msg += f" ・B問題対策: {data['bquest']} pt"
    
    return msg

def add_exp(category, amount=10):
    data = load_player_data()
    
    # 経験値を加算
    if category in data:
        data[category] += amount
    data['exp'] += amount #

    # レベルアップ判定
    is_eligible, diffs, next_lv = check_level_up(data)

    # ファイルに保存
    with open(PLAYER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    if is_eligible:
        data['level'] = next_lv
        save_player_data(data)
        return True, next_lv # レベルアップ成功
    else:
        save_player_data(data)
        return False, diffs # まだ上がらない（不足分を返す）

def report_study(category, count):
    """
    自己申告された問題数に応じて経験値を加算する
    1問 = 10 EXP として計算
    """
    exp_per_question = 10
    total_earned = count * exp_per_question
    
    # 前に作った add_exp を使って加算
    is_up, new_lv = add_exp(category, total_earned)
    
    return is_up, new_lv, total_earned

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