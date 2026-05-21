import json
import os

# タスクデータを永続化するためのJSONファイルのパス
DB_FILE = 'todo.json'

def load_data():
    """
    JSONファイルからタスクデータを読み込む関数。
    ファイルが存在しない場合は、安全に空のリストを返します。
    
    Returns:
        list: タスク文字列が格納されたリスト
    """
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_data(data):
    """
    指定されたタスクデータをJSONファイルへ書き込み、保存する関数。
    日本語が文字化けしないよう、ensure_ascii=False を指定しています。
    
    Args:
        data (list): 保存するタスクデータのリスト
    """
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_task(task_text):
    """
    新しいタスクをJSONデータに追加し、保存する関数。
    
    Args:
        task_text (str): ユーザーから入力されたタスクの内容
    Returns:
        str: 登録完了を通知するチャット用メッセージ
    """
    todo_list = load_data()
    todo_list.append(task_text)
    save_data(todo_list)
    return f'✅ 「{task_text}」を登録＆保存しました！'

def list_tasks():
    """
    現在保存されているタスクを整形し、一覧として返す関数。
    タスクが空の場合は、その旨を通知するメッセージを返します。
    
    Returns:
        str: 番号付きのタスク一覧メッセージ、または未登録通知
    """
    todo_list = load_data()
    if not todo_list:
        return '現在、登録されたタスクはありません。'
    
    response = '【現在のタスク一覧】\n'
    # enumerateを使って、1から始まる番号を自動付与してテキストを構築
    for i, t in enumerate(todo_list, 1):
        response += f'{i}. {t}\n'
    return response

def complete_task(number_str):
    """
    ユーザーが指定した番号のタスクをリストから削除（完了）し、データを更新する関数。
    不正な入力値や範囲外の番号に対して、例外処理（try-except）によるガードを行っています。
    
    Args:
        number_str (str): 完了したいタスクの番号（ユーザー入力の文字列）
    Returns:
        str: 処理結果（成功メッセージ、またはエラーメッセージ）
    """
    try:
        todo_list = load_data()
        # ユーザー目線の「1番」をプログラム用の「インデックス0」に補正
        index = int(number_str) - 1
        
        # 指定されたインデックスがリストの範囲内にあるかチェック
        if 0 <= index < len(todo_list):
            removed = todo_list.pop(index)
            save_data(todo_list)
            return f'消去＆保存完了: 「{removed}」をお疲れ様でした！'
        else:
            return 'その番号のタスクは見つかりません。'
    except ValueError:
        # 数字以外の文字が渡された場合のエラーハンドリング
        return '番号を正しく入力してください（例: !done 1）'

def get_task_count():
    """
    現在のタスクの総数を返す関数。
    Discord UI（View）側で、動的にいくつ完了ボタンを生成するかを決定するために使用されます。
    
    Returns:
        int: タスクの総数
    """
    todo_list = load_data()
    return len(todo_list)

def get_task_text(index):
    """
    指定されたインデックス（要素番号）のタスク内容を取得する関数。
    範囲外のインデックスが指定された場合は None を返します。
    
    Args:
        index (int): 取得したいタスクのインデックス
    Returns:
        str/None: タスクの内容文字列、または存在しない場合は None
    """
    todo_list = load_data()
    if 0 <= index < len(todo_list):
        return todo_list[index]
    return None