"""Botの生存確認（ハートビート）モジュール

discord.pyのBotは1日2回の定期処理以外はDiscordのゲートウェイに接続したまま待機しているだけなので、
「プロセスは生きているがイベントループが実質フリーズしている」ような状態には気づきにくい。
このモジュールは、動いている間だけ5分おきに現在時刻をファイルへ書き込むだけの単純な仕組みを提供する。

⭕ HTTPサーバーは立てない。EC2側でファイルの新しさをSSH経由で確認すれば十分であり、
   新しいポート開放やセキュリティグループの変更が不要になる（監視用ワークフロー側を参照）。
"""

import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
HEARTBEAT_FILE = os.path.join('data', 'heartbeat.txt')


def write_heartbeat(now=None):
    """現在時刻（ISO8601）をハートビートファイルへ書き込みます。

    ⭕ 書き込み失敗（ディスク一杯など）でBot本体を落としたくないので、例外はここで飲み込む。
       失敗そのものに気づけなくなるが、次の監視サイクルで「ファイルが古いまま」として検知できる。
    """
    now = now or datetime.now(JST)
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            f.write(now.isoformat())
        return True
    except OSError as error:
        print(f"⚠️ [heartbeat] 書き込みに失敗しました: {type(error).__name__}: {error}")
        return False


def read_last_heartbeat():
    """ハートビートファイルの内容をdatetimeとして返します。無ければNone。"""
    try:
        with open(HEARTBEAT_FILE, 'r', encoding='utf-8') as f:
            return datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None


def heartbeat_age_seconds(now=None):
    """最後のハートビートから何秒経っているかを返します。ファイルが無ければNoneを返します。"""
    now = now or datetime.now(JST)
    last = read_last_heartbeat()
    if last is None:
        return None
    return (now - last).total_seconds()
