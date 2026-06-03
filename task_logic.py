"""タスク管理データ永続化モジュール

JSONファイル（todo.json）を用いてユーザーのタスクデータを永続化し、
追加、一覧取得、削除（完了処理）などのバックエンドロジックを提供します。
"""

import json
import os

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
DB_FILE = 'todo.json'


def load_data():
    """JSONファイルからタスクデータを読み込みます。

    ファイルが存在しない場合や、破損している場合は安全に空のリストを返します。

    Returns:
        list: タスク内容（文字列）が格納されたリスト。
    """
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [ERROR] タスクデータ（{DB_FILE}）の読み込みに失敗しました: {e}")
            return []
    return []


def save_data(data):
    """指定されたタスクデータをJSONファイルへ書き込み、保存します。

    Args:
        data (list): 保存対象のタスクデータリスト。
    """
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            # 日本語の文字化けを防ぐため ensure_ascii=False を指定
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] タスクデータ（{DB_FILE}）の保存に失敗しました: {e}")


def add_task(task_text):
    """新しいタスクをデータに追加し、永続化します。

    Args:
        task_text (str): ユーザーから入力されたタスクの内容。

    Returns:
        str: 登録完了を通知するチャット用メッセージ。
    """
    todo_list = load_data()
    todo_list.append(task_text)
    save_data(todo_list)
    return f'✅ 「{task_text}」を登録＆保存しました！'


def list_tasks():
    """現在保存されているすべてのタスクを整形し、一覧として取得します。

    Returns:
        str: 番号付きのタスク一覧メッセージ、または未登録通知メッセージ。
    """
    todo_list = load_data()
    if not todo_list:
        return '現在、登録されたタスクはありません。'
    
    response = '【現在のタスク一覧】\n'
    # 1から始まる通し番号を自動付与してテキストを構築
    for i, t in enumerate(todo_list, 1):
        response += f'{i}. {t}\n'
    return response


def complete_task(number_str):
    """ユーザーが指定した番号のタスクをリストから削除（完了処理）し、データを更新します。

    Args:
        number_str (str): 完了したいタスクの番号（ユーザー入力の文字列）。

    Returns:
        str: 処理結果を示すステータスメッセージ。
    """
    try:
        todo_list = load_data()
        # ユーザー目線の「1番」をプログラム用の「インデックス0」に補正
        index = int(number_str) - 1
        
        # 指定されたインデックスがリストの範囲内にあるか判定
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
    """現在のタスクの総数を取得します。

    Discord UI（View）側で、動的にいくつ完了ボタンを生成するかを決定するために使用されます。

    Returns:
        int: 保存されているタスクの総数。
    """
    todo_list = load_data()
    return len(todo_list)


def get_task_text(index):
    """指定されたインデックス（要素番号）のタスク内容を取得します。

    Args:
        index (int): 取得したいタスクのインデックス。

    Returns:
        str/None: タスクの内容文字列。インデックスが範囲外の場合は None。
    """
    todo_list = load_data()
    if 0 <= index < len(todo_list):
        return todo_list[index]
    return None