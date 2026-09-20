"""馬みくじ（お遊び機能）のスラッシュコマンド"""

import discord

import fortune_logic
from bot_state import tree


@tree.command(name="umamikuji", description="馬みくじで今日の運勢を占います(お遊び機能)")
async def umamikuji_command(interaction: discord.Interaction):
    fortune = fortune_logic.draw_fortune()
    display_name = interaction.user.display_name
    await interaction.response.send_message(
        fortune_logic.format_fortune_message(fortune, display_name)
    )
