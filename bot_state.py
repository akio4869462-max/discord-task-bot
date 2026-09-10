"""Botの共有状態モジュール

client・tree（Discordのコアオブジェクト）や、チャンネルID・タイマー時刻などの
設定値、集中タイマー管理用の辞書など、複数のui_*.pyモジュールから横断的に
参照される状態をここに集約します。

⭕ 各ui_*.pyはこのモジュールをimportしてclient/treeにアクセスします。main.pyが
   load_dotenv()を呼んだ後にこのモジュールが最初にimportされる前提のため、
   このファイル単体を先にimportして使うことはできません（環境変数が空になります）。
"""

import os
from datetime import time, timezone, timedelta

import discord
from discord import app_commands


def getenv_int(key, default):
    """環境変数を整数として読みます。

    ⭕ docker-composeの ${VAR} 展開は、対応する.envのキーが無いと変数を
       「空文字列」として渡します。os.getenv(key, default)のデフォルト引数は
       変数が完全に未定義の場合しか使われず、空文字列には効かないため、
       int('')でBot起動時にクラッシュする事故が実際に起きました。
       ここで空文字列も明示的にデフォルト扱いにして、.envの更新漏れが
       あっても起動を落とさずフォールバックできるようにします。
    """
    value = os.getenv(key)
    return int(value) if value else default


TOKEN = os.getenv('DISCORD_TOKEN')

# Discord クライアントの初期化設定
# ⭕ スラッシュコマンドはDiscordが構造化データとして送ってくるため、
# テキストコマンド時代に必要だった message_content 特権インテントは不要
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
JST = timezone(timedelta(hours=9))
DELIVERY_TIMES = [time(8, 0, tzinfo=JST), time(20, 0, tzinfo=JST)]
NEWS_CHANNEL_ID = getenv_int('NEWS_CHANNEL_ID', 1498093810356453508)
TASK_CHANNEL_ID = getenv_int('TASK_CHANNEL_ID', NEWS_CHANNEL_ID)
# バックアップの送り先。未設定ならタスク用チャンネルへ送る
BACKUP_CHANNEL_ID = getenv_int('BACKUP_CHANNEL_ID', TASK_CHANNEL_ID)
# 週次バックアップの実行時刻。8:00の定期配信と処理が重ならないよう10分ずらす
BACKUP_TIME = time(8, 10, tzinfo=JST)
BACKUP_WEEKDAY = 0  # 0=月曜
FOCUS_TIMER_SECONDS = 1500

# タスク完了時に獲得できる疑似作業時間（15分 = 150 EXP）
TASK_COMPLETE_MINUTES = 15

# 過去問1問あたりの目安所要時間（分）。EXP換算のみに使い、演習記録そのものには影響しない。
EXAM_MINUTES_PER_QUESTION = 1.5

# ⭕ 集中タイマーの多重起動防止用：user_id -> 実行中のasyncio.Taskを保持
active_focus_timers = {}
