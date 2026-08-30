"""データバックアップモジュール

data/ 配下の学習記録・タスク・演習成績などを1つのZIPにまとめ、Discordへ
添付できる形で返します。ホスト（EC2）上の data/ にしか存在しないデータが、
インスタンス消失とともに失われるのを防ぐための仕組みです。

⭕ 対象ファイルは「許可リスト方式」で管理しています。data/ を丸ごと固める
   のではなく、ここに列挙したファイルだけをZIPに入れるため、認証情報
   （data/service_account.json）が設計上バックアップへ混入しません。
"""

import os
import zipfile
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

DATA_DIR = 'data'
BACKUP_DIR = os.path.join('data', '_backups')

# 【バックアップ対象】ここに書いたファイルだけがZIPに入ります。
# ⚠️ service_account.json（Googleの秘密鍵）は絶対に追加しないこと。
BACKUP_TARGETS = (
    'todo.json',            # タスク一覧
    'player_data.json',     # 学習記録・レベル・EXP
    'glossary.json',        # ストックした用語
    'exam_data.json',       # 演習成績
    'training_data.json',   # トレーニングログ・体組成
    'typing_data.json',     # タイピング記録
    'news_keywords.json',   # ニュース検索キーワード
)

# 許可リストに万一混ざっても弾く二重の防波堤
DENYLIST = ('service_account.json',)

# ホスト上に残すZIPの世代数
KEEP_ARCHIVES = 8

# Discordの添付上限に対する安全マージン（無料枠は10MB前後のため8MBで警告）
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

WEEKDAY_JP = '月火水木金土日'


def collect_targets():
    """バックアップ対象のうち、実在するファイルのパス一覧と欠けている名前を返します。"""
    found = []
    missing = []

    for name in BACKUP_TARGETS:
        if name in DENYLIST:
            continue
        path = os.path.join(DATA_DIR, name)
        if os.path.exists(path):
            found.append(path)
        else:
            missing.append(name)

    return found, missing


def create_archive(now=None):
    """対象ファイルを1つのZIPにまとめ、(パス, 収録した名前, 未収録の名前) を返します。"""
    now = now or datetime.now(JST)
    found, missing = collect_targets()

    if not found:
        return None, [], missing

    os.makedirs(BACKUP_DIR, exist_ok=True)
    zip_path = os.path.join(BACKUP_DIR, f"backup_{now.strftime('%Y-%m-%d')}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in found:
            # arcnameを指定して、ZIP内はフラットな構成（todo.json 等）にする
            archive.write(path, arcname=os.path.basename(path))

    return zip_path, [os.path.basename(p) for p in found], missing


def is_within_upload_limit(zip_path):
    """ZIPがDiscordの添付上限（安全マージン込み）に収まっているかを返します。"""
    return os.path.getsize(zip_path) <= MAX_UPLOAD_BYTES


def prune_old_archives(keep=None):
    """ホスト上のZIPを新しい方からkeep世代までに整理し、削除した名前を返します。

    ⭕ ファイル名が backup_YYYY-MM-DD.zip 固定なので、名前順のソートが日付順と一致します。
    """
    keep = KEEP_ARCHIVES if keep is None else keep

    if not os.path.isdir(BACKUP_DIR):
        return []

    archives = sorted(
        name for name in os.listdir(BACKUP_DIR)
        if name.startswith('backup_') and name.endswith('.zip')
    )
    stale = archives if keep <= 0 else archives[:-keep]

    removed = []
    for name in stale:
        os.remove(os.path.join(BACKUP_DIR, name))
        removed.append(name)

    return removed


def build_message(zip_path, included, missing, now=None):
    """Discordへ添付する際の本文を組み立てます。"""
    now = now or datetime.now(JST)
    date_text = f"{now.strftime('%Y-%m-%d')}({WEEKDAY_JP[now.weekday()]})"

    if zip_path is None:
        return (
            f"⚠️ **【週次バックアップ】{date_text}**\n"
            "バックアップ対象のファイルが1つも見つかりませんでした。"
            "data/ のマウント設定を確認してください。"
        )

    size_kb = os.path.getsize(zip_path) / 1024
    msg = (
        f"🗄️ **【週次バックアップ】{date_text}**\n"
        f"{len(included)}ファイル / {size_kb:,.1f} KB\n"
        f"収録: {', '.join(included)}"
    )

    if missing:
        msg += f"\n（未作成のため未収録: {', '.join(missing)}）"

    if not is_within_upload_limit(zip_path):
        msg += (
            "\n⚠️ 添付上限に近づいたため、ZIPは添付していません。"
            "ホストの data/_backups/ に保存済みです。Google Driveへの保存を検討してください。"
        )

    return msg
