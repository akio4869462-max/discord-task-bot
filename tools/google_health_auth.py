"""Google Health API の認証を1回だけ通し、認証情報を data/google_health_token.json に保存する。

    python tools/google_health_auth.py <OAuthクライアントのJSON>

事前準備（Google Cloud コンソール）:
  1. プロジェクトを作り、Google Health API を有効にする
  2. OAuth 同意画面を作る（ユーザーの種類: 外部）。自分のGoogleアカウントをテストユーザーに追加する
  3. 認証情報から OAuth クライアントID（アプリの種類: デスクトップ）を作り、JSONをダウンロードする
  4. ⭕ 同意画面の公開ステータスを「本番環境」にする。「テスト」のままだと、リフレッシュトークンが
     7日で切れて、毎週この認証をやり直すことになる（100人までの未検証状態でよい。自分1人の利用）

このスクリプトはブラウザを開いて許可を求め、受け取ったトークンを保存して、最後に今日の歩数を
1回取得して動作を確かめる。⭕ client_secret やトークンは画面に表示しない。

保存先の data/google_health_token.json はあなたの健康データを読める秘密情報。Git管理外で、
バックアップにも含めない。本番サーバー（VPS）で使うときは、このファイルを ~/discord-task-bot/data/ に置く。
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google_health_logic as ghl                    # noqa: E402

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
WAIT_SECONDS = 300


def read_client(path):
    """ダウンロードしたOAuthクライアントのJSONから、client_id と client_secret を取り出す。"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    section = data.get('installed') or data.get('web') or data
    client_id, client_secret = section.get('client_id'), section.get('client_secret')
    if not client_id or not client_secret:
        raise SystemExit("client_id / client_secret が見つかりません。OAuthクライアントのJSONか確認してください。")
    return client_id, client_secret


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for_code(port, state):
    """ブラウザからのリダイレクトを受けて、認可コードを返す。"""
    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received['code'] = (query.get('code') or [None])[0]
            received['state'] = (query.get('state') or [None])[0]
            received['error'] = (query.get('error') or [None])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("<p>認証を受け取りました。このタブは閉じて、ターミナルに戻ってください。</p>".encode('utf-8'))
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *args):          # 認可コードを含むURLをログに出さない
            pass

    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = WAIT_SECONDS
    timer = threading.Timer(WAIT_SECONDS, server.shutdown)
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()

    if received.get('error'):
        raise SystemExit(f"認証が許可されませんでした: {received['error']}")
    if received.get('state') != state or not received.get('code'):
        raise SystemExit("認証の結果を受け取れませんでした（時間切れ、または不正な応答）。もう一度実行してください。")
    return received['code']


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    client_id, client_secret = read_client(sys.argv[1])

    port = free_port()
    redirect_uri = f'http://127.0.0.1:{port}'
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()

    url = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ghl.SCOPE,
        'access_type': 'offline',
        'prompt': 'consent',          # 毎回同意画面を出し、リフレッシュトークンを確実に受け取る
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })
    print("ブラウザで許可を求めます。開かない場合は、次のURLを開いてください。\n")
    print(url + "\n")
    webbrowser.open(url)

    code = wait_for_code(port, state)

    body = urllib.parse.urlencode({
        'client_id': client_id, 'client_secret': client_secret, 'code': code,
        'redirect_uri': redirect_uri, 'grant_type': 'authorization_code', 'code_verifier': verifier,
    }).encode('utf-8')
    try:
        tokens = ghl._request_json(ghl.TOKEN_URL, data=body,
                                   headers={'Content-Type': 'application/x-www-form-urlencoded'})
    except ghl.GoogleHealthError as e:
        raise SystemExit(f"トークンの交換に失敗しました: {e}")

    refresh_token = tokens.get('refresh_token')
    if not refresh_token:
        raise SystemExit("リフレッシュトークンが返ってきませんでした。"
                         "Googleアカウントの「サードパーティのアクセス」でこのアプリを削除してから、もう一度実行してください。")

    os.makedirs(os.path.dirname(ghl.TOKEN_FILE), exist_ok=True)
    with open(ghl.TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump({'client_id': client_id, 'client_secret': client_secret, 'refresh_token': refresh_token},
                  f, ensure_ascii=False, indent=4)
    try:
        os.chmod(ghl.TOKEN_FILE, 0o600)         # Windowsでは効かないが、害は無い
    except OSError:
        pass
    print(f"✅ 認証情報を保存しました: {ghl.TOKEN_FILE}")

    print("今日の歩数を取得して、動作を確かめます…")
    try:
        steps = ghl.fetch_daily_steps(datetime.now(ghl.JST).date())
    except ghl.GoogleHealthError as e:
        raise SystemExit(f"❌ 認証は保存されましたが、歩数を取得できませんでした: {e}")
    if steps is None:
        print("✅ つながりました。ただし、今日の歩数はまだGoogle Healthにありません（端末の同期待ちかもしれません）。")
    else:
        print(f"✅ つながりました。今日の歩数: {steps:,}歩")


if __name__ == '__main__':
    main()
