"""開発用Bot（task-bot-dev）としてBotを起動する。

    PYTHONIOENCODING=utf-8 python tools/run_dev.py

`.env.dev` を読み込んで main.py を起動する。本番の `.env` は書き換えない。

⭕ 本番と同じトークンで二重ログインすると、EC2で動いているBotとローカルの両方が
   同じ操作に反応し、片方は「既に応答済み」で失敗する。さらにデータが2箇所に
   分かれて書かれる。取り違えは目視では防げないので、起動前に機械的に弾く。
"""

import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_ENV = os.path.join(ROOT, '.env.dev')
PROD_ENV = os.path.join(ROOT, '.env')

REQUIRED = ('DISCORD_TOKEN', 'TASK_CHANNEL_ID')


def read_env(path):
    """.env 形式のファイルを辞書にして返す。"""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    dev = read_env(DEV_ENV)
    if not dev:
        sys.exit(
            f"❌ {DEV_ENV} がありません。\n"
            f"   cp .env.dev.example .env.dev でひな形をコピーし、値を埋めてください。")

    missing = [k for k in REQUIRED if not dev.get(k)]
    if missing:
        sys.exit(f"❌ .env.dev の {', '.join(missing)} が空です。")

    prod_token = read_env(PROD_ENV).get('DISCORD_TOKEN')
    if prod_token and dev['DISCORD_TOKEN'] == prod_token:
        sys.exit(
            "❌ .env.dev のトークンが本番（.env）と同じです。\n"
            "   このまま起動するとEC2のBotと二重ログインになり、両方が同じ操作に\n"
            "   反応します。task-bot-dev のトークンを設定してください。")

    # ⭕ main.py の load_dotenv() は既存の環境変数を上書きしない。ここで入れた値が勝つ。
    os.environ.update(dev)
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)

    print("🧪 開発用Bot（.env.dev）で起動します。本番の .env は使いません。")
    runpy.run_path(os.path.join(ROOT, 'main.py'), run_name='__main__')


if __name__ == '__main__':
    main()
