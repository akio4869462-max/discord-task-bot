"""データバックアップモジュール

data/ 配下の学習記録・タスク・演習成績などを1つのZIPにまとめ、Discordへ
添付できる形で返します。ホスト（EC2）上の data/ にしか存在しないデータが、
インスタンス消失とともに失われるのを防ぐための仕組みです。

⭕ 対象ファイルは「許可リスト方式」で管理しています。data/ を丸ごと固める
   のではなく、ここに列挙したファイルだけをZIPに入れるため、認証情報
   （data/service_account.json）が設計上バックアップへ混入しません。
"""

import json
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
    'stable.json',          # 厩舎（現役馬・引退馬・成長）
    'player_data.json',     # 旧・就活RPGの記録（初代馬への移行元）
    'glossary.json',        # ストックした用語
    'exam_data.json',       # 演習成績
    'training_data.json',   # トレーニングログ・体組成
    'typing_data.json',     # タイピング記録
    'news_keywords.json',   # ニュース検索キーワード
)

# 許可リストに万一混ざっても弾く二重の防波堤
DENYLIST = ('service_account.json',)

# ホスト上に残すZIPの世代数。⭕ 日次にしたので、1週間ぶん＋復元前の退避が残る程度にする
KEEP_ARCHIVES = 10

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


def create_archive(now=None, label=None):
    """対象ファイルを1つのZIPにまとめ、(パス, 収録した名前, 未収録の名前) を返します。

    label を渡すとファイル名に足す（復元前の退避など、日次のZIPと別に残したいとき）。
    """
    now = now or datetime.now(JST)
    found, missing = collect_targets()

    if not found:
        return None, [], missing

    os.makedirs(BACKUP_DIR, exist_ok=True)
    suffix = f"_{label}" if label else ''
    zip_path = os.path.join(BACKUP_DIR, f"backup_{now.strftime('%Y-%m-%d')}{suffix}.zip")

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
            f"⚠️ **【バックアップ】{date_text}**\n"
            "バックアップ対象のファイルが1つも見つかりませんでした。"
            "data/ のマウント設定を確認してください。"
        )

    size_kb = os.path.getsize(zip_path) / 1024
    msg = (
        f"🗄️ **【バックアップ】{date_text}**\n"
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


# ====================================================
# 復元
# ====================================================
# ⭕ バックアップはあっても、戻す手段がEC2へのSSHしか無かった。ZIPをDiscordに添付して
#    /restore すれば戻せるようにする。書き戻すのは許可リストのファイルだけ。
#    上書きの前に今の状態をZIPに退避するので、間違えても1つ前に戻れる。
MAX_RESTORE_BYTES = MAX_UPLOAD_BYTES


def inspect_archive(zip_path):
    """復元用ZIPの中身を調べ、(復元できる名前, 無視する名前, エラー文) を返します。"""
    if os.path.getsize(zip_path) > MAX_RESTORE_BYTES:
        return [], [], "ZIPが大きすぎます。"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None:
                return [], [], "ZIPが壊れています。"
            names = archive.namelist()
    except zipfile.BadZipFile:
        return [], [], "ZIPとして読めません。"

    accepted, ignored = [], []
    for name in names:
        base = os.path.basename(name)
        # ディレクトリを含む名前・許可リスト外・秘密鍵は書き戻さない
        if name != base or base not in BACKUP_TARGETS or base in DENYLIST:
            ignored.append(name)
        else:
            accepted.append(base)
    if not accepted:
        return [], ignored, "復元できるファイルが入っていません。"
    return accepted, ignored, None


def restore_archive(zip_path, now=None):
    """ZIPの中の許可リストのファイルを data/ へ書き戻します。

    Returns:
        (復元した名前, 退避したZIPのパス or None, エラー文 or None)
    """
    accepted, _, error = inspect_archive(zip_path)
    if error:
        return [], None, error

    # 上書きの前に今の状態を退避する
    now = now or datetime.now(JST)
    snapshot, _, _ = create_archive(now, label=f"before-restore-{now.strftime('%H%M%S')}")

    os.makedirs(DATA_DIR, exist_ok=True)
    restored = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in accepted:
            data = archive.read(name)
            try:
                json.loads(data.decode('utf-8'))       # 壊れたJSONを置いてBotを落とさない
            except (ValueError, UnicodeDecodeError):
                continue
            target = os.path.join(DATA_DIR, name)
            tmp = target + '.restoring'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, target)                    # 書き込み途中の状態を見せない
            restored.append(name)
    return restored, snapshot, None


def build_restore_message(restored, snapshot, error):
    if error:
        return f"❌ 復元できませんでした: {error}"
    msg = f"♻️ **復元しました**（{len(restored)}ファイル）\n収録: {', '.join(restored)}"
    if snapshot:
        msg += f"\n上書き前の状態は `{os.path.basename(snapshot)}` に退避してあります。"
    msg += "\n各機能は次に開いたときから復元後のデータを読みます（再起動は不要）。"
    return msg
