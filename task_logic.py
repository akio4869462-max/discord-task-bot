import json
import os

DB_FILE = 'todo.json'

def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_data(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_task(task_text):
    todo_list = load_data()
    todo_list.append(task_text)
    save_data(todo_list)
    return f'✅ 「{task_text}」を登録＆保存しました！'

def list_tasks():
    todo_list = load_data()
    if not todo_list:
        return '現在、登録されたタスクはありません。'
    
    response = '【現在のタスク一覧】\n'
    for i, t in enumerate(todo_list, 1):
        response += f'{i}. {t}\n'
    return response

def complete_task(number_str):
    try:
        todo_list = load_data()
        index = int(number_str) - 1
        if 0 <= index < len(todo_list):
            removed = todo_list.pop(index)
            save_data(todo_list)
            return f'消去＆保存完了: 「{removed}」をお疲れ様でした！'
        else:
            return 'その番号のタスクは見つかりません。'
    except ValueError:
        return '番号を正しく入力してください（例: !done 1）'

def get_task_count():
    """現在のタスクの総数を返す（ボタンをいくつ作るか決めるために使用）"""
    todo_list = load_data()
    return len(todo_list)

def get_task_text(index):
    """指定されたインデックスのタスク内容を返す（確認用）"""
    todo_list = load_data()
    if 0 <= index < len(todo_list):
        return todo_list[index]
    return None