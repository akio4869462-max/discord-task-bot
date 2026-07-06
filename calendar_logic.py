"""Googleカレンダー連携ロジックモジュール

タスクの期限を、サービスアカウント認証を用いてGoogleカレンダーの終日予定として
自動登録します。認証ファイルまたはカレンダーIDが未設定の場合は、連携なしの
状態として静かにスキップします（この機能が無くてもBot本体は問題なく動作します）。
"""

import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = os.path.join('data', 'service_account.json')
CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
SCOPES = ['https://www.googleapis.com/auth/calendar']


def is_configured():
    """カレンダー連携に必要な設定（認証ファイル・カレンダーID）が揃っているかを確認します。"""
    return bool(CALENDAR_ID) and os.path.exists(SERVICE_ACCOUNT_FILE)


def create_deadline_event(task_text, category_name, deadline):
    """タスクの期限を、終日予定としてGoogleカレンダーに登録します。

    Args:
        task_text (str): タスクの内容。
        category_name (str): 表示用のカテゴリ名（例: "💻 開発"）。
        deadline (str): "YYYY-MM-DD"形式の期限。

    Returns:
        str/None: 登録できた場合はイベントへのリンクURL、未設定・失敗時はNone。
    """
    if not is_configured():
        return None

    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)

        event = {
            'summary': f'【{category_name}】{task_text}',
            'start': {'date': deadline},
            'end': {'date': deadline},
        }
        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return created_event.get('htmlLink')
    except Exception as e:
        print(f"⚠️ [ERROR] Googleカレンダーへの登録に失敗しました: {e}")
        return None
