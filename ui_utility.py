"""「その他」メニュー（バックアップ・ニュース手動確認）と週次バックアップの定期処理"""

import asyncio
from datetime import datetime

import discord
from discord.ext import tasks
from discord.ui import View

import backup_logic
import news_logic
from bot_state import client, tree, JST, BACKUP_CHANNEL_ID, BACKUP_TIME, BACKUP_WEEKDAY


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
                f"❌ **【週次バックアップ】失敗しました**\n`{type(error).__name__}: {error}`"
            )
        except Exception:
            pass
        return f"失敗しました: {type(error).__name__}: {error}"


@tasks.loop(time=BACKUP_TIME)
async def weekly_backup_task():
    """毎週決まった曜日に、データのバックアップをDiscordへ自動で書き出します。"""
    await client.wait_until_ready()

    if datetime.now(JST).weekday() != BACKUP_WEEKDAY:
        return

    print("🗄️ [週次バックアップ] 実行中...")
    await run_backup(client.get_channel(BACKUP_CHANNEL_ID))


class UtilityMenuView(View):
    """「その他」サブメニュー：データ出力・ニュース確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary, row=0)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ⭕ ephemeralな返信は自分にしか見えず消えるため、保管場所としては機能しない。
        #    週次バックアップと同じ経路でチャンネルへ残す。
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


@tree.command(name="backup", description="いまのデータをZIPにしてバックアップチャンネルへ送ります")
async def backup_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await run_backup(client.get_channel(BACKUP_CHANNEL_ID))
    await interaction.followup.send(
        "バックアップを実行しました。バックアップチャンネルを確認してください。", ephemeral=True
    )
