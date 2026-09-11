"""「その他」メニュー（バックアップ・ニュース手動確認）、日次バックアップの定期処理、復元"""

import asyncio
import os
import tempfile

import discord
from discord.ext import tasks
from discord.ui import View

import backup_logic
import news_logic
from bot_state import client, tree, BACKUP_CHANNEL_ID, BACKUP_TIME


async def run_backup(channel):
    """データをZIPにまとめてチャンネルへ添付します。

    ⭕ バックアップの失敗でBot本体が止まらないよう、例外はここで受け止めます。
       「静かに失敗して気づかない」のが一番怖いので、失敗もチャンネルへ通知します。
    """
    if channel is None:
        print("⚠️ [バックアップ] 送信先チャンネルが見つかりませんでした。")
        return "送信先チャンネルが見つかりませんでした。"

    try:
        zip_path, included, missing = await asyncio.to_thread(backup_logic.create_archive)
        message = backup_logic.build_message(zip_path, included, missing)

        if zip_path and backup_logic.is_within_upload_limit(zip_path):
            await channel.send(message, file=discord.File(zip_path))
        else:
            await channel.send(message)

        await asyncio.to_thread(backup_logic.prune_old_archives)
        print(f"🗄️ [バックアップ] 完了: {included}")
        return message

    except Exception as error:
        print(f"❌ [バックアップ] 失敗: {type(error).__name__}: {error}")
        try:
            await channel.send(
                f"❌ **【バックアップ】失敗しました**\n`{type(error).__name__}: {error}`"
            )
        except Exception:
            pass
        return f"失敗しました: {type(error).__name__}: {error}"


@tasks.loop(time=BACKUP_TIME)
async def daily_backup_task():
    """毎日、データのバックアップをDiscordへ自動で書き出します。

    ⭕ 週1だと最悪1週間ぶんのレースと配合が消える。データは数十KBなので毎日でも軽い。
    """
    await client.wait_until_ready()
    print("🗄️ [バックアップ] 実行中...")
    await run_backup(client.get_channel(BACKUP_CHANNEL_ID))


class UtilityMenuView(View):
    """「その他」サブメニュー：データ出力・ニュース確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary, row=0)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ⭕ ephemeralな返信は自分にしか見えず消えるため、保管場所としては機能しない。
        #    日次バックアップと同じ経路でチャンネルへ残す。
        await interaction.response.defer(ephemeral=True)
        await run_backup(client.get_channel(BACKUP_CHANNEL_ID))
        await interaction.followup.send(
            "バックアップチャンネルへ書き出しました。", ephemeral=True
        )

    @discord.ui.button(label="📰 最新ITニュースを確認", style=discord.ButtonStyle.primary, row=0)
    async def news_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        news_msg = await asyncio.to_thread(news_logic.get_it_news)
        await interaction.followup.send(news_msg, ephemeral=True)


# ====================================================
# 復元
# ====================================================
# ⭕ バックアップチャンネルのZIPを添付して /restore すると data/ に書き戻す。
#    上書きは取り返しがつかないので、中身を見せてボタンで確認してから実行する。
#    書き戻すのは backup_logic の許可リストのファイルだけで、秘密鍵は決して触らない。
class RestoreConfirmView(View):
    def __init__(self, zip_path):
        super().__init__(timeout=120)
        self.zip_path = zip_path

    @discord.ui.button(label="このZIPで上書きする", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        restored, snapshot, error = await asyncio.to_thread(backup_logic.restore_archive, self.zip_path)
        self._cleanup()
        await interaction.response.edit_message(
            content=backup_logic.build_restore_message(restored, snapshot, error), view=None)

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._cleanup()
        await interaction.response.edit_message(content="復元はやめました。", view=None)

    async def on_timeout(self):
        self._cleanup()

    def _cleanup(self):
        try:
            os.remove(self.zip_path)
        except OSError:
            pass


@tree.command(name="restore", description="バックアップのZIPを添付して、データを書き戻します")
@discord.app_commands.describe(archive="バックアップチャンネルに残っている backup_YYYY-MM-DD.zip")
async def restore_command(interaction: discord.Interaction, archive: discord.Attachment):
    if not archive.filename.lower().endswith('.zip'):
        await interaction.response.send_message("ZIPファイルを添付してください。", ephemeral=True)
        return
    if archive.size > backup_logic.MAX_RESTORE_BYTES:
        await interaction.response.send_message("ZIPが大きすぎます。", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    fd, path = tempfile.mkstemp(suffix='.zip')
    os.close(fd)
    await archive.save(path)
    accepted, ignored, error = await asyncio.to_thread(backup_logic.inspect_archive, path)
    if error:
        os.remove(path)
        await interaction.followup.send(f"❌ {error}", ephemeral=True)
        return

    text = (f"**{archive.filename}** を data/ に書き戻します。\n"
            f"書き戻す: {', '.join(accepted)}")
    if ignored:
        text += f"\n無視する: {', '.join(ignored)}"
    text += "\n\n今のデータは上書きの前にZIPへ退避します。よろしいですか？"
    await interaction.followup.send(text, view=RestoreConfirmView(path), ephemeral=True)


@tree.command(name="backup", description="いまのデータをZIPにしてバックアップチャンネルへ送ります")
async def backup_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await run_backup(client.get_channel(BACKUP_CHANNEL_ID))
    await interaction.followup.send(
        "バックアップを実行しました。バックアップチャンネルを確認してください。", ephemeral=True
    )
