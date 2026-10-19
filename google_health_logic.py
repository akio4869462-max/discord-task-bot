"""Google Health API から日ごとの歩数を取り込むモジュール

OAuth のリフレッシュトークンで認証し、dailyRollUp で指定した日の合計歩数を取得して、
steps_logic（手入力と同じ記録）に流します。依存を増やさないため、標準ライブラリだけで通信する。

認証情報は data/google_health_token.json（client_id / client_secret / refresh_token）。
tools/google_health_auth.py で1回だけ作る。⭕ あなたの健康データを読める秘密情報なので、
Git管理外（/data/）で、バックアップにも含めない（backup_logic.DENYLIST）。

⭕ 「データが無い」と「0歩」は別物。端末の同期が済んでいない日は、APIが何も返さない。
   それを0歩として記録すると、あとで本当の歩数が来たとき差分が正しく数えられても、
   途中経過の画面や通知が「0歩」になってしまうので、データが無い日は何も記録しない。
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

import steps_logic

TOKEN_FILE = os.path.join('data', 'google_health_token.json')
TOKEN_URL = 'https://oauth2.googleapis.com/token'
STEPS_URL = 'https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp'
SCOPE = 'https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly'

SOURCE = 'google_health'
TIMEOUT_SECONDS = 20
JST = timezone(timedelta(hours=9))

REAUTH_HINT = "`python tools/google_health_auth.py` で認証をやり直して、data/google_health_token.json を差し替えてください。"
PERMISSION_HINT = "Google CloudでGoogle Health APIが有効になっているか、認証時にスコープを許可したかを確認してください。"


class GoogleHealthError(Exception):
    """取り込みに失敗した。メッセージはそのまま通知に載せるので、秘密情報を含めないこと。"""

    def __init__(self, message, needs_reauth=False):
        super().__init__(message)
        self.needs_reauth = needs_reauth


def load_credentials():
    """認証情報（client_id / client_secret / refresh_token）を読み込みます。

    Returns:
        dict/None: 3つが揃っていれば辞書。ファイルが無い・壊れている・欠けているときは None。
    """
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [ERROR] {TOKEN_FILE} の読み込みに失敗しました: {type(e).__name__}")
        return None

    if not isinstance(data, dict):
        return None
    creds = {k: data.get(k) for k in ('client_id', 'client_secret', 'refresh_token')}
    return creds if all(isinstance(v, str) and v for v in creds.values()) else None


def is_configured():
    """自動取り込みの設定（認証情報）が揃っているか。未設定なら、この機能を静かにスキップする。"""
    return load_credentials() is not None


def _error_detail(body):
    """エラー応答の本文から、短い説明を取り出します（OAuth形式・Google API形式の両方）。"""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return '', ''
    err = data.get('error') if isinstance(data, dict) else None
    if isinstance(err, str):                                  # OAuth: {"error": "invalid_grant", ...}
        return err, str(data.get('error_description', ''))[:200]
    if isinstance(err, dict):                                 # Google API: {"error": {"status": ...}}
        return str(err.get('status', '')), str(err.get('message', ''))[:200]
    return '', ''


def _request_json(url, data=None, json_body=None, headers=None):
    """POSTしてJSONを返します。通信・HTTPエラーは GoogleHealthError にする。"""
    request_headers = dict(headers or {})
    if json_body is not None:
        payload = json.dumps(json_body).encode('utf-8')
        request_headers['Content-Type'] = 'application/json'
    else:
        payload = data
    request = urllib.request.Request(url, data=payload, headers=request_headers, method='POST')

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        code, description = _error_detail(e.read().decode('utf-8', 'replace'))
        detail = f"{code} {description}".strip()
        # invalid_grant ＝ リフレッシュトークンの期限切れ・取り消し。テスト状態の同意画面は7日で切れる
        reauth = code == 'invalid_grant' or e.code == 401
        if reauth:
            hint = REAUTH_HINT
        elif e.code == 403:
            hint = PERMISSION_HINT
        else:
            hint = ''
        raise GoogleHealthError(f"Googleが {e.code} を返しました（{detail or '詳細なし'}）。{hint}".strip(),
                                needs_reauth=reauth) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GoogleHealthError(f"Googleに接続できませんでした（{type(e).__name__}）。") from None
    except ValueError:
        raise GoogleHealthError("Googleの応答を読み取れませんでした。") from None


def refresh_access_token(creds):
    """リフレッシュトークンから、短命のアクセストークンを取得します。"""
    body = urllib.parse.urlencode({
        'client_id': creds['client_id'],
        'client_secret': creds['client_secret'],
        'refresh_token': creds['refresh_token'],
        'grant_type': 'refresh_token',
    }).encode('utf-8')
    response = _request_json(TOKEN_URL, data=body,
                             headers={'Content-Type': 'application/x-www-form-urlencoded'})
    token = response.get('access_token') if isinstance(response, dict) else None
    if not isinstance(token, str) or not token:
        raise GoogleHealthError("アクセストークンを取得できませんでした。", needs_reauth=True)
    return token


def _civil(day, hours, minutes, seconds):
    return {
        'date': {'year': day.year, 'month': day.month, 'day': day.day},
        'time': {'hours': hours, 'minutes': minutes, 'seconds': seconds, 'nanos': 0},
    }


def parse_daily_steps(response):
    """dailyRollUp の応答から、合計歩数を取り出します。

    Returns:
        int/None: 歩数。その日のデータが無い（端末が未同期など）ときは None。
    """
    points = response.get('rollupDataPoints') if isinstance(response, dict) else None
    for point in points or []:
        steps = point.get('steps') if isinstance(point, dict) else None
        count = steps.get('countSum') if isinstance(steps, dict) else None
        try:
            return int(count)             # int64は文字列で返ってくる
        except (TypeError, ValueError):
            continue
    return None


def fetch_daily_steps(day):
    """指定した日（暦日）の合計歩数をGoogle Healthから取得します。

    Returns:
        int/None: 歩数。データが無い日は None。

    Raises:
        GoogleHealthError: 未設定・認証切れ・通信失敗など。
    """
    creds = load_credentials()
    if creds is None:
        raise GoogleHealthError("Google Healthの認証情報（data/google_health_token.json）がありません。")

    token = refresh_access_token(creds)
    body = {
        'range': {'start': _civil(day, 0, 0, 0), 'end': _civil(day, 23, 59, 59)},
        'windowSizeDays': 1,
    }
    response = _request_json(STEPS_URL, json_body=body,
                             headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    return parse_daily_steps(response)


def sync_day(day):
    """指定した日の歩数を取り込んで、歩数の記録（steps_logic）に流します。

    Returns:
        dict/None: {'day', 'steps', 'credit', 'message'}。credit は調教に新しく数える歩数。
                   その日のデータがまだ無ければ None（何も記録しない）。
    """
    steps = fetch_daily_steps(day)
    if steps is None:
        return None

    # 記録の日付は暦日で決まる。時刻は日付を取り出すためだけに使う
    at = datetime.combine(day, time(12, 0), tzinfo=JST)
    message, credit = steps_logic.log_steps(steps, now=at, source=SOURCE)
    return {'day': day, 'steps': steps, 'credit': credit, 'message': message}
