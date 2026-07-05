"""タスク管理データ永続化モジュール (期限拡張 ＆ 優先度スター対応版)

JSONファイル（todo.json）を用いてユーザーのタスクデータを永続化します。
タスクごとにカテゴリ、期限（デッドライン）、そして優先度（★）を保持し、
優先度高 ＆ 期限順のマルチソート機能をサポートします。
"""

import json
import os
import uuid
from datetime import datetime

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
DB_FILE = os.path.join('data', 'todo.json')

CATEGORY_MAP = {
    'programming': '💻 開発',
    'document': '📝 書類・面接',
    'reading': '📚 インプット'
}

PRIORITY_MAP = {
    3: '★★★',
    2: '★★☆',
    1: '★☆☆'
}


def load_data():
    """JSONファイルからタスクデータを読み込みます。"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [ERROR] タスクデータ（{DB_FILE}）の読み込みに失敗しました: {e}")
            return []
    return []


def save_data(data):
    """指定されたタスクデータをJSONファイルへ書き込み、保存します。"""
    try:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] タスクデータ（{DB_FILE}）の保存に失敗しました: {e}")


def add_task(task_text, category='programming', deadline_str=None, priority=2):
    """新しいタスクをカテゴリ情報・期限・優先度付きでデータに追加し、永続化します。

    Args:
        task_text (str): タスクの内容。
        category (str): タスクのカテゴリ。
        deadline_str (str): ユーザー入力の期限（例: "6/15", "2026-06-15"）。
        priority (int): 優先度数値。3=高, 2=中, 1=低。デフォルトは 2。

    Returns:
        str: 登録完了メッセージ。
    """
    if category not in CATEGORY_MAP:
        category = 'programming'

    # 優先度の値チェック（安全対策）
    if priority not in [1, 2, 3]:
        priority = 2

    # 📅 期限文字列を「YYYY-MM-DD」形式にパース（整形）する
    formatted_deadline = None
    if deadline_str and deadline_str.strip():
        try:
            cleaned_str = deadline_str.strip().replace('/', '-')
            if len(cleaned_str.split('-')) == 2:
                current_year = datetime.now().year
                cleaned_str = f"{current_year}-{cleaned_str}"
            
            dt = datetime.strptime(cleaned_str, "%Y-%m-%d")
            formatted_deadline = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    todo_list = load_data()
    
    new_item = {
        "id": uuid.uuid4().hex[:8],  # ⭕ プルダウン選択の対象を一意に特定するためのID
        "task": task_text,
        "category": category,
        "deadline": formatted_deadline,
        "priority": priority
    }
    todo_list.append(new_item)
    save_data(todo_list)
    
    category_name = CATEGORY_MAP[category]
    stars = PRIORITY_MAP[priority]
    dl_msg = f"（期限: {formatted_deadline}）" if formatted_deadline else "（期限なし）"
    return f'✅ 【{category_name}】に「{task_text}」を登録しました！ [優先度: {stars}] {dl_msg}'


def get_display_fields(item):
    """タスク辞書から、プルダウン等の表示に使う (タスク内容, 優先度の星) を取り出します。

    list_tasks()を一度でも通したタスクは必ずこの辞書形式になっているため、
    呼び出し側で辞書かどうかを判定する必要はありません。
    """
    task_text = item.get('task', '')
    stars = PRIORITY_MAP.get(item.get('priority', 2), '★★☆')
    return task_text, stars


def list_tasks():
    """現在保存されているタスクを『優先度が高い順』、次いで『期限が近い順』にソートして一覧表示します。"""
    todo_list = load_data()
    if not todo_list:
        return '現在、登録されたタスクはありません。'
    
    # 互換性を持たせつつ辞書型に統一（古い形式のデータがあっても壊れないようにするわ！）
    normalized_list = []
    for item in todo_list:
        if isinstance(item, str):
            normalized_list.append({"id": uuid.uuid4().hex[:8], "task": item, "category": "programming", "deadline": None, "priority": 2})
        else:
            normalized_list.append({
                "id": item.get('id') or uuid.uuid4().hex[:8],  # 過去のタスクにはここでIDを補完するわ
                "task": item.get('task', ''),
                "category": item.get('category', 'programming'),
                "deadline": item.get('deadline', None),
                "priority": item.get('priority', 2)  # 過去のタスクはとりあえず「中(2)」にするわ
            })

    # ⭕ 2段階ソート：①優先度の降順(-x['priority']) -> ②期限の昇順
    # 優先度3(高)が一番上に来て、同じ優先度の中では期限が近い順に並ぶようにするわよ！
    normalized_list.sort(key=lambda x: (-x['priority'], x['deadline'] if x['deadline'] else '9999-12-31'))

    # ソートされた状態で保存データを更新
    save_data(normalized_list)
    
    response = '📋 **【現在のクエスト一覧（優先度＆期限順）】**\n'
    for i, item in enumerate(normalized_list, 1):
        task_text = item.get('task', '')
        cat_key = item.get('category', 'programming')
        category_text = CATEGORY_MAP.get(cat_key, '💻 開発')
        dl = item.get('deadline', None)
        priority = item.get('priority', 2)
        
        stars = PRIORITY_MAP.get(priority, '★★☆')
        dl_text = f" ⏳ 期限: {dl}" if dl else " 🗓️ 期限なし"
        
        # ちょっと豪華に、最優先(3)には「🔥」マークをつけて目立たせちゃう！
        p_emoji = "🔥 " if priority == 3 else ""
        
        response += f'{i}. {p_emoji}[{stars}] 【{category_text}】 {task_text}{dl_text}\n'
        
    return response


def _finish_complete(removed):
    """完了（削除）したタスクの情報から通知メッセージとカテゴリを組み立てます。"""
    if isinstance(removed, str):
        task_text = removed
        category = 'programming'
    else:
        task_text = removed.get('task', '')
        category = removed.get('category', 'programming')

    msg = f'消去＆保存完了: 「{task_text}」をお疲れ様でした！'
    return msg, category


def complete_task(identifier):
    """タスクを完了（削除）します。

    プルダウン選択時は一意なタスクID（英数字）、テキストコマンド（!done N）時は
    表示上の番号（1始まり）を受け取ります。IDでの完全一致を優先することで、
    一覧表示後にタスクが増減・並び替えされても、選んだつもりと別のタスクを
    誤って完了させてしまう事故を防ぎます。
    """
    todo_list = load_data()

    if not identifier.isdigit():
        for i, item in enumerate(todo_list):
            if isinstance(item, dict) and item.get('id') == identifier:
                removed = todo_list.pop(i)
                save_data(todo_list)
                return _finish_complete(removed)
        return 'そのタスクは既に完了しているか、見つかりませんでした。', None

    index = int(identifier) - 1
    if 0 <= index < len(todo_list):
        removed = todo_list.pop(index)
        save_data(todo_list)
        return _finish_complete(removed)
    else:
        return 'その番号のタスクは見つかりません。', None