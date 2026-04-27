import os
import json
import random

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